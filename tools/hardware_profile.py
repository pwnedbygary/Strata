#!/usr/bin/env python3
"""Create and run an opt-in RX 9070 XT / 32 GiB Linux configuration."""
from __future__ import annotations

import argparse
import copy
import json
import os
import shlex
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILE = 'rx9070xt-32gb'
OPTIONS = {
    '--max-context': '131072', '--kv': 'int8', '--kv-resident': '32768',
    '--expert-cache': 'auto', '--prefill': 'auto',
    '--resident-budget-gib': '11', '--vram-reserve-mib': '3072',
    '--adapt-async': '1', '--aux-cpus': 'auto',
}
ENV = {
    'STRATA_RESIDENT_PIN': '1', 'STRATA_STAGE_PIN': '0',
    'STRATA_RESIDENT_HEADROOM_GIB': '4', 'STRATA_PIN_GUARD': '2',
    'STRATA_PIN_RESERVE_GIB': '4', 'STRATA_UNBUFFERED_LOAD': '1',
}


def validate(config: dict) -> None:
    if config.get('backend') != 'hip':
        raise ValueError('this profile requires a HIP configuration')
    args = config.get('args')
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        raise ValueError('args must be a list of strings')
    if '--pack' not in args or '--native' not in args:
        raise ValueError('this profile requires a native Flash-Next pack')
    forbidden = {'--layer-split', '--peer-device', '--batch', '--batch-groups', '--gpus'}
    if forbidden.intersection(args) or config.get('parallel', 1) != 1 or config.get('replicas'):
        raise ValueError('this profile is for one GPU and one request at a time')
    gpu = config.get('gpu', 0)
    if isinstance(gpu, list) and len(gpu) != 1 or isinstance(gpu, str) and ',' in gpu:
        raise ValueError('this profile is for one GPU')
    if config.get('vision'):
        raise ValueError('this profile was measured with images disabled')


def apply(config: dict, repeatable: bool = False) -> dict:
    """Return a separate configuration, keeping model paths and unrelated settings."""
    validate(config)
    result = copy.deepcopy(config)
    args = config['args']
    remove_flags = {'--resident-experts', '--resident-cpu-experts', '--mmap-experts'}
    replace_values = set(OPTIONS) | {'--pcie-frac'}
    kept = []
    i = 0
    while i < len(args):
        value = args[i]
        if value in replace_values:
            if i + 1 == len(args) or args[i + 1].startswith('--'):
                raise ValueError(f'{value} has no value')
            i += 2
        elif value in remove_flags:
            i += 1
        else:
            kept.append(value)
            i += 1
    for flag, value in OPTIONS.items():
        kept.extend([flag, value])
    result['args'] = kept
    env = result.setdefault('env', {})
    if not isinstance(env, dict):
        raise ValueError('env must be an object')
    # Prefetch staging does not apply to the unbuffered file tier.
    for name in ('STRATA_IO_PREFETCH', 'STRATA_IO_PF_STAGE'):
        env.pop(name, None)
    env.update(ENV)
    if repeatable:
        for flag, value in {'--adapt-async': '0', '--adapt-swaps': '0',
                            '--pcie-frac': '0', '--prompt-cache': '0'}.items():
            while flag in kept:
                at = kept.index(flag)
                del kept[at:at + 2]
            kept.extend([flag, value])
        env['STRATA_ROUTE_TAIL_SKIP'] = '0'
    return result


def command(config: dict, path: Path) -> list[str]:
    """The server and its engine share one bounded scope across these launchers."""
    validate(config)
    if '--resident-budget-gib' not in config['args']:
        raise ValueError('apply the hardware profile first; a resident RAM budget is required')
    if sys.platform != 'linux':
        raise ValueError('the memory-limited launcher requires Linux and systemd')
    host = config.get('host') or '127.0.0.1'
    if host not in ('127.0.0.1', 'localhost', '::1') and not (
            config.get('api_key') or os.environ.get('STRATA_API_KEY')):
        raise ValueError('a non-loopback host requires an API key')
    python = ROOT / '.venv' / 'bin' / 'python'
    if not python.is_file():
        raise ValueError('run setup.sh first to create the Python environment')
    return ['systemd-run', '--user', '--scope', '--unit=strata-local',
            '-p', 'MemoryMax=20G', '-p', 'MemorySwapMax=0',
            str(python), str(ROOT / 'serve' / 'server.py'), '--engine', 'strata',
            '--config', str(path.resolve()), '--host', host,
            '--port', str(config.get('port') or 8080)]


def write(config: dict, source: Path, target: Path, force: bool) -> None:
    if source.resolve() == target.resolve():
        raise ValueError('write to a separate tuned configuration, keeping the original')
    text = json.dumps(config, indent=2) + '\n'
    if not force:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as output:
            output.write(text)
    else:
        with tempfile.NamedTemporaryFile(mode='w', dir=target.parent, delete=False) as output:
            temporary = Path(output.name)
            output.write(text)
        try:
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    create = commands.add_parser('apply', help='write a separate tuned configuration')
    create.add_argument('--config', type=Path, required=True)
    create.add_argument('--output', type=Path)
    create.add_argument('--force', action='store_true', help='replace an existing tuned output')
    create.add_argument('--repeatable', action='store_true',
                        help='disable adaptive swaps, PCIe sharing, prefix reuse and route-tail skipping for comparisons')
    launch = commands.add_parser('run', help='run a configuration inside the memory limit')
    launch.add_argument('--config', type=Path, required=True)
    launch.add_argument('--port', type=int, help='override the configured server port')
    launch.add_argument('--open', action='store_true', help='open the chat page when ready')
    benchmark = commands.add_parser('benchmark', help='run practical tasks against the running model')
    benchmark.add_argument('--url', default='http://127.0.0.1:8096')
    benchmark.add_argument('--output-dir', type=Path, required=True)
    benchmark.add_argument('--cases', default='snake,merge_intervals,lighthouse_svg')
    benchmark.add_argument('--repeats', type=int, default=1)
    benchmark.add_argument('--browser-checks', action='store_true')
    args = parser.parse_args()
    try:
        if args.action == 'benchmark':
            argv = [sys.executable, str(ROOT / 'tools/benchmark_practical.py'),
                    '--url', args.url, '--output-dir', str(args.output_dir.resolve()),
                    '--cases', args.cases, '--repeats', str(args.repeats)]
            if args.browser_checks:
                argv.append('--browser-checks')
            os.chdir(ROOT)
            os.execvp(argv[0], argv)
        config = json.loads(args.config.read_text(encoding='utf-8-sig'))
        if args.action == 'apply':
            if sys.platform != 'linux':
                raise ValueError('this profile is measured on Linux only')
            suffix = '-' + PROFILE + ('-repeatable' if args.repeatable else '') + '.json'
            target = args.output or args.config.with_name(args.config.stem + suffix)
            write(apply(config, args.repeatable), args.config, target, args.force)
            print(f'Tuned configuration: {target}')
            print(f'Run: .venv/bin/python tools/hardware_profile.py run --config {shlex.quote(str(target))}')
        else:
            if not shutil.which('systemd-run'):
                raise ValueError('systemd-run is required; no unbounded fallback is started')
            controllers = Path('/sys/fs/cgroup/cgroup.controllers')
            if not controllers.is_file() or 'memory' not in controllers.read_text().split():
                raise ValueError('the memory-limited launcher requires the cgroup v2 memory controller')
            if args.port is not None:
                config = {**config, 'port': args.port}
            argv = command(config, args.config)
            if args.open:
                argv.append('--open')
            os.chdir(ROOT)
            os.execvp(argv[0], argv)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
