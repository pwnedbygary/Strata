#!/usr/bin/env python3
"""Register prepared per-model configs without changing the originals."""
import argparse
import json
import os
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from serve.router import read_registry


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--profile', action='append', required=True, metavar='NAME=CONFIG')
    p.add_argument('--registry', type=Path, required=True)
    p.add_argument('--default')
    p.add_argument('--bundle-engines', action='store_true', help='use the AppImage engine executables')
    a = p.parse_args()
    a.registry.parent.mkdir(parents=True, exist_ok=True)
    profiles = {}
    for item in a.profile:
        if '=' not in item:
            p.error('Use NAME=CONFIG')
        name, source = item.split('=', 1)
        if not name or name in profiles:
            p.error('Profile names must be nonempty and unique')
        source = Path(source).resolve()
        if a.bundle_engines:
            cfg = json.loads(source.read_text())
            cfg['exe'] = '@bundle/flash-hip' if cfg.get('arch', 'qwen4exp') == 'qwen4exp' else '@bundle/dense-hip'
            # Pack paths remain external; all runtime output stays outside the read-only bundle.
            original_cwd = Path(cfg.get('cwd') or source.parent).resolve()
            for key in ('tokenizer',):
                value = Path(cfg[key]).expanduser()
                cfg[key] = str(value if value.is_absolute() else original_cwd / value)
            cfg['args'] = [str(original_cwd / arg) if isinstance(arg, str) and not arg.startswith('-')
                           and (original_cwd / arg).exists() else arg for arg in cfg['args']]
            if '--expert-profile' in cfg['args']:
                at = cfg['args'].index('--expert-profile') + 1
                if Path(cfg['args'][at]).name == 'expert-profile.bin':
                    cfg['args'][at] = '@bundle/data/expert-profile.bin'
            env = dict(cfg.get('env', {}))
            tuning = env.get('STRATA_HIPBLASLT_TUNING')
            if tuning and (ROOT/'tools/hip'/Path(tuning).name).is_file():
                env['STRATA_HIPBLASLT_TUNING'] = '@bundle/tools/hip/' + Path(tuning).name
            cfg['env'] = env
            cfg['cwd'] = str(a.registry.parent.resolve())
            path = a.registry.parent / 'profiles' / (str(len(profiles)) + '.json')
            path.parent.mkdir(exist_ok=True)
            cfg['log'] = str(path.with_suffix('.log'))
            path.write_text(json.dumps(cfg, indent=2) + '\n')
            path.chmod(0o600)
            source = path.resolve()
        profiles[name] = str(source)
    default = a.default or next(iter(profiles))
    if default not in profiles:
        p.error('Default model must be registered')
    data = {'default': default, 'profiles': profiles}
    temporary = a.registry.with_suffix('.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as output:
        output.write(json.dumps(data, indent=2) + '\n')
    read_registry(temporary)
    os.replace(temporary, a.registry)
    print(a.registry.resolve())


if __name__ == '__main__':
    main()
