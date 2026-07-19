# ── Yoishizuku-bot custom image ──
# Layers custom overrides on top of the upstream TeleChat base image.
# No volume mounts needed for code — everything is baked in.

ARG BASE_IMAGE=yym68686/chatgpt@sha256:802678fc950c5769f7c714a505c04b63fdd34b842a39bfd41a2ba60026427647
FROM ${BASE_IMAGE}

WORKDIR /home
USER root

# ── 1. Inject custom overrides for bot.py / config.py ──
COPY app/bot.py       /home/bot.py
COPY app/config.py    /home/config.py

# ── 2. Inject app/overrides/* → /home/*.py (flat, matching import paths) ──
COPY app/overrides/access_control.py      /home/access_control.py
COPY app/overrides/memory_store.py         /home/memory_store.py
COPY app/overrides/role_dialogue_store.py  /home/role_dialogue_store.py
COPY app/overrides/decorators_override.py  /home/decorators_override.py
COPY app/overrides/i18n_override.py        /home/i18n_override.py
COPY app/overrides/bot_utils_scripts.py    /home/bot_utils_scripts.py
COPY app/overrides/aient_base.py           /home/aient_base.py
COPY app/overrides/aient_chatgpt.py        /home/aient_chatgpt.py
COPY app/overrides/aient_run_python.py     /home/aient_run_python.py
COPY app/overrides/aient_utils_scripts.py  /home/aient_utils_scripts.py

# ── 3. Inject persona assets ──
# systemprompt.md is generated from persona/modules/*.md at build time
COPY persona/modules/  /home/persona/modules/
COPY persona/build_persona_prompt.py /home/persona/
COPY persona/persona.env       /home/persona.env
COPY persona/start_message.txt /home/persona_start_message.txt
COPY persona/bot_description.txt /home/persona_bot_description.txt
# Generate systemprompt.md from modules (works even without modules dir)
RUN python3 /home/persona/build_persona_prompt.py 2>/dev/null || echo "No persona modules found; systemprompt.md will be loaded from env"

# ── 4. Inject scripts ──
COPY scripts/healthcheck.py /home/scripts/healthcheck.py

# ── 5. Data directories (must be writable at runtime via volumes) ──
RUN mkdir -p /home/memory_data /home/role_data /home/access_data /home/user_configs

# ── 6. Drop back to non-root (base image user) ──
USER 10001

HEALTHCHECK --start-period=30s --interval=60s --timeout=15s --retries=3 \
  CMD python /home/scripts/healthcheck.py
