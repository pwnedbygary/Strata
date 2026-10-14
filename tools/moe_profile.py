#!/usr/bin/env python3
"""Inspect GGUF MoE families and prepare an opt-in qwen35moe HIP trial."""
import argparse
import copy
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.gguf_reader import GGUFFile
from tools.hardware_profile import write, recover_failed_scope

GATE_TYPES={'IQ2_XXS','IQ2_XS','IQ3_XXS','IQ3_S','IQ2_S','IQ4_XS','IQ1_M','Q2_0','Q4_K','Q5_K','Q5_0','Q4_0','Q4_1','Q8_0','NVFP4'}
DOWN_TYPES={'IQ4_NL','IQ4_XS','Q2_0','Q5_1','Q5_0','Q4_0','Q4_1','Q8_0','Q5_K','NVFP4'}


def describe(model):
    g = GGUFFile(model)
    arch = g.metadata.get('general.architecture', '')
    routed = [t for t in g.tensors if '_exps.' in t.name]
    unknown = [t.name for t in routed if t.expected_bytes() is None]
    if unknown:
        raise ValueError('expert sizes are unknown: ' + ', '.join(unknown[:3]))
    directory={t.name:t for t in g.tensors}
    layout_ok=True
    if arch=='qwen35moe':
        for i in range(g.metadata.get('qwen35moe.block_count',0)):
            tensors=[directory.get(f'blk.{i}.ffn_{role}_exps.weight') for role in ('gate','up','down')]
            if not all(tensors) or [t.shape for t in tensors]!=[[2048,512,256],[2048,512,256],[512,2048,256]] or tensors[0].type_name!=tensors[1].type_name:
                layout_ok=False
            shared_gate=directory.get(f'blk.{i}.ffn_gate_inp_shexp.weight')
            if shared_gate is None or shared_gate.shape != [2048]:
                layout_ok=False
    return {'architecture': arch, 'model': str(Path(model).resolve()),
            'metadata': {k: v for k, v in g.metadata.items() if k.startswith(arch+'.') and isinstance(v,(int,float))},
            'file_gib': Path(model).stat().st_size / 2**30,
            'expert_gib': sum(t.expected_bytes() for t in routed) / 2**30,
            'expert_types': sorted({t.type_name for t in routed}), 'expert_tensors': len(routed),
            'gate_types':sorted({t.type_name for t in routed if 'ffn_gate_exps' in t.name}),
            'up_types':sorted({t.type_name for t in routed if 'ffn_up_exps' in t.name}),
            'down_types':sorted({t.type_name for t in routed if 'ffn_down_exps' in t.name}),
            'expert_layout_valid':layout_ok}


def prepare(base, info, tokenizer):
    if base.get('backend') != 'hip':
        raise ValueError('this trial profile is measured only on HIP')
    if info['architecture'] != 'qwen35moe':
        raise ValueError('this adapter requires qwen35moe; Flash-Next uses hardware_profile.py, other families need an engine adapter')
    m = info['metadata']; prefix='qwen35moe.'
    expected={'embedding_length':2048,'expert_count':256,'expert_used_count':8,
              'full_attention_interval':4,'attention.key_length':256,'attention.value_length':256,
              'attention.head_count':16,'attention.head_count_kv':2,
              'expert_feed_forward_length':512,'expert_shared_feed_forward_length':512,
              'ssm.state_size':128,'ssm.conv_kernel':4,'ssm.group_count':16,
              'ssm.time_step_rank':32,'ssm.inner_size':4096,'rope.dimension_count':64}
    for key,value in expected.items():
        if m.get(prefix+key)!=value:
            raise ValueError('unvalidated geometry: '+key)
    if prefix+'nextn_predict_layers' not in m:
        raise ValueError('missing explicit MTP count; a verified no-MTP file needs gguf_no_mtp.py first')
    mtp=m[prefix+'nextn_predict_layers']
    if mtp not in (0,1) or m.get(prefix+'block_count',0)-mtp!=40 or info['expert_tensors']!=(40+mtp)*3:
        raise ValueError('expected 40 main layers and zero or one embedded MTP layer with three expert tensors each')
    if not info['expert_layout_valid']:
        raise ValueError('expert tensor shapes differ from the native engine layout; no automatic reshape is performed')
    if not info['gate_types'] or set(info['gate_types'])!=set(info['up_types']) or not set(info['gate_types'])<=GATE_TYPES or not set(info['down_types'])<=DOWN_TYPES:
        raise ValueError('expert projection formats are not accepted by this conservative default-build adapter')
    # This adapter duplicates all routed weights in host memory when hybrid.
    if info['expert_gib'] + 3 > 16:
        raise ValueError('all-host expert allocation plus 3 GiB overhead exceeds the 16 GiB trial allowance; choose a smaller quant')
    if base.get('parallel',1)!=1 or base.get('replicas') or base.get('vision'):
        raise ValueError('one text-only request on one GPU is required')
    gpu=base.get('gpu',0)
    if isinstance(gpu,list) and len(gpu)!=1 or isinstance(gpu,str) and ',' in gpu:
        raise ValueError('one GPU is required')
    cfg=copy.deepcopy(base)
    cfg['args']=['--native',info['model'],'--max-context','8192','--prefill','256',
                 '--expert-vram','6','--cpu-threads','7','--mtp','0']
    cfg['arch']='qwen35moe';cfg['tokenizer']=str(Path(tokenizer).resolve())
    cfg['model_name']=Path(info['model']).stem.lower();cfg['log']=str(ROOT/'strata-moe-trial.log')
    cfg['env']={k:v for k,v in base.get('env',{}).items() if not k.startswith('STRATA_') or k=='STRATA_HIPBLASLT_TUNING'}
    return cfg


