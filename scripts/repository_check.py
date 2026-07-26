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
    "draft_disabled_by_default": 'DRAFT_MODE = _persona_os.environ.get("DRAFT_MODE", "")' in bot,
    "draft_opt_in_only": "is_private = DRAFT_MODE and not str(chatid).startswith('-')" in bot,
    "global_model_change_is_guarded": "_configuration_change_allowed" in bot,
    "global_config_requires_admin": "return bool(config.ADMIN_LIST" in bot,
    "role_memory_writes_are_guarded": "_role_shared_memory_mutation_allowed" in bot,
    "scoped_search_plugin_is_built": "aient_scoped_search.py  /home/aient/aient/plugins/scoped_search.py" in dockerfile,
    "scoped_search_config_is_built": "aient_plugins_config.py /home/aient/aient/plugins/config.py" in dockerfile,
    "scoped_search_menu_label": "strings[\"search_scoped\"]" in (ROOT / "app" / "overrides" / "i18n_override.py").read_text(encoding="utf-8"),
    "engine_logs_are_opt_in": "print_log=VERBOSE_ENGINE_LOG" in config and "print_log=True" not in config,
    "guest_falls_back_to_base_url": 'getattr(config, "BASE_URL", None)' in bot,
    "guest_uses_caller_config": "guest_config_id = caller_id" in bot and "Users.extract_plugins_config(guest_config_id)" in bot,
    "guest_reply_context_is_forwarded": "reply_context = raw_guest.get(\"reply_to_message\")" in bot,
    "guest_avoids_high_frequency_stream_edits": "Guest inline messages are heavily rate-limited" in bot,
    "verify_uses_current_container": "CONTAINER_NAME=${CONTAINER_NAME:-Yoishizuku-bot}" in verify,
    "legacy_workflow_removed": not (ROOT / ".github" / "workflows" / "main.yml").exists(),
}

failed = [name for name, passed in checks.items() if not passed]
for name, passed in checks.items():
    print(("PASS" if passed else "FAIL"), name)
if failed:
    raise SystemExit("repository wiring checks failed: " + ", ".join(failed))
