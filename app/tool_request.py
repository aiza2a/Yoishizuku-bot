"""Compatibility patch for OpenAI-compatible Grok tool calls.

The pinned uni-api-core version removes ``tools`` and ``tool_choice`` for every
model whose name contains ``grok``.  Modern Grok-compatible gateways can
support this OpenAI schema, so restore the fields only for models explicitly
listed in TOOL_CALL_MODELS.
"""

from __future__ import annotations

import copy
import os

from aient.aient.core.request import prepare_request_payload as _prepare_request_payload

try:
    from tool_policy import model_supports_tools
except ImportError:
    from app.tool_policy import model_supports_tools


def _has_explicit_tool_model_allowlist() -> bool:
    return any(value.strip() for value in os.environ.get("TOOL_CALL_MODELS", "").split(","))


async def prepare_request_payload(provider: dict, request_data: dict):
    """Prepare an upstream request and restore explicit Grok tool schemas."""
    url, headers, payload, engine = await _prepare_request_payload(provider, request_data)

    model = str(request_data.get("model") or "")
    requested_tools = request_data.get("tools")
    if not (
        engine == "gpt"
        and "grok" in model.casefold()
        and provider.get("tools")
        and requested_tools
        and _has_explicit_tool_model_allowlist()
        and model_supports_tools(model)
    ):
        return url, headers, payload, engine

    # uni-api-core strips this OpenAI-compatible schema for all Grok model
    # names. TOOL_CALL_MODELS is an explicit operator opt-in for restoring it.
    payload["tools"] = copy.deepcopy(requested_tools)
    if "tool_choice" in request_data:
        payload["tool_choice"] = copy.deepcopy(request_data["tool_choice"])
    return url, headers, payload, engine
