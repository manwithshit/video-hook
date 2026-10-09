#!/usr/bin/env python3
"""Resolve every agent alias to the single repository environment."""
import os
import sys
from pathlib import Path
root = Path(__file__).resolve().parents[2]
python = root / '.venv/bin/python'
if not python.exists():
    sys.exit('Shared runtime missing. Run: python3 "' + str(root / 'scripts/install.py') + '"')
os.execv(str(python), [str(python), str(root / 'skill/scripts/hook.py'), *sys.argv[1:]])
