#!/usr/bin/env python3
"""Regression checks for tool exposure and model compatibility policy."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.tool_policy import (
    REMOVED_TOOLS,
    filter_plugins,
    model_requires_nonstream_tools,
    model_supports_tools,
    tools_enabled_for,
)

POLICY_VARIABLES = (
    "TOOL_ALLOWLIST",
    "TOOL_DENYLIST",
    "TOOL_CALL_MODELS",
    "TOOL_DISABLED_MODELS",
    "TOOL_NONSTREAM_MODELS",
)


def set_policy(**values: str) -> None:
    for name in POLICY_VARIABLES:
        if name in values:
            os.environ[name] = values[name]
        else:
            os.environ.pop(name, None)


def check(name: str, condition: bool) -> None:
    print(("PASS" if condition else "FAIL"), name)
    if not condition:
        raise SystemExit(f"tool policy check failed: {name}")


def main() -> None:
    previous = {name: os.environ.get(name) for name in POLICY_VARIABLES}
    plugins = {
        "download_read_arxiv_pdf": True,
        "run_python_script": True,
        "get_search_results": True,
        "get_url_content": False,
    }
    try:
        set_policy()
        check("removed_tools_are_fixed", REMOVED_TOOLS == {
            "download_read_arxiv_pdf",
            "run_python_script",
            "excute_command",
            "list_directory",
            "set_readonly_path",
        })
        check("removed_tools_are_hidden", filter_plugins(plugins) == {
            "get_search_results": True, "get_url_content": False
        })

        set_policy(TOOL_ALLOWLIST="get_search_results,run_python_script")
        check("allowlist_cannot_restore_removed_tool", filter_plugins(plugins) == {
            "get_search_results": True
        })
        set_policy(TOOL_ALLOWLIST="excute_command,list_directory,set_readonly_path")
        check("allowlist_cannot_restore_shell_tools", filter_plugins({
            "excute_command": True, "list_directory": True, "set_readonly_path": True
        }) == {})

        set_policy(
            TOOL_CALL_MODELS="gpt-4o,claude-*",
            TOOL_DISABLED_MODELS="claude-legacy*",
            TOOL_NONSTREAM_MODELS="grok-4.20-fast",
        )
        check("allowed_model_has_tools", model_supports_tools("gpt-4o"))
        check("unlisted_model_has_no_tools", not model_supports_tools("deepseek-v4-flash-free"))
        check("denylist_overrides_model_allowlist", not model_supports_tools("claude-legacy-3"))
        check("nonstream_tool_model", model_requires_nonstream_tools("grok-4.20-fast"))
        check("other_models_keep_streaming", not model_requires_nonstream_tools("gpt-4o"))
        check("tools_need_enabled_plugin", not tools_enabled_for("gpt-4o", {"get_time": False}, True))
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


if __name__ == "__main__":
    main()
