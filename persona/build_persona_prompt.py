#!/usr/bin/env python3
from pathlib import Path
BASE = Path(__file__).resolve().parent
MODULES = BASE / 'modules'
OUT = BASE / 'systemprompt.md'
parts = [p.read_bytes() for p in sorted(MODULES.glob('*.md'))]
content = b''.join(parts)
OUT.write_bytes(content)
print('built', OUT, len(content), 'bytes')