def launch(cfg, path):
    info=describe(Path(cfg['args'][cfg['args'].index('--native')+1]))
    # Recheck the same geometry/memory contract before launching an edited config.
    checked=prepare(cfg,info,cfg['tokenizer'])
    if checked['args']!=cfg['args']:
        raise ValueError('trial settings changed; only the validated 8K/6GiB/MTP-off profile can run here')
    if not (Path(cfg['tokenizer'])/'tokenizer.json').is_file():
        raise ValueError('export this model\'s own tokenizer before running')
    host=cfg.get('host') or '127.0.0.1'
    if host not in ('127.0.0.1','localhost','::1') and not (cfg.get('api_key') or os.getenv('STRATA_API_KEY')):
        raise ValueError('a public bind requires an API key')
    supported=subprocess.check_output([cfg['exe'],'--families'],text=True).split()
    if info['architecture'] not in supported:
        raise ValueError('this engine build does not advertise the selected family')
    recover_failed_scope()
    if subprocess.run(['systemctl','--user','is-active','--quiet','strata-local.scope']).returncode==0:
        raise ValueError('stop the current strata-local.scope before starting a second model')
    controllers=Path('/sys/fs/cgroup/cgroup.controllers')
    if not controllers.is_file() or 'memory' not in controllers.read_text().split():
        raise ValueError('cgroup v2 memory accounting is required')
    available=next(int(s.split()[1])*1024 for s in Path('/proc/meminfo').read_text().splitlines() if s.startswith('MemAvailable:'))/2**30
    if available < info['expert_gib']+4:
        raise ValueError(f'available RAM {available:.1f} GiB is below expert allocation + 4 GiB headroom')
    argv=['systemd-run','--user','--scope','--unit=strata-local','-p','MemoryMax=20G','-p','MemorySwapMax=0',
          str(ROOT/'.venv/bin/python'),str(ROOT/'serve/server.py'),'--engine','strata','--config',str(path.resolve()),
          '--host',host,'--port',str(cfg.get('port') or 8096)]
    os.chdir(ROOT);os.execvp(argv[0],argv)


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    inspect=sub.add_parser('inspect');inspect.add_argument('gguf',type=Path)
    make=sub.add_parser('prepare');make.add_argument('--gguf',type=Path,required=True)
    make.add_argument('--base-config',type=Path,required=True);make.add_argument('--tokenizer',type=Path,required=True)
    make.add_argument('--output',type=Path,required=True)
    run=sub.add_parser('run');run.add_argument('--config',type=Path,required=True)
    a=p.parse_args()
    try:
        if a.action=='inspect':print(json.dumps(describe(a.gguf),indent=2))
        elif a.action=='prepare':
            cfg=prepare(json.loads(a.base_config.read_text()),describe(a.gguf),a.tokenizer)
            write(cfg,a.base_config,a.output,False);print(a.output)
        else:launch(json.loads(a.config.read_text()),a.config)
    except (ValueError,OSError,KeyError,subprocess.CalledProcessError) as error:p.error(str(error))


if __name__=='__main__':main()
