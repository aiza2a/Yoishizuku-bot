import sys, tempfile
from datetime import tzinfo, timedelta
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'app' / 'overrides'))
sys.path.insert(0, '/var/minis/workspace/gptbot_p23/app/overrides')
import memory_store as ms
from memory_store import PersistentMemory

class FakeTZ(tzinfo):
    def utcoffset(self, dt):
        return timedelta(0)
    def dst(self, dt):
        return timedelta(0)
    def tzname(self, dt):
        return 'UTC'
    def fromutc(self, dt):
        return dt

ms.ZoneInfo = lambda _name: FakeTZ()

with tempfile.TemporaryDirectory() as tmp:
    db = tmp + '/m.sqlite3'
    m = PersistentMemory(db)
    mid, created = m.add_role_shared_memory('owner1', 'role1', '主人喜欢少糖。', 'c1')
    assert created is True
    mid2, created2 = m.add_role_shared_memory('owner1', 'role1', '主人喜欢少糖。', 'c2')
    assert mid2 == mid and created2 is False
    rows = m.list_role_shared_memories('owner1', 'role1')
    assert rows and rows[0]['content'] == '主人喜欢少糖。'
    ctx = m.build_role_shared_context('owner1', 'role1', query='少糖')
    assert '主人喜欢少糖' in ctx
    assert m.role_shared_count('owner1', 'role1') == 1
    assert m.delete_role_shared_memory('owner1', 'role1', mid) is True
    assert m.role_shared_count('owner1', 'role1') == 0
print('ROLE_SHARED_MEMORY_PASS')
