"""Policy helpers for tool exposure and per-model compatibility."""

from __future__ import annotations

import fnmatch
import os
from collections.abc import Mapping


# These features are intentionally removed from this bot's public tool set.
# The upstream base image may still contain their implementation, so filtering
# at registration/request time is required to prevent invocation.
# excute_command / list_directory / set_readonly_path expose the container
# filesystem and shell, which this companion bot must never offer to a model.
REMOVED_TOOLS = frozenset({
    "download_read_arxiv_pdf",
    "run_python_script",
    "excute_command",
    "list_directory",
    "set_readonly_path",
})


def _patterns(variable: str) -> tuple[str, ...]:
    return tuple(
        value.strip().casefold()
        for value in os.environ.get(variable, "").split(",")
        if value.strip()
    )


def _matches(name: str, patterns: tuple[str, ...]) -> bool:
    normalized = str(name or "").casefold()
    return any(fnmatch.fnmatchcase(normalized, pattern) for pattern in patterns)


def filter_plugins(plugins: Mapping[str, bool]) -> dict[str, bool]:
    """Return only tool names allowed by TOOL_ALLOWLIST/TOOL_DENYLIST.

    An unset allowlist keeps the upstream tool set for backward compatibility.
    A non-empty allowlist is the recommended production configuration.
    """
    allowlist = _patterns("TOOL_ALLOWLIST")
    denylist = set(_patterns("TOOL_DENYLIST")) | REMOVED_TOOLS
    return {
        name: enabled
        for name, enabled in plugins.items()
        if (not allowlist or _matches(name, allowlist)) and name.casefold() not in denylist
    }


def model_supports_tools(model: str) -> bool:
    """Whether an OpenAI-compatible model may receive a tools schema.

    TOOL_CALL_MODELS is an optional allowlist. TOOL_DISABLED_MODELS always wins.
    Values are comma-separated shell-style patterns, for example ``gpt-4o,*claude*``.
    """
    allowed_models = _patterns("TOOL_CALL_MODELS")
    disabled_models = _patterns("TOOL_DISABLED_MODELS")
    if _matches(model, disabled_models):
        return False
    return not allowed_models or _matches(model, allowed_models)


def model_requires_nonstream_tools(model: str) -> bool:
    """Whether native tool requests must disable HTTP streaming for a model."""
    return _matches(model, _patterns("TOOL_NONSTREAM_MODELS"))


def tools_enabled_for(model: str, plugins: Mapping[str, bool], use_plugins: bool) -> bool:
    return bool(use_plugins and any(plugins.values()) and model_supports_tools(model))
