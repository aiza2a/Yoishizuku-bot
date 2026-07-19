#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

python3 -m py_compile \
  app/bot.py \
  app/config.py \
  app/overrides/memory_store.py \
  app/overrides/role_dialogue_store.py \
  app/overrides/i18n_override.py \
  app/overrides/decorators_override.py \
  app/overrides/bot_utils_scripts.py \
  app/overrides/access_control.py \
  app/overrides/aient_base.py \
  app/overrides/aient_chatgpt.py \
  app/overrides/aient_utils_scripts.py \
  app/overrides/aient_run_python.py \
  persona/build_persona_prompt.py

docker compose config --quiet
python3 scripts/regression_check.py
python3 scripts/role_dialogue_check.py

docker compose run --rm --no-deps \
  -v "$ROOT/scripts/persona_messages_check.py:/tmp/persona_check.py:ro" \
  --entrypoint python chatgptbot /tmp/persona_check.py

docker compose run --rm --no-deps \
  -v "$ROOT/scripts/allow_check.py:/tmp/allow_check.py:ro" \
  --entrypoint python chatgptbot /tmp/allow_check.py

docker compose run --rm --no-deps \
  -v "$ROOT/scripts/allow_command_check.py:/tmp/allow_command_check.py:ro" \
  --entrypoint python chatgptbot /tmp/allow_command_check.py

docker compose run --rm --no-deps \
  -v "$ROOT/scripts/nick_alias_check.py:/tmp/nick_alias_check.py:ro" \
  --entrypoint python chatgptbot /tmp/nick_alias_check.py

status=$(docker inspect GPTBOT --format '{{.State.Status}}' 2>/dev/null || true)
restarts=$(docker inspect GPTBOT --format '{{.RestartCount}}' 2>/dev/null || true)
[ "$status" = "running" ]
[ "$restarts" = "0" ]

docker exec -e PYTHONPYCACHEPREFIX=/tmp/pycache GPTBOT \
  python -m py_compile /home/bot.py /home/config.py /home/memory_store.py

echo "ALL_CHECKS_PASS status=$status restarts=$restarts"
