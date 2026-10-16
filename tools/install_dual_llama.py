#!/usr/bin/env python3
"""Install an already built dual-backend llama locally, preserving a rollback binary and presets."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import shlex


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build-dir',type=Path,required=True)
    p.add_argument('--prefix',type=Path,required=True)
    p.add_argument('--executable',type=Path,default=Path.home()/'.local/bin/llama')
    p.add_argument('--presets',type=Path,required=True)
    a=p.parse_args()
    source=a.build_dir.resolve()/'bin'
    if not (source/'llama').is_file():p.error('Build directory has no bin/llama')
    before=digest(a.presets)
    backup=a.executable.with_name(a.executable.name+'.vulkan-backup')
    if a.executable.exists() and not backup.exists():shutil.copy2(a.executable,backup)
    target=a.prefix.resolve()/'bin'
    if target.exists():p.error('Choose a new install prefix; existing installations are preserved')
    shutil.copytree(source,target,symlinks=True)
    script='''#!/bin/sh
# Local dual-backend build. Explicit --device overrides this default.
export LD_LIBRARY_PATH=%s${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
case "${1-}" in serve|cli) export LLAMA_ARG_DEVICE="${LLAMA_ARG_DEVICE:-Vulkan0}" ;; esac
exec %s "$@"
'''%(shlex.quote(str(target)),shlex.quote(str(target/'llama')))
    temporary=a.executable.with_name(a.executable.name+'.new')
    temporary.write_text(script);temporary.chmod(0o755)
    if digest(a.presets)!=before:temporary.unlink();raise SystemExit('Presets changed during installation; executable not replaced')
    os.replace(temporary,a.executable)
    print(f'Installed {a.executable}')
    if backup.exists(): print(f'Rollback executable: {backup}')
    else: print('Additional command installed; no existing executable was replaced.')
    print(f'Presets untouched: SHA-256 {before}')
    print(f'Use {a.executable.name} serve --device Vulkan0 or --device ROCm0; default remains Vulkan.')


if __name__=='__main__':main()
