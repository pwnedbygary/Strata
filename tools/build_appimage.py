#!/usr/bin/env python3
"""Build the Linux router executable and an AppImage with host-provided ROCm."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--appimagetool', type=Path, required=True, help='local official appimagetool executable')
    p.add_argument('--dense-engine', type=Path, default=ROOT/'build-hip/strata')
    p.add_argument('--flash-engine', type=Path, default=ROOT/'engine/strata')
    p.add_argument('--vision-engine', type=Path, help='optional CPU strata-vision encoder for screenshot profiles')
    a = p.parse_args()
    for file in (a.appimagetool, a.dense_engine, a.flash_engine):
        if not file.is_file():
            p.error(f'Missing {file}')
    if a.vision_engine and not a.vision_engine.is_file():
        p.error(f'Missing {a.vision_engine}')
    output = ROOT/'dist'
    build = ROOT/'build-appimage'
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
               '--name', 'strata-router', '--distpath', str(output), '--workpath', str(build/'pyinstaller'),
               '--specpath', str(build), '--paths', str(ROOT), '--paths', str(ROOT/'tools'),
               '--collect-submodules', 'serve', '--hidden-import', 'strata_tokenizer',
               '--hidden-import', 'gguf_reader', '--hidden-import', 'regex',
               '--copy-metadata', 'Jinja2', '--copy-metadata', 'MarkupSafe',
               '--copy-metadata', 'regex', '--copy-metadata', 'psutil',
               '--copy-metadata', 'Pillow',
               '--add-data', f'{ROOT}/serve/web:serve/web',
               '--add-data', f'{ROOT}/tools/hip:tools/hip',
               '--add-data', f'{ROOT}/data/expert-profile.bin:data',
               '--add-data', f'{ROOT}/serve/chat_template.jinja:serve',
               '--add-data', f'{ROOT}/LICENSE:licenses', str(ROOT/'tools/strata_app.py')]
    subprocess.run(command, check=True, cwd=ROOT)
    appdir = output/'Strata.AppDir'
    if appdir.exists():
        shutil.rmtree(appdir)
    shutil.copytree(output/'strata-router', appdir/'usr/bin')
    engines = appdir/'usr/bin/_internal/engines'
    engines.mkdir(parents=True)
    shutil.copy2(a.dense_engine, engines/'dense-hip')
    shutil.copy2(a.flash_engine, engines/'flash-hip')
    if a.vision_engine:
        shutil.copy2(a.vision_engine, engines/'vision-cpu')
        license_dir = appdir/'usr/bin/_internal/licenses/llama.cpp'
        license_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT/'third_party/llama.cpp/LICENSE', license_dir/'LICENSE')
        standalone_license = output/'strata-router/_internal/licenses/llama.cpp'
        shutil.copytree(license_dir, standalone_license, dirs_exist_ok=True)
    # Keep the standalone executable directory equally useful.
    shutil.copytree(engines, output/'strata-router/_internal/engines', dirs_exist_ok=True)
    python_license = Path(sysconfig.get_path('stdlib')) / 'LICENSE.txt'
    if python_license.is_file():
        for runtime in (appdir/'usr/bin/_internal', output/'strata-router/_internal'):
            directory = runtime/'licenses/python'
            directory.mkdir(parents=True, exist_ok=True)
            shutil.copy2(python_license, directory/'LICENSE.txt')
    for file in ('AppRun', 'strata-router.desktop', 'strata-router.svg'):
        shutil.copy2(ROOT/'packaging'/file, appdir/file)
    (appdir/'AppRun').chmod(0o755)
    image = output/'Strata-RX9070XT-x86_64.AppImage'
    env = dict(os.environ, ARCH='x86_64', APPIMAGE_EXTRACT_AND_RUN='1')
    temporary_image = image.with_name(image.stem + '.new.AppImage')
    temporary_image.unlink(missing_ok=True)
    subprocess.run([str(a.appimagetool.resolve()), '--no-appstream', str(appdir), str(temporary_image)],
                   check=True, env=env)
    os.replace(temporary_image, image)
    print(f'Built {image} ({image.stat().st_size / 2**20:.1f} MiB)')
    print('Models/tokenizers stay external; compatible system ROCm and Linux drivers are required.')


if __name__ == '__main__':
    main()
