#!/usr/bin/env python3
import json
import os
import tempfile
import threading
from pathlib import Path

ACCESS_FILE = Path(os.environ.get('ACCESS_CONTROL_FILE', '/home/access_data/access_control.json'))
_LOCK = threading.RLock()


def _normalize(values):
    return sorted({str(value).strip() for value in (values or []) if str(value).strip()})


def _defaults():
    import config
    return {
        'users': _normalize(config.whitelist or []),
        'groups': _normalize(config.GROUP_LIST or []),
    }


def _read_unlocked():
    defaults = _defaults()
    if not ACCESS_FILE.exists():
        return defaults
    try:
        data = json.loads(ACCESS_FILE.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return defaults
    return {
        'users': _normalize(list(data.get('users') or []) + defaults['users']),
        'groups': _normalize(list(data.get('groups') or []) + defaults['groups']),
    }


def _write_unlocked(data):
    ACCESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='access-control.', suffix='.tmp', dir=str(ACCESS_FILE.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, ACCESS_FILE)
        os.chmod(ACCESS_FILE, 0o600)
        directory_fd = os.open(str(ACCESS_FILE.parent), os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def ensure_initialized():
    with _LOCK:
        data = _read_unlocked()
        if not ACCESS_FILE.exists():
            _write_unlocked(data)
        return data


def snapshot():
    with _LOCK:
        return _read_unlocked()


def is_user_allowed(user_id):
    return str(user_id) in snapshot()['users']


def is_group_allowed(group_id):
    return str(group_id) in snapshot()['groups']


def allow(identifier):
    value = str(identifier).strip()
    kind = 'group' if value.startswith('-') else 'user'
    with _LOCK:
        data = _read_unlocked()
        key = 'groups' if kind == 'group' else 'users'
        if value in data[key]:
            return kind, False
        data[key].append(value)
        data[key] = _normalize(data[key])
        _write_unlocked(data)
        return kind, True


ensure_initialized()
