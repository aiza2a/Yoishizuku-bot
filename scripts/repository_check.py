#!/usr/bin/env python3
"""Static regression checks for repository wiring that must hold before image publication."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
bot = (ROOT / "app" / "bot.py").read_text(encoding="utf-8")
config = (ROOT / "app" / "config.py").read_text(encoding="utf-8")
dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
verify = (ROOT / "scripts" / "verify.sh").read_text(encoding="utf-8")

checks = {
    "persona_default_path": "'/home/persona/systemprompt.md'" in config,
    "persona_image_default": "ENV SYSTEMPROMPT_FILE=/home/persona/systemprompt.md" in dockerfile,
    "persona_env_example": "SYSTEMPROMPT_FILE=/home/persona/systemprompt.md" in env_example,
    "draft_has_id": '"draft_id": draft_id' in bot,
    "draft_does_not_read_message_id": "draft_resp[" not in bot,
    "draft_streams_via_draft_api": "async def _update_draft" in bot,
    "global_model_change_is_guarded": "_configuration_change_allowed" in bot,
    "global_config_requires_admin": "return bool(config.ADMIN_LIST" in bot,
    "role_memory_writes_are_guarded": "_role_shared_memory_mutation_allowed" in bot,
    "verify_uses_current_container": "CONTAINER_NAME=${CONTAINER_NAME:-Yoishizuku-bot}" in verify,
    "legacy_workflow_removed": not (ROOT / ".github" / "workflows" / "main.yml").exists(),
}

failed = [name for name, passed in checks.items() if not passed]
for name, passed in checks.items():
    print(("PASS" if passed else "FAIL"), name)
if failed:
    raise SystemExit("repository wiring checks failed: " + ", ".join(failed))
