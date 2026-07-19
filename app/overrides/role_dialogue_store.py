#!/usr/bin/env python3
"""Persistent owner-scoped roles and dialogue profiles for GPTBOT."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class RoleDialogueStore:
    VERSION = 2
    DEFAULT_ROLE_ID = "shizuku"
    ROLE_ID = DEFAULT_ROLE_ID
    ROLE_NAME = "藍沢宵雫"
    DEFAULT_DIALOGUE_ID = "default"
    MAX_CUSTOM_ROLES = 3
    MAX_ACTIVE_DIALOGUES = 10
    MAX_DIALOGUE_NAME_CHARS = 80
    MAX_ROLE_NAME_CHARS = 60
    MAX_ROLE_FIELD_CHARS = 2000

    def __init__(self, root: str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.root, 0o700)
        except OSError:
            pass

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def _clean(value, fallback="", limit=2000):
        value = re.sub(r"\s+", " ", str(value or "").strip())
        value = value.replace("\x00", "")
        return value[:limit] or fallback

    def _path(self, owner_key: str) -> Path:
        digest = hashlib.sha256(str(owner_key).encode("utf-8")).hexdigest()[:32]
        return self.root / (digest + ".json")

    @contextmanager
    def _locked(self, owner_key: str):
        path = self._path(owner_key)
        lock_path = Path(str(path) + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, "a+", encoding="utf-8") as lock_file:
            try:
                import fcntl
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            except (ImportError, OSError):
                pass
            try:
                yield path
            finally:
                try:
                    import fcntl
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                except (ImportError, OSError):
                    pass

    def _runtime_key(self, owner_key, role_id, dialogue_id):
        if role_id == self.DEFAULT_ROLE_ID and dialogue_id == self.DEFAULT_DIALOGUE_ID:
            return str(owner_key)
        return f"{owner_key}::role::{role_id}::dialogue::{dialogue_id}"

    def _default_dialogue(self, owner_key, role_id=None):
        role_id = role_id or self.DEFAULT_ROLE_ID
        now = self._now()
        return {
            "id": self.DEFAULT_DIALOGUE_ID,
            "name": "默认对话",
            "runtime_key": self._runtime_key(owner_key, role_id, self.DEFAULT_DIALOGUE_ID),
            "created_at": now,
            "updated_at": now,
            "archived": False,
        }

    def _default_role(self, owner_key):
        now = self._now()
        return {
            "id": self.DEFAULT_ROLE_ID,
            "name": self.ROLE_NAME,
            "default": True,
            "archived": False,
            "identity": "藍沢宵雫",
            "tone": "",
            "welcome": "",
            "prompt": "",
            "created_at": now,
            "updated_at": now,
            "active_dialogue": self.DEFAULT_DIALOGUE_ID,
            "dialogues": [self._default_dialogue(owner_key)],
        }

    def _migrate(self, raw, owner_key):
        changed = False
        if isinstance(raw, dict) and isinstance(raw.get("roles"), list):
            roles = raw.get("roles")
            active_role = str(raw.get("active_role") or self.DEFAULT_ROLE_ID)
        elif isinstance(raw, dict) and isinstance(raw.get("dialogues"), list):
            # Version 1 stored one role at the document root. Preserve every
            # dialogue and its runtime key, especially the legacy default key.
            role = self._default_role(owner_key)
            role["id"] = str(raw.get("role_id") or self.DEFAULT_ROLE_ID)
            role["name"] = self._clean(raw.get("role_name"), self.ROLE_NAME, self.MAX_ROLE_NAME_CHARS)
            role["default"] = role["id"] == self.DEFAULT_ROLE_ID
            role["dialogues"] = raw.get("dialogues")
            role["active_dialogue"] = str(raw.get("active_dialogue") or self.DEFAULT_DIALOGUE_ID)
            roles = [role]
            active_role = role["id"]
            changed = True
        else:
            roles = []
            active_role = self.DEFAULT_ROLE_ID
            changed = True

        normalized = []
        seen_roles = set()
        for raw_role in roles:
            if not isinstance(raw_role, dict):
                changed = True
                continue
            role_id = self._clean(raw_role.get("id"), "", 40)
            if not role_id or role_id in seen_roles:
                changed = True
                continue
            seen_roles.add(role_id)
            role = dict(raw_role)
            role["id"] = role_id
            role["name"] = self._clean(role.get("name"), role_id, self.MAX_ROLE_NAME_CHARS)
            role["default"] = bool(role.get("default", role_id == self.DEFAULT_ROLE_ID))
            role["archived"] = bool(role.get("archived", False))
            role["identity"] = self._clean(role.get("identity"), role["name"], self.MAX_ROLE_FIELD_CHARS)
            role["tone"] = self._clean(role.get("tone"), "", self.MAX_ROLE_FIELD_CHARS)
            role["welcome"] = self._clean(role.get("welcome"), "", self.MAX_ROLE_FIELD_CHARS)
            role["prompt"] = self._clean(role.get("prompt"), "", self.MAX_ROLE_FIELD_CHARS)
            role["created_at"] = str(role.get("created_at") or self._now())
            role["updated_at"] = str(role.get("updated_at") or role["created_at"])
            role["active_dialogue"] = str(role.get("active_dialogue") or self.DEFAULT_DIALOGUE_ID)
            dialogues = []
            seen_dialogues = set()
            for raw_dialogue in role.get("dialogues", []):
                if not isinstance(raw_dialogue, dict):
                    changed = True
                    continue
                dialogue_id = self._clean(raw_dialogue.get("id"), "", 50)
                if not dialogue_id or dialogue_id in seen_dialogues:
                    changed = True
                    continue
                seen_dialogues.add(dialogue_id)
                dialogue = dict(raw_dialogue)
                dialogue["id"] = dialogue_id
                dialogue["name"] = self._clean(dialogue.get("name"), dialogue_id, self.MAX_DIALOGUE_NAME_CHARS)
                dialogue["runtime_key"] = str(dialogue.get("runtime_key") or self._runtime_key(owner_key, role_id, dialogue_id))
                dialogue["created_at"] = str(dialogue.get("created_at") or self._now())
                dialogue["updated_at"] = str(dialogue.get("updated_at") or dialogue["created_at"])
                dialogue["archived"] = bool(dialogue.get("archived", False))
                dialogues.append(dialogue)
            if not any(item["id"] == self.DEFAULT_DIALOGUE_ID for item in dialogues):
                dialogues.insert(0, self._default_dialogue(owner_key, role_id))
                changed = True
            if role["active_dialogue"] not in {item["id"] for item in dialogues if not item["archived"]}:
                role["active_dialogue"] = self.DEFAULT_DIALOGUE_ID
                changed = True
            role["dialogues"] = dialogues
            normalized.append(role)

        default = next((role for role in normalized if role["id"] == self.DEFAULT_ROLE_ID), None)
        if default is None:
            normalized.insert(0, self._default_role(owner_key))
            default = normalized[0]
            changed = True
        else:
            default["default"] = True
            if default["name"] == "shizuku":
                default["name"] = self.ROLE_NAME
                changed = True

        active_ids = {role["id"] for role in normalized if not role.get("archived")}
        if active_role not in active_ids:
            active_role = self.DEFAULT_ROLE_ID
            changed = True
        data = {"version": self.VERSION, "active_role": active_role, "roles": normalized}
        if not isinstance(raw, dict) or raw.get("version") != self.VERSION:
            changed = True
        return data, changed

    @staticmethod
    def _write(path: Path, data):
        directory = str(path.parent)
        fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=directory)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
            os.chmod(path, 0o600)
            try:
                dir_fd = os.open(directory, os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except OSError:
                pass
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def _read_locked(self, path, owner_key):
        if not path.exists():
            return self._default_document(owner_key), True
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            data, changed = self._migrate(raw, owner_key)
            return data, changed
        except Exception:
            try:
                damaged = Path(str(path) + ".corrupt." + str(int(datetime.now().timestamp())))
                os.replace(path, damaged)
                os.chmod(damaged, 0o600)
            except OSError:
                pass
            return self._default_document(owner_key), True

    def _default_document(self, owner_key):
        role = self._default_role(owner_key)
        return {"version": self.VERSION, "active_role": self.DEFAULT_ROLE_ID, "roles": [role]}

    def _load_locked(self, path, owner_key):
        data, changed = self._read_locked(path, owner_key)
        if changed or not path.exists():
            self._write(path, data)
        return data

    @staticmethod
    def _copy(value):
        return json.loads(json.dumps(value, ensure_ascii=False))

    def ensure(self, owner_key):
        owner_key = str(owner_key)
        with self._locked(owner_key) as path:
            return self._copy(self._load_locked(path, owner_key))

    def _role_locked(self, data, role_id):
        return next((role for role in data["roles"] if role["id"] == str(role_id)), None)

    def active_role(self, owner_key):
        owner_key = str(owner_key)
        with self._locked(owner_key) as path:
            data = self._load_locked(path, owner_key)
            role = self._role_locked(data, data["active_role"])
            return self._copy(role or self._role_locked(data, self.DEFAULT_ROLE_ID))

    def list_roles(self, owner_key, include_archived=False):
        owner_key = str(owner_key)
        with self._locked(owner_key) as path:
            data = self._load_locked(path, owner_key)
            active = data["active_role"]
            rows = [self._copy(role) for role in data["roles"] if include_archived or not role.get("archived")]
            rows.sort(key=lambda role: (role["id"] != active, role.get("updated_at", "")))
            return rows

    def active_context(self, owner_key):
        role = self.active_role(owner_key)
        dialogue = next((item for item in role["dialogues"] if item["id"] == role["active_dialogue"] and not item.get("archived")), None)
        if dialogue is None:
            dialogue = next(item for item in role["dialogues"] if item["id"] == self.DEFAULT_DIALOGUE_ID)
        return {"role": self._copy(role), "dialogue": self._copy(dialogue)}

    def active(self, owner_key):
        context = self.active_context(str(owner_key))
        role = context["role"]
        dialogue = context["dialogue"]
        result = dict(dialogue)
        result.update({
            "role_id": role["id"],
            "role_name": role["name"],
            "role_default": role.get("default", False),
            "role_identity": role.get("identity", ""),
            "role_tone": role.get("tone", ""),
            "role_welcome": role.get("welcome", ""),
            "role_prompt": role.get("prompt", ""),
        })
        return result

    def list_dialogues(self, owner_key, include_archived=False, role_id=None):
        owner_key = str(owner_key)
        with self._locked(owner_key) as path:
            data = self._load_locked(path, owner_key)
            role = self._role_locked(data, role_id or data["active_role"])
            if role is None:
                return []
            active = role["active_dialogue"]
            rows = [self._copy(item) for item in role["dialogues"] if include_archived or not item.get("archived")]
            rows.sort(key=lambda item: (item["id"] != active, item.get("updated_at", "")))
            return rows

    def switch_role(self, owner_key, role_id):
        owner_key = str(owner_key)
        with self._locked(owner_key) as path:
            data = self._load_locked(path, owner_key)
            role = self._role_locked(data, role_id)
            if role is None or role.get("archived"):
                return None
            data["active_role"] = role["id"]
            role["updated_at"] = self._now()
            self._write(path, data)
            return self._copy(role)

    def create_role(self, owner_key, name, clone_from=None):
        owner_key = str(owner_key)
        label = self._clean(name, "", self.MAX_ROLE_NAME_CHARS)
        if not label:
            raise ValueError("empty_name")
        with self._locked(owner_key) as path:
            data = self._load_locked(path, owner_key)
            custom = [role for role in data["roles"] if role["id"] != self.DEFAULT_ROLE_ID and not role.get("archived")]
            if len(custom) >= self.MAX_CUSTOM_ROLES:
                raise ValueError("role_limit")
            if any(role["name"] == label and not role.get("archived") for role in data["roles"]):
                raise ValueError("duplicate_name")
            source = self._role_locked(data, clone_from) if clone_from else None
            now = self._now()
            role_id = "r_" + uuid.uuid4().hex[:12]
            role = {
                "id": role_id,
                "name": label,
                "default": False,
                "archived": False,
                "identity": source.get("identity", label) if source else label,
                "tone": source.get("tone", "") if source else "",
                "welcome": source.get("welcome", "") if source else "",
                "prompt": source.get("prompt", "") if source else "",
                "created_at": now,
                "updated_at": now,
                "active_dialogue": self.DEFAULT_DIALOGUE_ID,
                "dialogues": [self._default_dialogue(owner_key, role_id)],
            }
            data["roles"].append(role)
            data["active_role"] = role_id
            self._write(path, data)
            return self._copy(role)

    def rename_role(self, owner_key, role_id, name):
        owner_key = str(owner_key)
        label = self._clean(name, "", self.MAX_ROLE_NAME_CHARS)
        if not label:
            raise ValueError("empty_name")
        if str(role_id) == self.DEFAULT_ROLE_ID:
            raise ValueError("default_role")
        with self._locked(owner_key) as path:
            data = self._load_locked(path, owner_key)
            if any(role["id"] != str(role_id) and role["name"] == label and not role.get("archived") for role in data["roles"]):
                raise ValueError("duplicate_name")
            role = self._role_locked(data, role_id)
            if role is None or role.get("archived"):
                return None
            role["name"] = label
            role["updated_at"] = self._now()
            self._write(path, data)
            return self._copy(role)

    def update_role(self, owner_key, role_id, field, value):
        owner_key = str(owner_key)
        if field not in ("identity", "tone", "welcome", "prompt"):
            raise ValueError("invalid_field")
        value = self._clean(value, "", self.MAX_ROLE_FIELD_CHARS)
        if not value:
            raise ValueError("empty_value")
        with self._locked(owner_key) as path:
            data = self._load_locked(path, owner_key)
            role = self._role_locked(data, role_id)
            if role is None or role.get("archived"):
                return None
            role[field] = value
            role["updated_at"] = self._now()
            self._write(path, data)
            return self._copy(role)

    def archive_role(self, owner_key, role_id):
        owner_key = str(owner_key)
        if str(role_id) == self.DEFAULT_ROLE_ID:
            return False
        with self._locked(owner_key) as path:
            data = self._load_locked(path, owner_key)
            role = self._role_locked(data, role_id)
            if role is None or role.get("archived"):
                return False
            role["archived"] = True
            role["updated_at"] = self._now()
            if data["active_role"] == role["id"]:
                data["active_role"] = self.DEFAULT_ROLE_ID
            self._write(path, data)
            return True

    def restore_role(self, owner_key, role_id):
        owner_key = str(owner_key)
        with self._locked(owner_key) as path:
            data = self._load_locked(path, owner_key)
            role = self._role_locked(data, role_id)
            if role is None or not role.get("archived"):
                return None
            custom = [item for item in data["roles"] if item["id"] != self.DEFAULT_ROLE_ID and not item.get("archived")]
            if len(custom) >= self.MAX_CUSTOM_ROLES:
                raise ValueError("role_limit")
            role["archived"] = False
            role["updated_at"] = self._now()
            self._write(path, data)
            return self._copy(role)

    def role_shared_key(self, owner_key, role_id=None):
        owner_key = str(owner_key)
        with self._locked(owner_key) as path:
            data = self._load_locked(path, owner_key)
            role = self._role_locked(data, role_id or data["active_role"])
            if role is None:
                return None
            return owner_key + "::role_shared::" + str(role["id"])

    def role_runtime_keys(self, owner_key, role_id):
        owner_key = str(owner_key)
        with self._locked(owner_key) as path:
            data = self._load_locked(path, owner_key)
            role = self._role_locked(data, role_id)
            if role is None:
                return []
            return [str(item["runtime_key"]) for item in role["dialogues"]]

    def delete_role(self, owner_key, role_id):
        owner_key = str(owner_key)
        if str(role_id) == self.DEFAULT_ROLE_ID:
            return False
        with self._locked(owner_key) as path:
            data = self._load_locked(path, owner_key)
            for index, role in enumerate(data["roles"]):
                if role["id"] == str(role_id):
                    data["roles"].pop(index)
                    if data["active_role"] == str(role_id):
                        data["active_role"] = self.DEFAULT_ROLE_ID
                    self._write(path, data)
                    return True
        return False

    def switch(self, owner_key, dialogue_id):
        owner_key = str(owner_key)
        with self._locked(owner_key) as path:
            data = self._load_locked(path, owner_key)
            role = self._role_locked(data, data["active_role"])
            if role is None:
                return None
            for item in role["dialogues"]:
                if item["id"] == str(dialogue_id) and not item.get("archived"):
                    role["active_dialogue"] = item["id"]
                    item["updated_at"] = self._now()
                    self._write(path, data)
                    return self._copy(item)
        return None

    def create(self, owner_key, name=""):
        owner_key = str(owner_key)
        label = self._clean(name, "", self.MAX_DIALOGUE_NAME_CHARS)
        with self._locked(owner_key) as path:
            data = self._load_locked(path, owner_key)
            role = self._role_locked(data, data["active_role"])
            active_rows = [item for item in role["dialogues"] if not item.get("archived")]
            if len(active_rows) >= self.MAX_ACTIVE_DIALOGUES:
                raise ValueError("dialogue_limit")
            if not label:
                label = "新对话 " + str(len(active_rows))
            if any(item["name"] == label and not item.get("archived") for item in role["dialogues"]):
                raise ValueError("duplicate_name")
            now = self._now()
            ident = "d_" + uuid.uuid4().hex[:12]
            item = {
                "id": ident,
                "name": label,
                "runtime_key": self._runtime_key(owner_key, role["id"], ident),
                "created_at": now,
                "updated_at": now,
                "archived": False,
            }
            role["dialogues"].append(item)
            role["active_dialogue"] = ident
            role["updated_at"] = now
            self._write(path, data)
            return self._copy(item)

    def rename(self, owner_key, dialogue_id, name):
        owner_key = str(owner_key)
        label = self._clean(name, "", self.MAX_DIALOGUE_NAME_CHARS)
        if not label:
            raise ValueError("empty_name")
        with self._locked(owner_key) as path:
            data = self._load_locked(path, owner_key)
            role = self._role_locked(data, data["active_role"])
            if any(item["id"] != str(dialogue_id) and item["name"] == label and not item.get("archived") for item in role["dialogues"]):
                raise ValueError("duplicate_name")
            for item in role["dialogues"]:
                if item["id"] == str(dialogue_id) and not item.get("archived"):
                    item["name"] = label
                    item["updated_at"] = self._now()
                    self._write(path, data)
                    return self._copy(item)
        return None

    def archive(self, owner_key, dialogue_id):
        owner_key = str(owner_key)
        if str(dialogue_id) == self.DEFAULT_DIALOGUE_ID:
            return False
        with self._locked(owner_key) as path:
            data = self._load_locked(path, owner_key)
            role = self._role_locked(data, data["active_role"])
            for item in role["dialogues"]:
                if item["id"] == str(dialogue_id) and not item.get("archived"):
                    item["archived"] = True
                    item["updated_at"] = self._now()
                    if role["active_dialogue"] == item["id"]:
                        role["active_dialogue"] = self.DEFAULT_DIALOGUE_ID
                    self._write(path, data)
                    return True
        return False

    def restore(self, owner_key, dialogue_id):
        owner_key = str(owner_key)
        with self._locked(owner_key) as path:
            data = self._load_locked(path, owner_key)
            role = self._role_locked(data, data["active_role"])
            active_rows = [item for item in role["dialogues"] if not item.get("archived")]
            if len(active_rows) >= self.MAX_ACTIVE_DIALOGUES:
                raise ValueError("dialogue_limit")
            for item in role["dialogues"]:
                if item["id"] == str(dialogue_id) and item.get("archived"):
                    item["archived"] = False
                    item["updated_at"] = self._now()
                    self._write(path, data)
                    return self._copy(item)
        return None

    def delete(self, owner_key, dialogue_id):
        owner_key = str(owner_key)
        if str(dialogue_id) == self.DEFAULT_DIALOGUE_ID:
            return False
        with self._locked(owner_key) as path:
            data = self._load_locked(path, owner_key)
            role = self._role_locked(data, data["active_role"])
            for index, item in enumerate(role["dialogues"]):
                if item["id"] == str(dialogue_id):
                    role["dialogues"].pop(index)
                    if role["active_dialogue"] == str(dialogue_id):
                        role["active_dialogue"] = self.DEFAULT_DIALOGUE_ID
                    self._write(path, data)
                    return True
        return False
