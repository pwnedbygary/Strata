#!/usr/bin/env python3
"""Add profiles for the locally tested Swift/Tiel/0.8B files; retain existing registry entries."""
import argparse
import copy
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


def apply_dense_tuning(cfg, args):
    if args.dense_prefill_tuning:
        cfg['env']['STRATA_HIPBLASLT_TUNING'] = '@bundle/tools/hip/gfx1201-qwen35-dense-hipblaslt-100202.txt'
    if args.dense_memory_fit:
        cfg['env'].update(STRATA_Q35_KV_GROW_STEP='4096', STRATA_Q35_RESERVE_MIB=str(args.dense_reserve_mib),
                          STRATA_Q35_ADAPTIVE_WEIGHTS='1')
        if cfg['args'][cfg['args'].index('--mtp')+1] != '0':
            cfg['env']['STRATA_Q35_ADAPTIVE_MTP'] = '1'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--models', type=Path, default=ROOT/'models')
    parser.add_argument('--packs', type=Path, default=ROOT/'packs')
    parser.add_argument('--base-config', type=Path, default=ROOT/'strata-saluki27-adaptive.json')
    parser.add_argument('--registry', type=Path, default=Path.home()/'.config/strata/router.json')
    parser.add_argument('--swift-mtp', action='store_true', help='enable embedded Swift MTP; context and draft count are configurable')
    parser.add_argument('--swift-mtp-drafts', type=int, choices=(1,2), default=1, help='greedy Swift MTP proposals per verification (default 1)')
    parser.add_argument('--mtp-context', type=int, default=8192, help='MTP limit, 4K multiples through 256K; larger limits opt into adaptive MTP')
    parser.add_argument('--include-q8-compat', action='store_true', help='explicitly permit lossy 0.8B projection compatibility conversion')
    parser.add_argument('--vision', action='store_true', help='add separate CPU screenshot-encoder profiles; requires a vision-enabled build')
    parser.add_argument('--vision-tokens', type=int, default=2048, help='visual-token budget per screenshot (default 2048)')
    parser.add_argument('--saluki-abliterated', action='store_true', help='add 256K Saluki abliterated screenshot profiles with MTP off/on')
    parser.add_argument('--saluki-128k-tuning', action='store_true', help='opt into tested RX9070XT filled-128K Saluki MTP memory/attention settings; requires the updated engine')
    parser.add_argument('--remove-swift-mtp', action='store_true', help='remove Swift MTP selections from the registry, retaining their files')
    parser.add_argument('--dense-prefill-tuning', action='store_true', help='opt into measured gfx1201/hipBLASLt 100202 dense calibration')
    parser.add_argument('--dense-memory-fit', action='store_true', help='opt into 4K KV growth and a smaller reserve; measured Swift IQ3_S')
    parser.add_argument('--dense-reserve-mib', type=int, default=2048, help='reserve with --dense-memory-fit (1536..8192; default 2048)')
    parser.add_argument('--only', action='append', choices=['swift27-iq3-s', 'swift27-iq3-xxs', 'saluki27-abliterated'], help='limit newly generated profiles to this family (repeatable)')
    args = parser.parse_args()
    if not 1536 <= args.dense_reserve_mib <= 8192:
        parser.error('--dense-reserve-mib must be 1536..8192')
    if args.mtp_context not in range(4096, 262145, 4096):
        parser.error('--mtp-context must be a 4K multiple through 262144')
    if args.vision_tokens not in range(256,4097):
        parser.error('--vision-tokens must be between 256 and 4096')
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
        if args.only and not any(name == family or name.startswith(family+'-') for family in args.only):
            continue
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
                cfg['args'][cfg['args'].index('--max-context')+1] = str(args.mtp_context)
                cfg['args'][cfg['args'].index('--mtp')+1] = str(args.swift_mtp_drafts)
                cfg['env'].pop('STRATA_Q35_ADAPTIVE_WEIGHTS', None)
                cfg['sampling'] = {**cfg.get('sampling', {}), 'temperature': 0}
                if args.mtp_context > 8192:
                    cfg['env'].update(STRATA_Q35_ADAPTIVE_WEIGHTS='1', STRATA_Q35_ADAPTIVE_MTP='1')
                title = f'Swift 1.5 27B {quant} — {args.mtp_context//1024}K, MTP drafting on ({args.swift_mtp_drafts} draft{"s" if args.swift_mtp_drafts != 1 else ""})'
                if args.mtp_context > 8192:
                    title += '; adaptive GPU/file weights'
            elif mtp_file:
                title += '; contains MTP weights, drafting off'
            cfg['router'] = {'display_name': title}
            apply_dense_tuning(cfg, args)
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
        if kind == 'swift' and mtp_file and args.swift_mtp and args.mtp_context > 8192 and not args.dense_memory_fit:
            fast_name = name + '-fast-8k'
            fast = copy.deepcopy(cfg)
            fast['args'][fast['args'].index('--max-context')+1] = '8192'
            fast['env'].pop('STRATA_Q35_ADAPTIVE_WEIGHTS', None)
            fast['env'].pop('STRATA_Q35_ADAPTIVE_MTP', None)
            fast['model_name'] = fast_name
            fast['router']['display_name'] = f'Swift 1.5 27B {quant} — fast 8K MTP'
            fast_path = args.registry.parent/'profiles'/(fast_name+'.json')
            fast['log'] = str(fast_path.resolve().with_suffix('.log'))
            save(fast_path, fast)
            registry['profiles'][fast_name] = str(fast_path.resolve())
        registry['profiles'][name] = str(path.resolve())
        # Retire the temporary labels used before MTP validation.
        if mtp_file:
            registry['profiles'].pop(name+'-file', None)
        added.append(name)
        if args.vision and kind == 'swift' and (not mtp_file or args.dense_memory_fit):
            mmproj = args.models/'mmproj-Swift-1.5-Qwen3.8-27B-F16.gguf'
            if mmproj.is_file():
                add_vision_profile(cfg, name, model, mmproj, registry, args.registry.parent, args.vision_tokens,
                                   int(cfg['args'][cfg['args'].index('--mtp')+1]))
    if args.vision and not args.only and 'saluki27' in registry['profiles']:
        entry = registry['profiles']['saluki27']
        source = Path(entry) if isinstance(entry, str) else None
        if source and not source.is_absolute():
            source = args.registry.parent/source
        saluki = json.loads(source.read_text()) if source else entry
        model = args.models/'Underdog-Saluki-27B-1.0-IQ2-mix.gguf'
        mmproj = args.models/'mmproj-Underdog-Saluki-27B-1.0-F16.gguf'
        if model.is_file() and mmproj.is_file():
            add_vision_profile(saluki, 'saluki27', model, mmproj, registry, args.registry.parent, args.vision_tokens)
    if args.saluki_abliterated and (not args.only or 'saluki27-abliterated' in args.only):
        model = args.models/'Underdog-Saluki-27B-1.0-IQ2-mix-MTP-abliterated.gguf'
        mmproj = args.models/'mmproj-Underdog-Saluki-27B-1.0-F16.gguf'
        if not model.is_file() or not mmproj.is_file():
            parser.error('Saluki abliterated GGUF and matching Saluki mmproj are required')
        name = 'saluki27-abliterated'
        pack = args.packs/name
        extract(model, pack)
        cfg = prepare(base, model, pack/'tokenizer', 262144, 512, attention_score_mib=128)
        apply_dense_tuning(cfg, args)
        cfg.update(exe='@bundle/dense-hip', cwd=str(args.registry.resolve().parent))
        cfg['router'] = {'display_name': 'Saluki 27B abliterated IQ2-mix — adaptive 256K'}
        tuning = cfg.get('env', {}).get('STRATA_HIPBLASLT_TUNING')
        if tuning and (ROOT/'tools/hip'/Path(tuning).name).is_file():
            cfg['env']['STRATA_HIPBLASLT_TUNING'] = '@bundle/tools/hip/' + Path(tuning).name
        for drafts in (0, 2 if args.saluki_128k_tuning else 1):
            profile = name + ('-mtp' if drafts else '')
            selected = copy.deepcopy(cfg)
            if drafts and args.saluki_128k_tuning:
                selected['env'].update(STRATA_Q35_ATTN_HEAD_REUSE='1', STRATA_Q35_PREFILL_LOAN='1',
                                       STRATA_Q35_KV_GROW_STEP='4096', STRATA_Q35_ATTN_SCORE_MIB='256',
                                       STRATA_Q35_RESERVE_MIB='1536', STRATA_Q35_PHYSICAL_RESERVE_MIB='1024',
                                       STRATA_Q35_ADAPTIVE_WEIGHTS='1', STRATA_Q35_KV_I8='1',
                                       STRATA_HIPBLASLT_TUNING='@bundle/tools/hip/gfx1201-qwen35-dense-hipblaslt-100202.txt')
            add_vision_profile(selected, profile, model, mmproj, registry, args.registry.parent, args.vision_tokens, drafts)
            added.append(profile+'-vision')
    if args.remove_swift_mtp:
        for profile in list(registry['profiles']):
            if profile.startswith('swift27-') and '-mtp' in profile:
                del registry['profiles'][profile]
        added = [name for name in added if not (name.startswith('swift27-') and '-mtp' in name)]
        if registry.get('default') not in registry['profiles']:
            registry['default'] = next(iter(registry['profiles']))
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
    print('Restart the router to read the updated registry.' +
          (' Disabled Tiel entries are listed but cannot load.' if any(n in registry['profiles'] for n in ('tiel-coder', 'cyber-tiel')) else ''))


