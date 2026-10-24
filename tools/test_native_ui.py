#!/usr/bin/env python3
"""Check the exact JavaScript embedded in the native UI, without a running server."""
from pathlib import Path
import subprocess
root = Path(__file__).resolve().parents[1]
source = (root / 'frontend/ui.hpp').read_text().split('<script>', 1)[1].split('</script>', 1)[0]
subprocess.run(['node', '--check'], input=source, text=True, check=True)
print('PASS: embedded native UI JavaScript syntax')
