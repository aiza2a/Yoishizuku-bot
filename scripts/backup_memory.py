#!/usr/bin/env python3
import sqlite3
import sys
from pathlib import Path

if len(sys.argv) != 2:
    raise SystemExit('usage: backup_memory.py OUTPUT.sqlite3')
source = Path('/root/data/docker_data/gptbot/data/memory/gptbot_memory.sqlite3')
target = Path(sys.argv[1]).expanduser().resolve()
target.parent.mkdir(parents=True, exist_ok=True)
with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
    src.backup(dst)
    result = dst.execute('PRAGMA integrity_check').fetchone()[0]
if result != 'ok':
    target.unlink(missing_ok=True)
    raise SystemExit(f'backup integrity failed: {result}')
target.chmod(0o600)
print(target)
