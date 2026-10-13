#!/usr/bin/env python3
"""Run a benchmark command, stopping its Strata scope if host RAM gets low."""
import argparse
import json
import subprocess
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope', default='strata-local.scope')
    parser.add_argument('--memory-floor-gib', type=float, default=1)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command or args.memory_floor_gib <= 0:
        parser.error('provide a command and a positive memory floor')
    rows = []
    aborted = False
    started = time.monotonic()
    process = subprocess.Popen(command)
    try:
        while process.poll() is None:
            info = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
            available = int(info['MemAvailable'].split()[0]) * 1024
            row = {'seconds': round(time.monotonic() - started, 2),
                   'available_gib': round(available / 2**30, 3)}
            for device in Path('/sys/class/drm').glob('card*/device'):
                try:
                    total = int((device / 'mem_info_vram_total').read_text())
                    used = int((device / 'mem_info_vram_used').read_text())
                    if total > 2**30:
                        row['vram_free_mib'] = round((total - used) / 2**20)
                except (OSError, ValueError):
                    pass
            rows.append(row)
            if available < args.memory_floor_gib * 2**30:
                aborted = True
                print('Benchmark stopped: available RAM fell below the test floor.', flush=True)
                subprocess.run(['systemctl', '--user', 'stop', args.scope], check=False)
                process.terminate()
                break
            time.sleep(0.5)
        code = process.wait()
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({'aborted': aborted, 'samples': rows}, indent=2) + '\n')
    return 2 if aborted else code


if __name__ == '__main__':
    raise SystemExit(main())
