# ── Yoishizuku-bot Dockerfile ──
# Layers custom overrides on top of upstream yym68686/chatgpt base image.

ARG BASE_IMAGE=yym68686/chatgpt@sha256:802678fc950c5769f7c714a505c04b63fdd34b842a39bfd41a2ba60026427647
FROM $BASE_IMAGE

# ── 1. Inject core entrypoints ──
COPY app/bot.py       /home/bot.py
COPY app/config.py    /home/config.py

# ── 2. Inject overrides (match upstream Python import paths) ──
# Each file replaces the corresponding upstream file at its exact path
# so that Python imports (from utils.scripts, aient.models.base, etc.) resolve to ours.
COPY app/overrides/access_control.py     /home/access_control.py
COPY app/overrides/memory_store.py        /home/memory_store.py
COPY app/overrides/role_dialogue_store.py /home/role_dialogue_store.py
COPY app/overrides/decorators_override.py /home/utils/decorators.py
COPY app/overrides/i18n_override.py       /home/i18n_override.py
COPY app/overrides/bot_utils_scripts.py   /home/utils/scripts.py
COPY app/overrides/aient_base.py          /home/aient/aient/models/base.py
COPY app/overrides/aient_chatgpt.py       /home/aient/aient/models/chatgpt.py
COPY app/overrides/aient_run_python.py    /home/aient/aient/plugins/run_python.py
COPY app/overrides/aient_utils_scripts.py /home/aient/aient/utils/scripts.py

# ── 3. Inject persona ──
# systemprompt.md is generated from persona/modules/*.md at build time
COPY persona/modules/           /home/persona/modules/
COPY persona/build_persona_prompt.py /home/persona/build_persona_prompt.py
COPY persona/persona.env        /home/persona.env
COPY persona/start_message.txt  /home/persona_start_message.txt
COPY persona/bot_description.txt /home/persona_bot_description.txt
RUN python3 /home/persona/build_persona_prompt.py 2>/dev/null || \
    echo "No persona modules found; systemprompt.md will be loaded from env"

# ── 4. Inject scripts ──
COPY scripts/healthcheck.py /home/scripts/healthcheck.py

# ── 5. Data dirs (overridden by runtime volumes) ──
RUN mkdir -p /home/memory_data /home/role_data /home/access_data /home/user_configs

# ── 6. Keep non-root ──
USER 10001

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD python /home/scripts/healthcheck.py