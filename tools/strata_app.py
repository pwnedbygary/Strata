#!/usr/bin/env python3
"""Executable entry point for the router and its bundled single-model workers."""
import sys
from pathlib import Path
ROOT = Path(sys._MEIPASS) if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tools'))
if '--worker' in sys.argv:
    sys.argv.remove('--worker')
    from serve.server import main
else:
    from serve.router import main
if __name__ == '__main__':
    raise SystemExit(main())
