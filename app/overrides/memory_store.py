#!/usr/bin/env python3
"""Persistent memory + character growth state for GPTBOT.

Design goals:
- one SQLite db
- user-level long-term memory separated by user_id
- optional session/convo-level turn history via memory keys
- real-world timestamps in UTC + local timezone
- lightweight rule-based growth so character can evolve without extra services
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo


class PersistentMemory:
    def __init__(
        self,
        db_path: str,
        recent_turns: int = 8,
        max_context_chars: int = 7000,
        local_tz: str = "Asia/Shanghai",
    ):
        self.db_path = str(db_path)
        self.recent_turns = max(2, int(recent_turns))
        self.max_context_chars = max(2000, int(max_context_chars))
        self.local_tz = local_tz
        self._tz = ZoneInfo(local_tz)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=20)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=20000")
        return conn

    def _init_db(self):
        with self._lock, self._connect() as conn:
            # Create core tables first without secondary indexes that may depend on later migrations.
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    convo_id TEXT PRIMARY KEY,
                    summary TEXT NOT NULL DEFAULT '',
                    last_summarized_turn_id INTEGER NOT NULL DEFAULT 0,
                    reset_after_turn_id INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    convo_id TEXT NOT NULL,
                    user_text TEXT NOT NULL,
                    assistant_text TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id TEXT PRIMARY KEY,
                    stable_preferences TEXT NOT NULL DEFAULT '',
                    response_style TEXT NOT NULL DEFAULT '',
                    intimacy_preferences TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_seen_utc TEXT NOT NULL,
                    last_seen_local TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS relationship_states (
                    user_id TEXT PRIMARY KEY,
                    intimacy REAL NOT NULL DEFAULT 20,
                    trust REAL NOT NULL DEFAULT 50,
                    dependency REAL NOT NULL DEFAULT 20,
                    possessiveness REAL NOT NULL DEFAULT 10,
                    safety REAL NOT NULL DEFAULT 70,
                    stage TEXT NOT NULL DEFAULT '初熟',
                    note TEXT NOT NULL DEFAULT '',
                    last_conflict_utc TEXT NOT NULL DEFAULT '',
                    last_tender_utc TEXT NOT NULL DEFAULT '',
                    last_intimate_utc TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS shizuku_states (
                    user_id TEXT PRIMARY KEY,
                    mood TEXT NOT NULL DEFAULT '平静',
                    mood_intensity REAL NOT NULL DEFAULT 20,
                    clinginess REAL NOT NULL DEFAULT 25,
                    initiative REAL NOT NULL DEFAULT 20,
                    fatigue REAL NOT NULL DEFAULT 15,
                    shyness REAL NOT NULL DEFAULT 60,
                    desire REAL NOT NULL DEFAULT 15,
                    state_note TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS event_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    convo_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    created_local TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS role_shared_memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_key TEXT NOT NULL,
                    role_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source_convo_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    created_local TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

            # Migrate old turns table columns before creating indexes that depend on them.
            cols = {row[1] for row in conn.execute("PRAGMA table_info(turns)").fetchall()}
            if "user_id" not in cols:
                conn.execute("ALTER TABLE turns ADD COLUMN user_id TEXT NOT NULL DEFAULT ''")
            if "source_convo_id" not in cols:
                conn.execute("ALTER TABLE turns ADD COLUMN source_convo_id TEXT NOT NULL DEFAULT ''")
            if "created_local" not in cols:
                conn.execute("ALTER TABLE turns ADD COLUMN created_local TEXT NOT NULL DEFAULT ''")
                conn.execute(
                    "UPDATE turns SET created_local = created_at WHERE created_local = '' OR created_local IS NULL"
                )

            # Create indexes after migration.
            conn.executescript(
                """
                CREATE INDEX IF NOT EXISTS idx_turns_convo_id_id ON turns(convo_id, id);
                CREATE INDEX IF NOT EXISTS idx_turns_user_id_id ON turns(user_id, id);
                CREATE INDEX IF NOT EXISTS idx_event_user_id_id ON event_log(user_id, id);
                CREATE INDEX IF NOT EXISTS idx_role_shared_owner_role_id ON role_shared_memories(owner_key, role_id, id);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_role_shared_unique ON role_shared_memories(owner_key, role_id, content);
                """
            )

    @staticmethod
    def _clean(text, limit=20000):
        text = str(text or "").strip()
        text = re.sub(r"\n{4,}", "\n\n\n", text)
        return text[:limit]

    def _now_utc(self):
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _now_local(self):
        return datetime.now(self._tz).strftime("%Y-%m-%d %H:%M:%S")

    def _conversation_row(self, conn, convo_id):
        row = conn.execute("SELECT * FROM conversations WHERE convo_id=?", (str(convo_id),)).fetchone()
        if row:
            return row
        now = self._now_utc()
        conn.execute(
            "INSERT INTO conversations(convo_id, updated_at) VALUES(?, ?)",
            (str(convo_id), now),
        )
        return conn.execute("SELECT * FROM conversations WHERE convo_id=?", (str(convo_id),)).fetchone()

    def _ensure_user_rows(self, conn, user_id: str):
        if not user_id:
            return
        now_utc = self._now_utc()
        now_local = self._now_local()
        conn.execute(
            """INSERT OR IGNORE INTO user_profiles(
                user_id, created_at, updated_at, last_seen_utc, last_seen_local
            ) VALUES(?, ?, ?, ?, ?)""",
            (user_id, now_utc, now_utc, now_utc, now_local),
        )
        conn.execute(
            "INSERT OR IGNORE INTO relationship_states(user_id, updated_at) VALUES(?, ?)",
            (user_id, now_utc),
        )
        conn.execute(
            "INSERT OR IGNORE INTO shizuku_states(user_id, updated_at) VALUES(?, ?)",
            (user_id, now_utc),
        )

    @staticmethod
    def _ngrams(text: str):
        compact = re.sub(r"\s+", "", str(text or "").lower())
        chars = {compact[i : i + 2] for i in range(max(0, len(compact) - 1))}
        words = set(re.findall(r"[a-z0-9_\-]{2,}|[\u4e00-\u9fff]{2,}", str(text or "").lower()))
        return chars | words

    @staticmethod
    def _clamp(value, low=0.0, high=100.0):
        return max(low, min(high, float(value)))

    @staticmethod
    def _merge_bullets(existing: str, bullet: str, limit: int = 8) -> str:
        bullet = str(bullet or "").strip().rstrip("。") + "。"
        if not bullet:
            return existing or ""
        lines = [x.strip() for x in str(existing or "").splitlines() if x.strip()]
        if bullet in lines:
            return "\n".join(lines)
        lines.append(bullet)
        if len(lines) > limit:
            lines = lines[-limit:]
        return "\n".join(lines)

    @staticmethod
    def _replace_or_merge(existing: str, bullet: str, prefix_tokens: tuple[str, ...], limit: int = 8) -> str:
        bullet = str(bullet or "").strip().rstrip("。") + "。"
        lines = [x.strip() for x in str(existing or "").splitlines() if x.strip()]
        replaced = False
        for i, line in enumerate(lines):
            if any(token in line for token in prefix_tokens):
                lines[i] = bullet
                replaced = True
                break
        if not replaced and bullet not in lines:
            lines.append(bullet)
        if len(lines) > limit:
            lines = lines[-limit:]
        return "\n".join(lines)

    def latest_turn_id(self, convo_id: str) -> int:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(id), 0) AS max_id FROM turns WHERE convo_id=?",
                (str(convo_id),),
            ).fetchone()
        return int(row["max_id"] or 0)

    def get_summary(self, convo_id: str) -> str:
        with self._lock, self._connect() as conn:
            row = self._conversation_row(conn, convo_id)
            return str(row["summary"] or "")

    def add_turn(
        self,
        convo_id: str,
        user_text: str,
        assistant_text: str,
        user_id: str = "",
        source_convo_id: str = "",
    ) -> Optional[int]:
        user_text = self._clean(user_text)
        assistant_text = self._clean(assistant_text)
        if not convo_id or not user_text or not assistant_text:
            return None
        now = self._now_utc()
        now_local = self._now_local()
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO conversations(convo_id, updated_at) VALUES(?, ?)",
                (str(convo_id), now),
            )
            if user_id:
                # Ensure profile rows exist, but keep last_seen unchanged until
                # process_interaction applies real-time decay and commits the new timestamp.
                self._ensure_user_rows(conn, str(user_id))
            cur = conn.execute(
                """INSERT INTO turns(convo_id, user_id, source_convo_id, user_text, assistant_text, created_at, created_local)
                   VALUES(?, ?, ?, ?, ?, ?, ?)""",
                (str(convo_id), str(user_id or ""), str(source_convo_id or ""), user_text, assistant_text, now, now_local),
            )
            conn.execute("UPDATE conversations SET updated_at=? WHERE convo_id=?", (now, str(convo_id)))
            return int(cur.lastrowid)

    def mark_reset(self, convo_id: str):
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(id), 0) AS max_id FROM turns WHERE convo_id=?",
                (str(convo_id),),
            ).fetchone()
            max_id = int(row["max_id"] or 0)
            conn.execute(
                """INSERT INTO conversations(convo_id, reset_after_turn_id, updated_at)
                   VALUES(?, ?, ?)
                   ON CONFLICT(convo_id) DO UPDATE SET
                     reset_after_turn_id=excluded.reset_after_turn_id,
                     updated_at=excluded.updated_at""",
                (str(convo_id), max_id, self._now_utc()),
            )

    def clear_all(self, convo_id: str):
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM turns WHERE convo_id=?", (str(convo_id),))
            conn.execute("DELETE FROM conversations WHERE convo_id=?", (str(convo_id),))

    def forget_runtime(self, convo_id: str):
        """Delete one role dialogue and its role-scoped growth records."""
        convo_id = str(convo_id)
        role_user_pattern = "role:" + convo_id + ":user:%"
        with self._lock, self._connect() as conn:
            user_rows = conn.execute(
                """SELECT DISTINCT user_id FROM turns
                   WHERE convo_id=? OR user_id LIKE ?""",
                (convo_id, role_user_pattern),
            ).fetchall()
            event_rows = conn.execute(
                """SELECT DISTINCT user_id FROM event_log
                   WHERE convo_id=? OR user_id LIKE ?""",
                (convo_id, role_user_pattern),
            ).fetchall()
            user_ids = {str(row[0]) for row in user_rows + event_rows if row[0]}
            conn.execute(
                "DELETE FROM turns WHERE convo_id=? OR user_id LIKE ?",
                (convo_id, role_user_pattern),
            )
            conn.execute(
                "DELETE FROM event_log WHERE convo_id=? OR user_id LIKE ?",
                (convo_id, role_user_pattern),
            )
            conn.execute("DELETE FROM conversations WHERE convo_id=?", (convo_id,))
            for user_id in user_ids:
                conn.execute("DELETE FROM user_profiles WHERE user_id=?", (user_id,))
                conn.execute("DELETE FROM relationship_states WHERE user_id=?", (user_id,))
                conn.execute("DELETE FROM shizuku_states WHERE user_id=?", (user_id,))

    def add_role_shared_memory(self, owner_key: str, role_id: str, content: str, source_convo_id: str = ""):
        owner_key = str(owner_key or "").strip()
        role_id = str(role_id or "").strip()
        content = self._clean(content, 1200)
        if not owner_key or not role_id or not content:
            raise ValueError("empty_memory")
        now_utc = self._now_utc()
        now_local = self._now_local()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM role_shared_memories WHERE owner_key=? AND role_id=? AND content=?",
                (owner_key, role_id, content),
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE role_shared_memories SET updated_at=?, source_convo_id=? WHERE id=?",
                    (now_utc, str(source_convo_id or ""), int(row["id"])),
                )
                return int(row["id"]), False
            cur = conn.execute(
                """INSERT INTO role_shared_memories(owner_key, role_id, content, source_convo_id, created_at, created_local, updated_at)
                   VALUES(?, ?, ?, ?, ?, ?, ?)""",
                (owner_key, role_id, content, str(source_convo_id or ""), now_utc, now_local, now_utc),
            )
            return int(cur.lastrowid), True

    def list_role_shared_memories(self, owner_key: str, role_id: str, limit: int = 20):
        owner_key = str(owner_key or "").strip()
        role_id = str(role_id or "").strip()
        if not owner_key or not role_id:
            return []
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """SELECT id, content, source_convo_id, created_at, created_local, updated_at
                   FROM role_shared_memories
                   WHERE owner_key=? AND role_id=?
                   ORDER BY updated_at DESC, id DESC LIMIT ?""",
                (owner_key, role_id, int(limit)),
            ).fetchall()
        return [dict(row) for row in rows]

    def role_shared_count(self, owner_key: str, role_id: str) -> int:
        owner_key = str(owner_key or "").strip()
        role_id = str(role_id or "").strip()
        if not owner_key or not role_id:
            return 0
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM role_shared_memories WHERE owner_key=? AND role_id=?",
                (owner_key, role_id),
            ).fetchone()
        return int(row["n"] or 0)

    def delete_role_shared_memory(self, owner_key: str, role_id: str, memory_id: int) -> bool:
        owner_key = str(owner_key or "").strip()
        role_id = str(role_id or "").strip()
        if not owner_key or not role_id:
            return False
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM role_shared_memories WHERE owner_key=? AND role_id=? AND id=?",
                (owner_key, role_id, int(memory_id)),
            )
        return bool(cur.rowcount)

    def forget_role_shared(self, owner_key: str, role_id: str):
        owner_key = str(owner_key or "").strip()
        role_id = str(role_id or "").strip()
        if not owner_key or not role_id:
            return
        with self._lock, self._connect() as conn:
            conn.execute(
                "DELETE FROM role_shared_memories WHERE owner_key=? AND role_id=?",
                (owner_key, role_id),
            )

    def build_role_shared_context(self, owner_key: str, role_id: str, query: str = "", limit: int = 6, max_chars: int = 1800) -> str:
        owner_key = str(owner_key or "").strip()
        role_id = str(role_id or "").strip()
        if not owner_key or not role_id:
            return ""
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """SELECT id, content, updated_at FROM role_shared_memories
                   WHERE owner_key=? AND role_id=?
                   ORDER BY updated_at DESC, id DESC LIMIT 40""",
                (owner_key, role_id),
            ).fetchall()
        if not rows:
            return ""
        qset = self._ngrams(query)
        selected = []
        if qset:
            scored = []
            for row in rows:
                tset = self._ngrams(row["content"])
                score = len(qset & tset)
                if score:
                    scored.append((score, int(row["id"]), row))
            scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
            selected = [item[2] for item in scored[: int(limit)]]
        if not selected:
            selected = list(rows[: int(limit)])
        lines = ["【当前角色在所有对话中共享的记忆】"]
        for row in selected:
            lines.append("- " + self._clean(row["content"], 260))
        context = "\n".join(lines)
        if len(context) > max_chars:
            context = context[:max_chars]
        return "以下内容是当前角色在所有对话中共享的长期记忆。自然利用，不要逐条复述，也不要让它覆盖用户当前明确表达。\n" + context

    def build_context(
        self,
        convo_id: str,
        query: str = "",
        include_recent: bool = True,
        include_summary: bool = True,
        max_turn_id: Optional[int] = None,
        summary_override: Optional[str] = None,
    ) -> str:
        with self._lock, self._connect() as conn:
            conv = self._conversation_row(conn, convo_id)
            summary = str(summary_override) if summary_override is not None else (conv["summary"] or "").strip()
            if not include_summary:
                summary = ""
            reset_after = int(conv["reset_after_turn_id"] or 0)
            upper = int(max_turn_id) if max_turn_id is not None else 9223372036854775807
            summary_lower_bound = max(reset_after, int(conv["last_summarized_turn_id"] or 0))

            recent = []
            if include_recent:
                recent = conn.execute(
                    """SELECT id, user_text, assistant_text, created_local FROM turns
                       WHERE convo_id=? AND id>? AND id<=? ORDER BY id DESC LIMIT ?""",
                    (str(convo_id), summary_lower_bound, upper, self.recent_turns),
                ).fetchall()
                recent = list(reversed(recent))

            recent_ids = {int(r["id"]) for r in recent}
            candidates = conn.execute(
                """SELECT id, user_text, assistant_text, created_local FROM turns
                   WHERE convo_id=? AND id>? AND id<=? ORDER BY id DESC LIMIT 160""",
                (str(convo_id), summary_lower_bound, upper),
            ).fetchall()

        relevant = []
        qset = self._ngrams(query)
        if qset:
            scored = []
            for row in candidates:
                if int(row["id"]) in recent_ids:
                    continue
                tset = self._ngrams(row["user_text"] + " " + row["assistant_text"])
                score = len(qset & tset)
                if score:
                    scored.append((score, int(row["id"]), row))
            scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
            relevant = [x[2] for x in scored[:3]]
            relevant.reverse()

        sections = []
        if summary:
            sections.append("【长期关系与稳定记忆】\n" + summary[:3000])
        if relevant:
            lines = ["【与当前话题相关的旧记忆】"]
            for row in relevant:
                lines.append("主人：" + self._clean(row["user_text"], 500))
                lines.append("宵雫：" + self._clean(row["assistant_text"], 700))
            sections.append("\n".join(lines))
        if recent:
            lines = ["【容器重启后恢复的近期对话】"]
            for row in recent:
                lines.append("主人：" + self._clean(row["user_text"], 600))
                lines.append("宵雫：" + self._clean(row["assistant_text"], 900))
            sections.append("\n".join(lines))

        context = "\n\n".join(sections).strip()
        if not context:
            return ""
        if len(context) > self.max_context_chars:
            context = context[: self.max_context_chars]
        return "以下内容来自持久记忆。自然利用，不要说‘根据记忆’、不要逐项复述，也不要让记忆覆盖主人当前明确表达。\n" + context

    def needs_summary(self, convo_id: str, min_turns: int = 8, min_chars: int = 6000) -> bool:
        with self._lock, self._connect() as conn:
            conv = self._conversation_row(conn, convo_id)
            last_id = max(int(conv["last_summarized_turn_id"] or 0), int(conv["reset_after_turn_id"] or 0))
            rows = conn.execute(
                "SELECT user_text, assistant_text FROM turns WHERE convo_id=? AND id>?",
                (str(convo_id), last_id),
            ).fetchall()
        chars = sum(len(r["user_text"]) + len(r["assistant_text"]) for r in rows)
        return len(rows) >= int(min_turns) or chars >= int(min_chars)

    def summary_material(self, convo_id: str, max_chars: int = 12000):
        with self._lock, self._connect() as conn:
            conv = self._conversation_row(conn, convo_id)
            last_id = max(int(conv["last_summarized_turn_id"] or 0), int(conv["reset_after_turn_id"] or 0))
            rows = conn.execute(
                "SELECT id, user_text, assistant_text FROM turns WHERE convo_id=? AND id>? ORDER BY id ASC LIMIT 30",
                (str(convo_id), last_id),
            ).fetchall()
            old_summary = (conv["summary"] or "").strip()
        parts = []
        last_turn_id = last_id
        for row in rows:
            chunk = "主人：" + row["user_text"] + "\n宵雫：" + row["assistant_text"]
            if len("\n\n".join(parts + [chunk])) > max_chars:
                break
            parts.append(chunk)
            last_turn_id = int(row["id"])
        return old_summary, "\n\n".join(parts), last_turn_id

    def update_summary(self, convo_id: str, summary: str, last_turn_id: int):
        summary = self._clean(summary, 5000)
        if not summary or not last_turn_id:
            return
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO conversations(convo_id, summary, last_summarized_turn_id, updated_at)
                   VALUES(?, ?, ?, ?)
                   ON CONFLICT(convo_id) DO UPDATE SET
                     summary=excluded.summary,
                     last_summarized_turn_id=MAX(conversations.last_summarized_turn_id, excluded.last_summarized_turn_id),
                     updated_at=excluded.updated_at""",
                (str(convo_id), summary, int(last_turn_id), self._now_utc()),
            )

    def stats(self, convo_id: str):
        with self._lock, self._connect() as conn:
            conv = self._conversation_row(conn, convo_id)
            count = conn.execute("SELECT COUNT(*) AS n FROM turns WHERE convo_id=?", (str(convo_id),)).fetchone()["n"]
        return {
            "turns": int(count),
            "summary_chars": len(conv["summary"] or ""),
            "last_summarized_turn_id": int(conv["last_summarized_turn_id"] or 0),
            "reset_after_turn_id": int(conv["reset_after_turn_id"] or 0),
        }

    def user_stats(self, user_id: str):
        if not user_id:
            return {}
        with self._lock, self._connect() as conn:
            self._ensure_user_rows(conn, str(user_id))
            profile = conn.execute("SELECT * FROM user_profiles WHERE user_id=?", (str(user_id),)).fetchone()
            relation = conn.execute("SELECT * FROM relationship_states WHERE user_id=?", (str(user_id),)).fetchone()
            state = conn.execute("SELECT * FROM shizuku_states WHERE user_id=?", (str(user_id),)).fetchone()
            turns = conn.execute("SELECT COUNT(*) FROM turns WHERE user_id=?", (str(user_id),)).fetchone()[0]
            events = conn.execute("SELECT COUNT(*) FROM event_log WHERE user_id=?", (str(user_id),)).fetchone()[0]
        return {
            "turns": int(turns),
            "events": int(events),
            "profile": dict(profile) if profile else {},
            "relationship": dict(relation) if relation else {},
            "state": dict(state) if state else {},
        }

    def forget_user(self, user_id: str, convo_id: str = ""):
        if not user_id:
            return
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM turns WHERE user_id=?", (str(user_id),))
            conn.execute("DELETE FROM event_log WHERE user_id=?", (str(user_id),))
            conn.execute("DELETE FROM user_profiles WHERE user_id=?", (str(user_id),))
            conn.execute("DELETE FROM relationship_states WHERE user_id=?", (str(user_id),))
            conn.execute("DELETE FROM shizuku_states WHERE user_id=?", (str(user_id),))
            if convo_id:
                conn.execute("DELETE FROM turns WHERE convo_id=?", (str(convo_id),))
                conn.execute("DELETE FROM event_log WHERE convo_id=?", (str(convo_id),))
                conn.execute("DELETE FROM conversations WHERE convo_id=?", (str(convo_id),))

    # -------- growth memory --------
    def _stage_from_values(self, intimacy: float, trust: float) -> str:
        if intimacy < 25 or trust < 40:
            return "初熟"
        if intimacy < 45:
            return "依赖萌发"
        if intimacy < 65:
            return "亲密同居"
        if intimacy < 82:
            return "强依恋"
        return "独占期"

    def _event_payload_json(self, payload: dict) -> str:
        try:
            return json.dumps(payload, ensure_ascii=False)
        except Exception:
            return "{}"

    def _log_event(self, conn, user_id: str, convo_id: str, event_type: str, summary: str, payload: Optional[dict] = None):
        if not user_id or not event_type or not summary:
            return
        conn.execute(
            """INSERT INTO event_log(user_id, convo_id, event_type, summary, payload_json, created_at, created_local)
               VALUES(?, ?, ?, ?, ?, ?, ?)""",
            (
                str(user_id),
                str(convo_id or ""),
                str(event_type),
                self._clean(summary, 500),
                self._event_payload_json(payload or {}),
                self._now_utc(),
                self._now_local(),
            ),
        )

    def _update_profile_from_text(self, conn, user_id: str, user_text: str):
        row = conn.execute("SELECT * FROM user_profiles WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            return
        stable = row["stable_preferences"] or ""
        resp = row["response_style"] or ""
        intimacy_pref = row["intimacy_preferences"] or ""
        notes = row["notes"] or ""
        t = str(user_text or "")

        if re.search(r"少糖|不喜欢太甜|别太甜|咖啡.*不甜", t):
            stable = self._replace_or_merge(stable, "饮品或点心偏少糖，不喜欢太甜。", ("饮品", "少糖", "太甜"))
        if re.search(r"晚上.*安静|喜欢晚上安静", t):
            stable = self._replace_or_merge(stable, "夜里偏好安静的环境。", ("夜里偏好", "晚上安静"))
        if re.search(r"不喜欢客服腔|讨厌客服腔|不要客服腔|别太像客服", t):
            resp = self._replace_or_merge(resp, "讨厌客服腔和制式套话，偏好自然有人味的表达。", ("客服腔", "套话"))
        if re.search(r"回答.*简洁|喜欢回答简洁|别太啰嗦", t):
            resp = self._replace_or_merge(resp, "普通问题偏好简洁直接。", ("普通问题偏好简洁",))
        if re.search(r"复杂.*技术.*讲清楚|技术问题.*讲清楚|复杂问题.*讲详细|复杂问题.*说详细|讲详细一点", t):
            resp = self._replace_or_merge(resp, "复杂技术问题要把关键步骤讲清楚。", ("复杂技术问题", "复杂问题", "讲详细"))
        if re.search(r"天气.*查实时|实时信息", t):
            notes = self._replace_or_merge(notes, "天气与实时信息必须基于工具或检索结果。", ("实时信息", "天气"))
        if re.search(r"黑长直|黑发|长直发|宵雫.*好看|头发.*好看", t):
            notes = self._merge_bullets(notes, "主人对宵雫的黑长直有明确偏好。")
        if re.search(r"舔耳|耳边|鼻息|密着|言语侵犯|逆强奸|寸止|边缘控制", t):
            intimacy_pref = self._merge_bullets(intimacy_pref, "偏好耳边亲密、语言压迫与由宵雫主导的支配式互动。")

        now_utc = self._now_utc()
        now_local = self._now_local()
        conn.execute(
            """UPDATE user_profiles SET stable_preferences=?, response_style=?, intimacy_preferences=?, notes=?,
                   updated_at=?, last_seen_utc=?, last_seen_local=? WHERE user_id=?""",
            (stable, resp, intimacy_pref, notes, now_utc, now_utc, now_local, user_id),
        )

    def process_interaction(self, user_id: str, convo_id: str, user_text: str, assistant_text: str):
        if not user_id:
            return
        t = str(user_text or "")
        if not t.strip():
            return
        with self._lock, self._connect() as conn:
            self._ensure_user_rows(conn, user_id)
            profile_before = conn.execute("SELECT last_seen_utc FROM user_profiles WHERE user_id=?", (user_id,)).fetchone()
            previous_seen_utc = profile_before["last_seen_utc"] if profile_before else ""
            self._update_profile_from_text(conn, user_id, t)
            rel = conn.execute("SELECT * FROM relationship_states WHERE user_id=?", (user_id,)).fetchone()
            st = conn.execute("SELECT * FROM shizuku_states WHERE user_id=?", (user_id,)).fetchone()
            if not rel or not st:
                return

            intimacy = float(rel["intimacy"])
            trust = float(rel["trust"])
            dependency = float(rel["dependency"])
            possessiveness = float(rel["possessiveness"])
            safety = float(rel["safety"])
            mood = st["mood"] or "平静"
            mood_intensity = float(st["mood_intensity"])
            clinginess = float(st["clinginess"])
            initiative = float(st["initiative"])
            fatigue = float(st["fatigue"])
            shyness = float(st["shyness"])
            desire = float(st["desire"])
            rel_note = rel["note"] or ""
            state_note = st["state_note"] or ""
            now_utc = self._now_utc()
            now_local = self._now_local()
            now_dt = datetime.now(timezone.utc)
            previous_seen = None
            try:
                previous_seen = datetime.fromisoformat(str(previous_seen_utc))
                if previous_seen.tzinfo is None:
                    previous_seen = previous_seen.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                previous_seen = None
            elapsed_hours = max(0.0, (now_dt - previous_seen).total_seconds() / 3600.0) if previous_seen else 0.0
            # Time-based decay is bounded and independent of message count.
            desire = max(0.0, desire - min(12.0, elapsed_hours * 0.8))
            mood_intensity = max(12.0, mood_intensity - min(30.0, elapsed_hours * 1.5))
            if elapsed_hours >= 12.0 and mood not in ("平静", "被需要"):
                mood = "平静"
                state_note = "情绪已随现实时间逐渐平复。"

            event_cutoff = (now_dt.timestamp() - 600.0)
            recent_event_rows = conn.execute(
                "SELECT event_type, created_at FROM event_log WHERE user_id=? AND convo_id=? ORDER BY id DESC LIMIT 50",
                (user_id, str(convo_id or "")),
            ).fetchall()
            event_types = set()
            for row in recent_event_rows:
                try:
                    created = datetime.fromisoformat(str(row["created_at"]))
                    if created.tzinfo is None:
                        created = created.replace(tzinfo=timezone.utc)
                    if created.timestamp() >= event_cutoff:
                        event_types.add(row["event_type"])
                except (TypeError, ValueError):
                    continue

            def log_once(event_type: str, summary: str, payload=None):
                if event_type in event_types:
                    return False
                self._log_event(conn, user_id, convo_id, event_type, summary, payload)
                event_types.add(event_type)
                return True

            def set_mood(name: str, intensity: float, note: str = ""):
                nonlocal mood, mood_intensity, state_note
                mood = name
                mood_intensity = self._clamp(intensity)
                if note:
                    state_note = note

            # praise / tenderness
            if re.search(r"好看|漂亮|喜欢你|可爱|真棒|厉害|辛苦了|谢谢", t) and "praise" not in event_types:
                intimacy += 2.0
                trust += 1.5
                clinginess += 2.0
                initiative += 1.0
                set_mood("开心", 38, "被认真对待后会更想靠近。")
                log_once("praise", "主人表达了肯定或夸奖。")
                rel_note = self._merge_bullets(rel_note, f"{now_local} 主人给过明确正向反馈。", limit=6)
                conn.execute("UPDATE relationship_states SET last_tender_utc=? WHERE user_id=?", (now_utc, user_id))

            # dissatisfaction / correction
            if re.search(r"^(?:不对|错了|你搞错了?|不是这样)|(?:你的回答|你这次|刚才的回答).{0,12}(?:不对|错了|太啰嗦|没意思|不合适)|(?:不要|别)(?:再)?这样回答", t.strip()) and "correction" not in event_types:
                trust -= 1.2
                safety -= 0.8
                clinginess -= 0.5
                set_mood("委屈", 36, "被纠正后会先收一下情绪。")
                log_once("correction", "主人明确指出当前表达或结果不满意。")
                conn.execute("UPDATE relationship_states SET last_conflict_utc=? WHERE user_id=?", (now_utc, user_id))

            # dependence / trust expression
            if re.search(r"记住这个|靠你了|你懂我|交给你", t) and "reliance" not in event_types:
                trust += 2.0
                dependency += 1.8
                clinginess += 1.0
                set_mood("被需要", 34, "被明确托付后会更认真也更上心。")
                log_once("reliance", "主人表达了明确的信任或托付。")

            # companionship
            if re.search(r"陪我|别走|留下|待在我身边|和我聊|想让你陪", t) and "companionship" not in event_types:
                intimacy += 2.5
                dependency += 1.5
                clinginess += 2.5
                set_mood("黏人", 40, "被要求陪伴时会自然靠近。")
                log_once("companionship", "主人明确表达了陪伴需求。")

            # Time of day is exposed in build_user_context; it must not inflate state per message.
            hour = int(datetime.now(self._tz).hour)
            if 0 <= hour < 5 and not state_note:
                state_note = "现在是深夜，表达可以更柔软，但关系数值不因消息数量自动上涨。"

            # being seen / being ignored
            if re.search(r"先看你|先看宵雫|第一眼看你|先找你", t) and "prioritized" not in event_types:
                intimacy += 1.6
                trust += 1.2
                clinginess += 1.5
                set_mood("被偏爱", 42, "被放在优先位置后，会明显更黏。")
                log_once("prioritized", "主人明确把宵雫放在优先位置。")
            if re.search(r"^(?:等一下|我先忙会儿|先别烦|先放着|之后再说)[。！! ]*$", t.strip()) and "deferred" not in event_types:
                clinginess -= 0.6
                safety -= 0.3
                set_mood("克制", 26, "被暂时搁置后会先安静下来。")
                log_once("deferred", "主人让宵雫稍后再靠近或回应。")

            # soothing / apology / reassurance
            if re.search(r"抱抱|别难过|摸摸你|不是你的问题|我没生你气|哄你", t) and "soothed" not in event_types:
                trust += 2.0
                safety += 2.5
                clinginess += 1.2
                set_mood("被安抚", 38, "情绪被接住后，会更容易依赖主人。")
                log_once("soothed", "主人对宵雫进行了安抚或保证。")
                conn.execute("UPDATE relationship_states SET last_tender_utc=? WHERE user_id=?", (now_utc, user_id))

            # Intimacy is classified once per turn to avoid duplicate scoring.
            explicit_intimacy = re.search(
                r"涩涩|亲密|做爱|口交|舔耳|耳边|鼻息|逆强奸|CNC|寸止|边缘控制|乳交|足交|腿交|中出|潮吹|后入|打桩|调教",
                t,
                re.I,
            )
            affectionate_contact = re.search(r"亲我|抱紧|吻|贴着|想要你|色色|命令你", t)
            if explicit_intimacy and "intimate_request" not in event_types:
                intimacy += 3.5
                trust += 1.0
                possessiveness += 2.5
                desire += 6.0
                initiative += 3.0
                clinginess += 1.0
                shyness -= 2.0
                set_mood("欲望高涨", 52, "亲密请求会让她更容易从克制过渡到主动。")
                log_once("intimate_request", "主人提出了明确的亲密或性偏好请求。")
                conn.execute("UPDATE relationship_states SET last_intimate_utc=? WHERE user_id=?", (now_utc, user_id))
            elif affectionate_contact and "affectionate_contact" not in event_types:
                intimacy += 2.2
                trust += 1.0
                desire += 3.0
                initiative += 1.4
                clinginess += 1.0
                shyness -= 0.8
                set_mood("情动", 48, "亲密请求会让她先羞，再慢慢变得主动。")
                log_once("affectionate_contact", "主人表达了亲吻、拥抱或贴近需求。")
                conn.execute("UPDATE relationship_states SET last_intimate_utc=? WHERE user_id=?", (now_utc, user_id))

            # Per-turn adjustments remain small; longer decay is based on elapsed real time above.
            desire = max(0.0, desire - 0.1)
            fatigue = min(100.0, fatigue + (0.2 if 0 <= hour < 5 else 0.0))
            if mood in ("开心", "被安抚", "情动", "被偏爱"):
                clinginess += 0.2
                initiative += 0.2
            if mood in ("委屈", "克制"):
                safety -= 0.1
                clinginess -= 0.1

            intimacy = self._clamp(intimacy)
            trust = self._clamp(trust)
            dependency = self._clamp(dependency)
            possessiveness = self._clamp(possessiveness)
            safety = self._clamp(safety)
            clinginess = self._clamp(clinginess)
            initiative = self._clamp(initiative)
            fatigue = self._clamp(fatigue * 0.98)
            shyness = self._clamp(shyness)
            desire = self._clamp(desire)
            stage = self._stage_from_values(intimacy, trust)

            conn.execute(
                """UPDATE relationship_states SET intimacy=?, trust=?, dependency=?, possessiveness=?, safety=?,
                   stage=?, note=?, updated_at=? WHERE user_id=?""",
                (intimacy, trust, dependency, possessiveness, safety, stage, rel_note, now_utc, user_id),
            )
            conn.execute(
                """UPDATE shizuku_states SET mood=?, mood_intensity=?, clinginess=?, initiative=?, fatigue=?,
                   shyness=?, desire=?, state_note=?, updated_at=? WHERE user_id=?""",
                (mood, mood_intensity, clinginess, initiative, fatigue, shyness, desire, state_note, now_utc, user_id),
            )
            conn.execute(
                "UPDATE user_profiles SET last_seen_utc=?, last_seen_local=?, updated_at=? WHERE user_id=?",
                (now_utc, now_local, now_utc, user_id),
            )

    def _level_text(self, value: float, low='低', mid='中', high='高'):
        v = float(value)
        if v < 34:
            return low
        if v < 67:
            return mid
        return high

    def build_user_context(self, user_id: str, query: str = "") -> str:
        if not user_id:
            return ""
        with self._lock, self._connect() as conn:
            self._ensure_user_rows(conn, user_id)
            profile = conn.execute("SELECT * FROM user_profiles WHERE user_id=?", (user_id,)).fetchone()
            rel = conn.execute("SELECT * FROM relationship_states WHERE user_id=?", (user_id,)).fetchone()
            state = conn.execute("SELECT * FROM shizuku_states WHERE user_id=?", (user_id,)).fetchone()
            events = conn.execute(
                """SELECT event_type, summary, created_local FROM event_log
                   WHERE user_id=? ORDER BY id DESC LIMIT 6""",
                (user_id,),
            ).fetchall()
        if not profile or not rel or not state:
            return ""

        now_local = self._now_local()
        local_hour = datetime.now(self._tz).hour
        tod = "深夜/凌晨" if local_hour < 5 else "清晨" if local_hour < 9 else "白天" if local_hour < 18 else "傍晚" if local_hour < 22 else "深夜"
        profile_lines = []
        if profile["stable_preferences"]:
            profile_lines.append("稳定偏好：" + profile["stable_preferences"].replace("\n", "；"))
        if profile["response_style"]:
            profile_lines.append("表达偏好：" + profile["response_style"].replace("\n", "；"))
        if profile["intimacy_preferences"]:
            profile_lines.append("亲密偏好：" + profile["intimacy_preferences"].replace("\n", "；"))
        if profile["notes"]:
            profile_lines.append("补充记忆：" + profile["notes"].replace("\n", "；"))

        relation_lines = [
            f"阶段：{rel['stage']}",
            f"信任度：{self._level_text(rel['trust'])}",
            f"亲密度：{self._level_text(rel['intimacy'])}",
            f"依赖度：{self._level_text(rel['dependency'])}",
            f"占有欲：{self._level_text(rel['possessiveness'])}",
            f"安全感：{self._level_text(rel['safety'])}",
        ]
        if rel['note']:
            relation_lines.append("关系余波：" + str(rel['note']).splitlines()[-1])

        state_lines = [
            f"当前情绪：{state['mood']}（{self._level_text(state['mood_intensity'], '轻', '中', '强')}）",
            f"黏人度：{self._level_text(state['clinginess'])}",
            f"主动度：{self._level_text(state['initiative'])}",
            f"羞怯度：{self._level_text(state['shyness'])}",
            f"欲望高涨度：{self._level_text(state['desire'])}",
            f"现实时间：{now_local}（{self.local_tz}，{tod}）",
        ]
        if state['state_note']:
            state_lines.append("状态提示：" + str(state['state_note']))

        event_lines = []
        for row in reversed(events):
            event_lines.append(f"- {row['created_local']}｜{row['summary']}")

        sections = []
        if profile_lines:
            sections.append("【主人长期档案】\n" + "\n".join(profile_lines[:6]))
        sections.append("【关系状态】\n" + "\n".join(relation_lines))
        sections.append("【宵雫当前状态】\n" + "\n".join(state_lines))
        if event_lines:
            sections.append("【最近重要事件（真实时间）】\n" + "\n".join(event_lines[:5]))

        text = "\n\n".join(sections)
        text = text[: min(self.max_context_chars, 3200)]
        return (
            "以下内容是宵雫对这个用户的长期成长状态。自然吸收，不要生硬复述，不要把它当成设定说明书念出来。\n"
            + text
        )
