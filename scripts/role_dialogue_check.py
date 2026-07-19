#!/usr/bin/env python3
"""Static and behavioral checks for role -> dialogue isolation."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app" / "overrides"))
try:
    from role_dialogue_store import RoleDialogueStore
except ModuleNotFoundError:
    from pathlib import Path as _Path
    sys.path.insert(0, "/home")
    from role_dialogue_store import RoleDialogueStore


def check_store():
    with tempfile.TemporaryDirectory() as tmp:
        store = RoleDialogueStore(tmp)
        first = store.ensure("private-1")
        assert first["active_role"] == "shizuku"
        assert store.active("private-1")["runtime_key"] == "private-1"
        role = store.create_role("private-1", "工作助手")
        assert role["id"] != "shizuku"
        active = store.active("private-1")
        assert active["role_id"] == role["id"]
        store.update_role("private-1", role["id"], "tone", "简洁、直接")
        assert store.active("private-1")["role_tone"] == "简洁、直接"
        dialogue = store.create("private-1", "支线故事")
        assert store.active("private-1")["runtime_key"].endswith(dialogue["id"])
        store.switch_role("private-1", "shizuku")
        assert store.active("private-1")["runtime_key"] == "private-1"
        store.rename_role("private-1", role["id"], "工作助手二")
        store.archive_role("private-1", role["id"])
        assert store.restore_role("private-1", role["id"])["archived"] is False
        clone = store.create_role("private-1", "复制助手", clone_from=role["id"])
        assert clone["tone"] == "简洁、直接"
        assert store.delete_role("private-1", clone["id"])
        assert store.delete_role("private-1", "shizuku") is False
        # v1 migration keeps legacy default runtime key.
        legacy_root = Path(tmp) / "legacy"
        legacy_root.mkdir()
        legacy = RoleDialogueStore(str(legacy_root))
        path = legacy._path("legacy-owner")
        path.write_text(json.dumps({
            "version": 1, "role_id": "shizuku", "role_name": "藍沢宵雫",
            "active_dialogue": "default", "dialogues": [
                {"id": "default", "name": "默认对话", "runtime_key": "legacy-owner", "archived": False}
            ]
        }, ensure_ascii=False), encoding="utf-8")
        assert legacy.ensure("legacy-owner")["active_role"] == "shizuku"
        assert legacy.active("legacy-owner")["runtime_key"] == "legacy-owner"
        files = list(Path(tmp).rglob("*.json"))
        assert files and all((os.stat(p).st_mode & 0o077) == 0 for p in files)


def check_source():
    bot_path = Path("/home/bot.py") if Path("/home/bot.py").exists() else ROOT / "app" / "bot.py"
    compose_path = ROOT / "docker-compose.yml"
    if not compose_path.exists():
        compose_path = Path("/tmp/docker-compose.yml")
    bot = bot_path.read_text(encoding="utf-8")
    compose = compose_path.read_text(encoding="utf-8") if compose_path.exists() else ""
    required = [
        "RoleDialogueStore",
        "active_dialogue_context",
        "runtime_convo_id",
        "data={\"config_convo_id\": str(convo_id), \"runtime_convo_id\": runtime_convo_id}",
        "CommandHandler(\"persona\", persona_command)",
        "async def role_dialogue_button",
        "role_dialogue_store.py:/home/role_dialogue_store.py:ro",
        "./data/roles:/home/role_data",
    ]
    for item in required:
        if item not in (bot + compose) and not (item in ("role_dialogue_store.py:/home/role_dialogue_store.py:ro", "./data/roles:/home/role_data") and not compose):
            raise AssertionError(item)
    assert "MEMORY.process_interaction(growth_user_id" in bot
    assert "MEMORY.add_turn(convo_id" in bot
    assert "ROLE_RENAME_PROMPT" in bot
    assert "ROLE_ARCHIVED" in bot
    assert "ROLE_DELETE_CONFIRM" in bot
    assert "_handle_role_pending_text" in bot
    store_path = Path("/home/role_dialogue_store.py") if Path("/home/role_dialogue_store.py").exists() else ROOT / "app" / "overrides" / "role_dialogue_store.py"
    memory_path = Path("/home/memory_store.py") if Path("/home/memory_store.py").exists() else ROOT / "app" / "overrides" / "memory_store.py"
    store_source = store_path.read_text(encoding="utf-8")
    memory_source = memory_path.read_text(encoding="utf-8")
    assert "def rename(" in store_source
    assert "def restore(" in store_source
    assert "def create_role(" in store_source
    assert "def switch_role(" in store_source
    assert "def update_role(" in store_source
    assert "ROLE_SETTINGS" in bot
    assert "ROLE_DIALOGUE_PANEL" in bot
    assert "ROLE_NEW_DIALOGUE" in bot
    assert "role_memory" in bot
    assert "remember_role" in bot
    assert "lore_command" in bot
    assert "canon_command" in bot
    assert "build_role_shared_context" in memory_source
    assert "add_role_shared_memory" in memory_source

    assert 'BotCommand("cancel"' not in bot


if __name__ == "__main__":
    check_store()
    check_source()
    print("ROLE_DIALOGUE_CHECK_PASS")
