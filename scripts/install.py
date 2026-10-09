#!/usr/bin/env python3
"""Install one environment and non-overwriting discovery links on this Mac."""
import argparse
import json
import shutil
import subprocess
import sys
import venv
from pathlib import Path

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--vault', type=Path, help='Optional Obsidian vault canonical skill registry')
a = p.parse_args()
root = Path(__file__).resolve().parents[1]
skill = root / 'skill'
home = Path.home()
for tool in ('ffmpeg', 'ffprobe'):
    if not shutil.which(tool):
        sys.exit('Missing ' + tool + '; install FFmpeg before running installer.')
entries = [home / '.codex/skills/video-hook', home / '.agents/skills/video-hook',
           home / '.claude/skills/video-hook', home / '.gemini/antigravity/skills/video-hook']
canonical = a.vault.expanduser().resolve() / '.claude/skills/video-hook' if a.vault else skill
if a.vault and not a.vault.is_dir():
    sys.exit('Vault must exist')
if canonical != skill:
    entries.insert(0, canonical)
# Preflight all existing entries before any mutation.
for entry in entries:
    if entry.exists() or entry.is_symlink():
        if entry.resolve() != skill:
            sys.exit('Refusing to replace existing entry: ' + str(entry))
if not (root / '.venv/bin/python').exists():
    venv.EnvBuilder(with_pip=False).create(root / '.venv')
for entry in entries:
    if entry.exists() or entry.is_symlink():
        continue
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.symlink_to(skill if entry == canonical else canonical, target_is_directory=True)
results = []
for entry in entries:
    result = subprocess.check_output([sys.executable, str(entry / 'scripts/run.py'), 'doctor'], text=True)
    results.append({'entry': str(entry), 'resolved': str(entry.resolve()), 'doctor': json.loads(result)})
print(json.dumps({'root': str(root), 'entries': results}, ensure_ascii=False, indent=2))
