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
    "weather_plugin_is_built": "aient_weather.py        /home/aient/aient/plugins/weather.py" in dockerfile,
    "image_plugin_is_built": "aient_image.py          /home/aient/aient/plugins/image.py" in dockerfile,
    "image_search_plugin_is_built": "aient_image_search.py   /home/aient/aient/plugins/image_search.py" in dockerfile,
    "persona_covers_scoped_search": "### 检索范围的选择" in (ROOT / "persona" / "modules" / "13_task_execution.md").read_text(encoding="utf-8"),
    "sync_plugins_run_off_event_loop": "asyncio.to_thread(function_to_call" in (ROOT / "app" / "overrides" / "aient_plugins_config.py").read_text(encoding="utf-8"),
    "image_bytes_uploaded_directly": "def _fetch_image_bytes" in bot and "asyncio.to_thread(_fetch_image_bytes" in bot,
    "guest_has_status_animation": "_animate_guest" in bot and "guest_status_stop.set()" in bot,
    "guest_animation_stops_on_exit": "finally:" in bot and bot.count("guest_status_task.cancel()") >= 2,
    "guest_shows_generated_image": "generated_image and not generated_image.startswith" in bot,
    "image_gateway_retries": "retrying" in (ROOT / "app" / "overrides" / "aient_image.py").read_text(encoding="utf-8"),
    "tool_execution_has_timeout": "TOOL_EXECUTION_TIMEOUT" in (ROOT / "app" / "overrides" / "aient_plugins_config.py").read_text(encoding="utf-8"),
    "generated_image_uses_event": "message_generated_image:" in bot and "message_generated_image:" in (ROOT / "app" / "overrides" / "aient_chatgpt.py").read_text(encoding="utf-8"),
    "preamble_before_tool_is_discarded": "message_tool_discard_preamble" in bot and "Discarding %d chars emitted before tool execution" in (ROOT / "app" / "overrides" / "aient_chatgpt.py").read_text(encoding="utf-8"),
    "persona_forbids_premature_failure": "绝对不能先说它失败" in (ROOT / "persona" / "modules" / "13_task_execution.md").read_text(encoding="utf-8"),
    "persona_covers_retry": "### 重新回答" in (ROOT / "persona" / "modules" / "13_task_execution.md").read_text(encoding="utf-8"),
    "model_panel_has_two_levels": "def update_model_kind_buttons" in config and "def update_image_models_buttons" in config,
    "info_shows_image_model": '"• " + t["image_model"]' in config,
    "image_model_callback_registered": '_IMAGEMODELS' in bot,
    "image_plugin_reads_panel_choice": "config.get_image_engine(None)" in (ROOT / "app" / "overrides" / "aient_image.py").read_text(encoding="utf-8"),
    "search_prompt_keeps_persona": "do not switch" in (ROOT / "app" / "overrides" / "aient_plugins_config.py").read_text(encoding="utf-8"),
    "rich_mode_avoids_markdownv2_escape": "def _rich_markdown" in bot and 'rich_message": {"markdown": escape(' not in bot,
    "stream_updates_honour_retry_after": "stream_retry_until" in bot,
    "tool_running_animation": "message_tool_running:" in bot,
    "generated_image_send_is_tolerant": "生图工具返回中没有可用的图片地址" in bot,
    "retry_command_registered": 'CommandHandler("retry", retry_chat)' in bot,
    "retry_rolls_back_memory": "MEMORY.pop_last_turn(runtime_convo_id)" in bot,
    "memory_supports_turn_rollback": "def pop_last_turn" in (ROOT / "app" / "overrides" / "memory_store.py").read_text(encoding="utf-8"),
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
