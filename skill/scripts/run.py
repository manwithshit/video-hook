#!/usr/bin/env python3
"""Resolve every agent alias to the single repository environment."""
import os
import sys
from pathlib import Path
root = Path(__file__).resolve().parents[2]
if not (root / 'scripts/install.py').is_file() or not (root / 'skill/scripts/hook.py').is_file():
    sys.exit('Incomplete installation: the skill folder alone is not supported.\n'
             'Clone the full repository: gh repo clone manwithshit/video-hook\n'
             'Then run python3 scripts/install.py inside that repository.\n'
             'Repository: https://github.com/manwithshit/video-hook')
python = root / '.venv/bin/python'
if not python.exists():
    sys.exit('Shared runtime missing. Run: python3 "' + str(root / 'scripts/install.py') + '"')
os.execv(str(python), [str(python), str(root / 'skill/scripts/hook.py'), *sys.argv[1:]])