def add_vision_profile(base, name, model, mmproj, registry, directory, image_tokens=2048, drafts=0):
    cfg = copy.deepcopy(base)
    name += '-vision'
    cfg['model_name'] = name
    cfg['args'][cfg['args'].index('--mtp')+1] = str(drafts)
    if '--vision' not in cfg['args']:
        cfg['args'].append('--vision')
    cfg['env'].pop('STRATA_Q35_ADAPTIVE_MTP', None)
    if drafts:
        cfg['env']['STRATA_Q35_ADAPTIVE_MTP'] = '1'
        cfg['sampling'] = {**cfg.get('sampling', {}), 'temperature': 0}
    cfg['env']['STRATA_Q35_VISION'] = '1'
    cfg['vision'] = {'exe': '@bundle/vision-cpu', 'model': str(model.resolve()),
                     'mmproj': str(mmproj.resolve()), 'gpu': False, 'threads': 4, 'max_tokens': image_tokens}
    draft_label = f'on ({drafts} draft{"s" if drafts != 1 else ""})' if drafts else 'off'
    cfg['router'] = {'display_name': base.get('router', {}).get('display_name', name.removesuffix('-vision')) + f' — screenshots, MTP {draft_label}'}
    path = directory/'profiles'/(name+'.json')
    cfg['log'] = str(path.resolve().with_suffix('.log'))
    save(path, cfg)
    registry['profiles'][name] = str(path.resolve())


if __name__ == '__main__':
    main()
