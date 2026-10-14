#!/usr/bin/env python3
"""Opt-in native dense Qwen35 27B HIP profile; original GGUF weights and int8 KV."""
import argparse
import copy
import json
import math
import os
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.gguf_reader import GGUFFile
from tools.hardware_profile import write, recover_failed_scope


def prepare(base, model, tokenizer, context=163840, prefill=512, weight_vram_gib=None, attention_score_mib=32, adaptive=None):
    if adaptive is None:adaptive=weight_vram_gib is None
    if adaptive and weight_vram_gib is not None:raise ValueError('choose adaptive or fixed placement')
    if base.get('backend')!='hip':raise ValueError('this hardware profile is validated only on HIP')
    if context not in range(4096,262145,4096) or prefill not in (128,256,512,1024,2048,4096):
        raise ValueError('context must be a 4K multiple through 256K; prefill must be 128/256/512/1024/2048/4096')
    if attention_score_mib not in (32,64,128,256) or (weight_vram_gib is not None and (not math.isfinite(weight_vram_gib) or not 1<=weight_vram_gib<=15)):
        raise ValueError('invalid weight target or attention scratch size')
    if base.get('vision') or base.get('replicas') or base.get('parallel',1)!=1:
        raise ValueError('one text request, without vision or replicas, is required')
    gpu=base.get('gpu',0)
    if isinstance(gpu,list) and len(gpu)!=1 or isinstance(gpu,str) and ',' in gpu:
        raise ValueError('one GPU is required')
    g=GGUFFile(model);m=g.metadata
    if m.get('general.architecture')!='qwen35':raise ValueError('requires a dense qwen35 GGUF')
    expected={'embedding_length':5120,'feed_forward_length':17408,'attention.head_count':24,
              'attention.head_count_kv':4,'attention.key_length':256,'attention.value_length':256,
              'ssm.state_size':128,'ssm.conv_kernel':4,'ssm.group_count':16,'ssm.time_step_rank':48,
              'ssm.inner_size':6144,'full_attention_interval':4,'rope.dimension_count':64}
    for k,v in expected.items():
        if m.get('qwen35.'+k)!=v:raise ValueError('unvalidated 27B geometry: '+k)
    mtp=m.get('qwen35.nextn_predict_layers',0)
    if mtp not in (0,1) or m.get('qwen35.block_count',0)-mtp!=64:raise ValueError('requires 64 main layers')
    if context>m.get('qwen35.context_length',0):raise ValueError('context exceeds the model metadata limit')
    supported={0,1,2,6,7,8,10,11,12,13,14,16,17,18,19,20,21,22,23,29,30,42}
    size=Path(model).stat().st_size
    for t in g.tensors:
        n=t.expected_bytes()
        if t.type_id not in supported or n is None or g.data_start+t.offset+n>size:
            raise ValueError('unknown or truncated tensor: '+t.name)
    # Projection BF16/F16 are supported only for alpha/beta float products, not arbitrary dense matrices.
    for t in g.tensors:
        if len(t.shape)==2 and t.type_id in (0,1,30) and not any(x in t.name for x in ('ssm_alpha.weight','ssm_beta.weight','ssm_conv1d.weight')):
            raise ValueError('projection would need explicit compatibility conversion: '+t.name)
    cfg=copy.deepcopy(base)
    cfg['exe']=str(ROOT/'build-hip/strata');cfg['cwd']=str(ROOT);cfg['arch']='qwen35'
    cfg['args']=['--native',str(Path(model).resolve()),'--max-context',str(context),'--prefill',str(prefill),'--mtp','0']
    cfg['tokenizer']=str(Path(tokenizer).resolve());cfg['model_name']=Path(model).stem.lower()
    cfg['log']=str(ROOT/'strata-dense-trial.log')
    cfg['env']={k:v for k,v in base.get('env',{}).items() if not k.startswith('STRATA_') or k=='STRATA_HIPBLASLT_TUNING'}
    cfg['env'].update(STRATA_Q35_DENSE='1',STRATA_Q35_NATIVE_LOWBIT='1',STRATA_Q35_KV_I8='1')
    cfg['env']['GPU_PINNED_MIN_XFER_SIZE']='1000000'
    cfg['env']['STRATA_Q35_ATTN_SCORE_MIB']=str(attention_score_mib)
    if weight_vram_gib is not None:cfg['env']['STRATA_Q35_WEIGHT_VRAM_GIB']=str(weight_vram_gib)
    if adaptive:cfg['env']['STRATA_Q35_ADAPTIVE_WEIGHTS']='1'
    return cfg


