#!/usr/bin/env python3
"""Add profiles for the locally tested Swift/Tiel/0.8B files; retain existing registry entries."""
import argparse
import json
import os
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.dense_profile import prepare
from tools.strata_tokenizer import extract
from serve.router import read_registry


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    fd = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(json.dumps(data, indent=2) + '\n')
    os.replace(temporary, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--models', type=Path, default=ROOT/'models')
    parser.add_argument('--packs', type=Path, default=ROOT/'packs')
    parser.add_argument('--base-config', type=Path, default=ROOT/'strata-saluki27-adaptive.json')
    parser.add_argument('--registry', type=Path, default=Path.home()/'.config/strata/router.json')
    parser.add_argument('--swift-mtp', action='store_true', help='opt in to measured 8K/one-draft Swift profiles')
    parser.add_argument('--include-q8-compat', action='store_true', help='explicitly permit lossy 0.8B projection compatibility conversion')
    args = parser.parse_args()
    base = json.loads(args.base_config.read_text())
    if base.get('backend') != 'hip':
        parser.error('These profiles were validated on the RX 9070 XT HIP build only')
    registry = json.loads(args.registry.read_text()) if args.registry.exists() else {'profiles': {}}
    added = []
    candidates = [(f'swift27-{q.lower().replace("_", "-")}' + ('-mtp' if mtp else ''),
                   f'Swift-1.5-Qwen3.8-27B-GSQ-RCO-{q}' + ('-mtp' if mtp else '') + '.gguf', 'swift', mtp)
                  for q in ('IQ3_XXS', 'IQ3_S') for mtp in (False, True)]
    candidates += [('tiel-coder', 'Tiel-Coder-35B-A3B-MTP-UD-Q4_K_XL.gguf', 'blocked', False),
                   ('cyber-tiel', 'Cyber-Tiel-Coder-35B-A3B-MTP-UD-Q4_K_XL.gguf', 'blocked', False)]
    if args.include_q8_compat:
        candidates += [('qwen35-08b-q8-compat', 'Qwen3.5-0.8B-UD-Q5_K_XL.gguf', 'small', False)]
    for name, filename, kind, mtp_file in candidates:
        model = args.models/filename
        if not model.is_file():
            continue
        pack = args.packs/name
        extract(model, pack)
        if kind == 'swift':
            cfg = prepare(base, model, pack/'tokenizer', 262144, 512, attention_score_mib=128)
            quant = 'IQ3_S' if 'IQ3_S' in filename else 'IQ3_XXS'
            title = f'Swift 1.5 27B {quant} — adaptive 256K'
            if mtp_file and args.swift_mtp:
                cfg['args'][cfg['args'].index('--max-context')+1] = '8192'
                cfg['args'][cfg['args'].index('--mtp')+1] = '1'
                cfg['env'].pop('STRATA_Q35_ADAPTIVE_WEIGHTS', None)
                cfg['sampling'] = {**cfg.get('sampling', {}), 'temperature': 0}
                title = f'Swift 1.5 27B {quant} — 8K, MTP drafting on (1 draft)'
            elif mtp_file:
                title += '; contains MTP weights, drafting off'
            cfg['router'] = {'display_name': title}
        else:
            cfg = dict(base)
            cfg['env'] = {k:v for k,v in base.get('env', {}).items() if k == 'STRATA_HIPBLASLT_TUNING'}
            cfg['arch'] = 'qwen35moe' if kind == 'blocked' else 'qwen35'
            cfg['args'] = ['--native', str(model.resolve()), '--max-context', '8192' if kind == 'blocked' else '4096',
                           '--prefill', '256' if kind == 'blocked' else '128', '--mtp', '0']
            if kind == 'blocked':
                cfg['args'] += ['--expert-vram', '6', '--cpu-threads', '7']
                cfg['router'] = {'display_name': filename.removesuffix('.gguf'), 'enabled': False,
                    'disabled_reason': 'Bundled MoE expert kernels lack Q6_K main experts and Q3_K MTP down projections; 18.64 GiB host experts exceed the conservative allowance.'}
            else:
                cfg['env'].update(STRATA_Q35_DENSE='1', STRATA_Q35_REPACK_Q8='1', STRATA_Q35_ATTN_SCORE_MIB='128')
                cfg['reasoning_effort'] = 'none'
                cfg['router'] = {'display_name': 'Qwen3.5 0.8B — 4K; Q8 compatibility conversion'}
        cfg.update(exe='@bundle/dense-hip', cwd=str(args.registry.resolve().parent),
                   tokenizer=str((pack/'tokenizer').resolve()), model_name=name)
        tuning = cfg.get('env', {}).get('STRATA_HIPBLASLT_TUNING')
        if tuning and (ROOT/'tools/hip'/Path(tuning).name).is_file():
            cfg['env']['STRATA_HIPBLASLT_TUNING'] = '@bundle/tools/hip/' + Path(tuning).name
        path = args.registry.parent/'profiles'/(name+'.json')
        cfg['log'] = str(path.resolve().with_suffix('.log'))
        save(path, cfg)
        registry['profiles'][name] = str(path.resolve())
        # Retire the temporary labels used before MTP validation.
        if mtp_file:
            registry['profiles'].pop(name+'-file', None)
        added.append(name)
    if not added:
        parser.error('None of the known candidate files were found; registry left unchanged')
    registry.setdefault('default', next(iter(registry['profiles'])))
    temporary = args.registry.with_name(args.registry.name+'.check')
    save(temporary, registry)
    try:
        read_registry(temporary)
        os.replace(temporary, args.registry)
    finally:
        temporary.unlink(missing_ok=True)
    print('Registered: '+', '.join(added))
    print('Restart the router to read the updated registry. Disabled Tiel entries are listed but cannot load.')


if __name__ == '__main__':
    main()
