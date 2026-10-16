#!/usr/bin/env python3
"""Package the native C++ server. Build-time Python only; no Python in the AppImage."""
import argparse
from pathlib import Path
import os
import shutil
import subprocess
ROOT=Path(__file__).resolve().parents[1]
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--appimagetool',type=Path,required=True)
    p.add_argument('--runtime-file',type=Path,required=True,help='Already downloaded AppImage runtime; packaging does not fetch it')
    p.add_argument('--rocm-build-dir',type=Path,required=True,help='Dedicated ROCm build with bin/llama and shared libraries')
    p.add_argument('--vulkan-binary',type=Path,required=True,help='Locally tested Vulkan-only executable')
    p.add_argument('--binary',type=Path,default=ROOT/'build-hip/frontend/strata-native')
    p.add_argument('--output',type=Path,default=ROOT/'dist/Strata-Native-RX9070XT-x86_64.AppImage')
    a=p.parse_args()
    for file in (a.binary,a.appimagetool,a.runtime_file):
        if not file.is_file():p.error(f'Missing local file: {file}')
    appdir=ROOT/'dist/Strata-Native.AppDir'
    if appdir.exists():shutil.rmtree(appdir)
    bindir=appdir/'usr/bin';bindir.mkdir(parents=True)
    shutil.copy2(a.binary,bindir/'strata-native')
    if a.rocm_build_dir:
        rocm=a.rocm_build_dir.resolve()/'bin'
        if not (rocm/'llama').is_file():p.error('ROCm build needs bin/llama')
        shutil.copytree(rocm,bindir/'llama-rocm/bin',symlinks=True)
    if a.vulkan_binary:
        if not a.vulkan_binary.is_file():p.error('Missing Vulkan executable')
        shutil.copy2(a.vulkan_binary,bindir/'llama-vulkan')
    data=bindir/'data';data.mkdir();shutil.copy2(ROOT/'data/expert-profile.bin',data/'expert-profile.bin')
    tuning=bindir/'tools/hip';tuning.mkdir(parents=True)
    for file in (ROOT/'tools/hip').glob('*.txt'):shutil.copy2(file,tuning/file.name)
    licenses=appdir/'usr/share/licenses';licenses.mkdir(parents=True)
    for name,file in [('Strata',ROOT/'LICENSE'),('UnbiasedStrata',ROOT/'frontend/LICENSE'),('llama.cpp',ROOT/'third_party/llama.cpp/LICENSE')]:
        shutil.copy2(file,licenses/(name+'.txt'))
    vendor=ROOT/'third_party/llama.cpp/vendor'
    for file in vendor.rglob('LICENSE*'):
        if file.is_file():shutil.copy2(file,licenses/('vendor-'+str(file.relative_to(vendor)).replace('/','-')))
    mit=(ROOT/'third_party/llama.cpp/LICENSE').read_text();mit_body=mit[mit.index('Permission is hereby granted'):]
    (licenses/'nlohmann-json.txt').write_text('Copyright (c) 2013-2025 Niels Lohmann\n\n'+mit_body)
    stb=(vendor/'stb/stb_image.h').read_text()
    marker=stb.rfind('ALTERNATIVE A')
    if marker>=0:(licenses/'stb-image.txt').write_text(stb[marker:])
    for file in ('strata-router.desktop','strata-router.svg'):shutil.copy2(ROOT/'packaging'/file,appdir/file)
    desktop=appdir/'strata-router.desktop';desktop.write_text(desktop.read_text().replace('Exec=strata-router --open','Exec=strata-native --open'))
    (appdir/'AppRun').write_text('#!/bin/sh\nAPPDIR_PATH=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\nif [ "$#" -eq 0 ]; then set -- --open; fi\nexec "$APPDIR_PATH/usr/bin/strata-native" "$@"\n')
    (appdir/'AppRun').chmod(0o755)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    temporary=a.output.with_name(a.output.stem+'.new.AppImage')
    subprocess.run([str(a.appimagetool.resolve()),'--no-appstream','--runtime-file',str(a.runtime_file.resolve()),str(appdir),str(temporary)],check=True,env=dict(os.environ,ARCH='x86_64',APPIMAGE_EXTRACT_AND_RUN='1'))
    os.replace(temporary,a.output)
    print(f'Built {a.output} ({a.output.stat().st_size/2**20:.1f} MiB); native runtime, host ROCm required.')
if __name__=='__main__':main()