def launch(path):
    cfg=json.loads(path.read_text());args=cfg['args']
    model=args[args.index('--native')+1];context=int(args[args.index('--max-context')+1]);prefill=int(args[args.index('--prefill')+1])
    weight=cfg.get('env',{}).get('STRATA_Q35_WEIGHT_VRAM_GIB')
    checked=prepare(cfg,model,cfg['tokenizer'],context,prefill,float(weight) if weight is not None else None,int(cfg.get('env',{}).get('STRATA_Q35_ATTN_SCORE_MIB','32')),cfg.get('env',{}).get('STRATA_Q35_ADAPTIVE_WEIGHTS')=='1')
    if checked['args']!=args or checked['exe']!=cfg['exe'] or checked['env']!=cfg.get('env',{}):
        raise ValueError('config differs from the native dense profile; prepare it again')
    if not (Path(cfg['tokenizer'])/'vocab.json').is_file():raise ValueError('export this model\'s tokenizer first')
    host=cfg.get('host') or '127.0.0.1'
    if host not in ('127.0.0.1','localhost','::1') and not (cfg.get('api_key') or os.getenv('STRATA_API_KEY')):
        raise ValueError('public binding requires an API key')
    env={**os.environ,**cfg.get('env',{})}
    if 'qwen35' not in subprocess.check_output([cfg['exe'],'--families'],env=env,text=True).split():
        raise ValueError('build the development native dense engine first')
    recover_failed_scope()
    if subprocess.run(['systemctl','--user','is-active','--quiet','strata-local.scope']).returncode==0:
        raise ValueError('stop the active Strata scope before switching models')
    if not Path('/sys/fs/cgroup/cgroup.controllers').is_file() or 'memory' not in Path('/sys/fs/cgroup/cgroup.controllers').read_text().split():
        raise ValueError('requires cgroup v2 memory accounting')
    available=next(int(s.split()[1]) for s in Path('/proc/meminfo').read_text().splitlines() if s.startswith('MemAvailable:'))/2**20
    if available < Path(model).stat().st_size/2**30+2:raise ValueError('insufficient RAM headroom for loading this file')
    argv=[str(ROOT/'.venv/bin/python'),str(ROOT/'tools/benchmark_guarded.py'),'--memory-floor-gib','1.5',
          '--output',str(ROOT/'local-tuning/dense-run-memory.json'),'--','systemd-run','--user','--scope',
          '--unit=strata-local','-p','MemoryMax=20G','-p','MemorySwapMax=0',str(ROOT/'.venv/bin/python'),
          str(ROOT/'serve/server.py'),'--engine','strata','--config',str(path.resolve()),'--host',host,
          '--port',str(cfg.get('port') or 8096)]
    os.chdir(ROOT);os.execvp(argv[0],argv)


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    a=sub.add_parser('prepare');a.add_argument('--gguf',type=Path,required=True);a.add_argument('--base-config',type=Path,required=True)
    a.add_argument('--tokenizer',type=Path,required=True);a.add_argument('--output',type=Path,required=True)
    a.add_argument('--context',type=int,default=163840);a.add_argument('--prefill',type=int,default=512)
    a.add_argument('--fixed-cache',action='store_true');a.add_argument('--weight-vram-gib',type=float);a.add_argument('--attention-score-mib',type=int,default=32)
    a=sub.add_parser('run');a.add_argument('--config',type=Path,required=True)
    a=p.parse_args()
    try:
        if a.action=='prepare':write(prepare(json.loads(a.base_config.read_text()),a.gguf,a.tokenizer,a.context,a.prefill,a.weight_vram_gib,a.attention_score_mib,not a.fixed_cache and a.weight_vram_gib is None),a.base_config,a.output,False)
        else:launch(a.config)
    except (ValueError,OSError,KeyError,subprocess.CalledProcessError) as e:p.error(str(e))
if __name__=='__main__':main()
