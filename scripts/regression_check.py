#!/usr/bin/env python3
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'app'
MEMORY_MODULE = APP / 'overrides'
PROMPT = ROOT / 'persona' / 'systemprompt.md'
MODULES = ROOT / 'persona' / 'modules'
CONFIGS = ROOT / 'data' / 'user_configs'
DB = ROOT / 'data' / 'memory' / 'gptbot_memory.sqlite3'

sys.path.insert(0, str(MEMORY_MODULE))
from memory_store import PersistentMemory

checks = []

def check(name, condition):
    if not condition:
        raise AssertionError(name)
    checks.append(name)

prompt_bytes = PROMPT.read_bytes()
built_bytes = b''.join(path.read_bytes() for path in sorted(MODULES.glob('*.md')))
check('persona_module_exact', built_bytes == prompt_bytes)
check('persona_viewpoint_rule', b'\xe5\x8f\x99\xe8\xbf\xb0\xe8\xa7\x86\xe8\xa7\x92\xe7\xba\xa6\xe6\x9d\x9f' in prompt_bytes)
check('persona_no_echo_rule', '避免机械复述主人的原话'.encode() in prompt_bytes)

for path in CONFIGS.glob('*.json'):
    data = json.loads(path.read_text(encoding='utf-8'))
    check(f'config_no_secret_duplicates:{path.name}', not ({'api_key', 'api_url'} & set(data)))
    if 'systemprompt' in data:
        check(f'config_systemprompt_is_custom:{path.name}', data['systemprompt'] != PROMPT.read_text(encoding='utf-8'))
    check(f'config_mode_600:{path.name}', (path.stat().st_mode & 0o777) == 0o600)

with sqlite3.connect(DB) as conn:
    check('sqlite_integrity', conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok')

fd, test_path = tempfile.mkstemp(prefix='gptbot-regression-', suffix='.sqlite3')
os.close(fd)
Path(test_path).unlink(missing_ok=True)
try:
    memory = PersistentMemory(test_path)
    memory.process_interaction('u1', 'c1', '舔耳，陪我', '好。')
    with sqlite3.connect(test_path) as conn:
        first_intimacy = conn.execute("SELECT intimacy FROM relationship_states WHERE user_id='u1'").fetchone()[0]
    memory.process_interaction('u1', 'c1', '舔耳，陪我', '好。')
    memory.process_interaction('u2', 'c2', '复杂问题请讲详细', '明白。')
    with sqlite3.connect(test_path) as conn:
        events = [row[0] for row in conn.execute("SELECT event_type FROM event_log WHERE user_id='u1'")]
        second_intimacy = conn.execute("SELECT intimacy FROM relationship_states WHERE user_id='u1'").fetchone()[0]
        conn.execute(
            "UPDATE user_profiles SET last_seen_utc='2026-01-01T00:00:00+00:00' WHERE user_id='u1'"
        )
        conn.execute(
            "UPDATE shizuku_states SET mood='欲望高涨', mood_intensity=90, desire=90 WHERE user_id='u1'"
        )
        conn.execute(
            "UPDATE event_log SET created_at='2026-01-01T00:00:00+00:00' WHERE user_id='u1' AND event_type='intimate_request'"
        )
        conn.commit()
    check('single_intimacy_event_with_cooldown', events.count('intimate_request') == 1)
    check('cooldown_blocks_duplicate_scoring', second_intimacy == first_intimacy)
    memory.process_interaction('u1', 'c1', '舔耳', '好。')
    with sqlite3.connect(test_path) as conn:
        refreshed_events = [row[0] for row in conn.execute("SELECT event_type FROM event_log WHERE user_id='u1'")]
        mood, intensity, desire = conn.execute(
            "SELECT mood, mood_intensity, desire FROM shizuku_states WHERE user_id='u1'"
        ).fetchone()
    check('event_cooldown_expires', refreshed_events.count('intimate_request') == 2)
    check('real_time_decay_applied', intensity < 90 and desire < 90)
    with sqlite3.connect(test_path) as conn:
        conn.execute(
            "UPDATE user_profiles SET last_seen_utc='2026-01-01T00:00:00+00:00' WHERE user_id='u1'"
        )
        conn.execute(
            "UPDATE shizuku_states SET mood='欲望高涨', mood_intensity=90, desire=90 WHERE user_id='u1'"
        )
        conn.commit()
    memory.add_turn('c1', '普通消息', '普通回复', user_id='u1', source_convo_id='c1')
    memory.process_interaction('u1', 'c1', '普通消息', '普通回复')
    with sqlite3.connect(test_path) as conn:
        production_order_intensity, production_order_desire = conn.execute(
            "SELECT mood_intensity, desire FROM shizuku_states WHERE user_id='u1'"
        ).fetchone()
    check('real_time_decay_with_production_call_order', production_order_intensity < 90 and production_order_desire < 90)
    memory.process_interaction('u3', 'c3', '这段代码为什么不对？', '分析如下。')
    with sqlite3.connect(test_path) as conn:
        correction_count = conn.execute(
            "SELECT COUNT(*) FROM event_log WHERE user_id='u3' AND event_type='correction'"
        ).fetchone()[0]
    check('technical_question_not_misclassified_as_correction', correction_count == 0)
    check('growth_context_user_isolation', '复杂技术问题要把关键步骤讲清楚' not in memory.build_user_context('u1'))
    check('growth_context_user_profile', '复杂技术问题要把关键步骤讲清楚' in memory.build_user_context('u2'))
finally:
    for suffix in ('', '-wal', '-shm'):
        Path(test_path + suffix).unlink(missing_ok=True)

print('PASS', len(checks))
for name in checks:
    print('-', name)
