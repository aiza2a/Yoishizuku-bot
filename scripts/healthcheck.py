#!/usr/bin/env python3
import os
import sqlite3
import sys
from pathlib import Path

DB = Path(os.environ.get('MEMORY_DB_PATH', '/home/memory_data/gptbot_memory.sqlite3'))
try:
    with sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=2) as conn:
        result = conn.execute('PRAGMA quick_check').fetchone()[0]
    if result != 'ok':
        print(result)
        raise SystemExit(1)
    print('ok')
except Exception as exc:
    print(f'unhealthy: {exc}')
    raise SystemExit(1)
