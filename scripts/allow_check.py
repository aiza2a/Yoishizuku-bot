#!/usr/bin/env python3
import json
import os
import sys
import tempfile
from pathlib import Path

root = Path(tempfile.mkdtemp(prefix='gptbot-access-', dir='/tmp'))
os.environ['ACCESS_CONTROL_FILE'] = str(root / 'access_control.json')
sys.path.insert(0, '/home')

import config
config.whitelist = ['10001']
config.GROUP_LIST = ['-10001']
import access_control

try:
    initial = access_control.ensure_initialized()
    assert initial['users'] == ['10001']
    assert initial['groups'] == ['-10001']
    assert access_control.is_user_allowed('10001')
    assert access_control.is_group_allowed('-10001')

    kind, added = access_control.allow('6359487083')
    assert (kind, added) == ('user', True)
    assert access_control.is_user_allowed('6359487083')
    assert access_control.allow('6359487083') == ('user', False)

    kind, added = access_control.allow('-1006359487083')
    assert (kind, added) == ('group', True)
    assert access_control.is_group_allowed('-1006359487083')
    assert access_control.allow('-1006359487083') == ('group', False)

    saved = json.loads((root / 'access_control.json').read_text(encoding='utf-8'))
    assert '6359487083' in saved['users']
    assert '-1006359487083' in saved['groups']
    assert ((root / 'access_control.json').stat().st_mode & 0o777) == 0o600
    print('allow_user_persistence_ok')
    print('allow_group_members_ok')
    print('allow_duplicate_idempotent_ok')
finally:
    for path in root.glob('*'):
        path.unlink(missing_ok=True)
    root.rmdir()
