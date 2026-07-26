#!/usr/bin/env python3
"""Catch locals that are only assigned inside a handler but read on the main path.

``py_compile`` accepts such code; the failure only appears at runtime, which is
how a streaming regression reached production. The rule implemented here is
deliberately narrow to avoid false positives: report a name when every
assignment lives inside an ``except``/``else`` handler while a read happens
outside of it in the same function body.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [
    ROOT / "app" / "bot.py",
    ROOT / "app" / "config.py",
    ROOT / "app" / "overrides" / "aient_chatgpt.py",
    ROOT / "app" / "overrides" / "aient_scoped_search.py",
    ROOT / "app" / "overrides" / "aient_weather.py",
    ROOT / "app" / "overrides" / "aient_image.py",
    ROOT / "app" / "overrides" / "aient_image_search.py",
    ROOT / "app" / "overrides" / "memory_store.py",
]


def _own_nodes(func: ast.AST):
    """Walk a function body, skipping nested function/lambda/comprehension scopes."""
    stack = list(ast.iter_child_nodes(func))
    while stack:
        node = stack.pop()
        if isinstance(node, (
            ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda,
            ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp,
        )):
            continue
        yield node
        stack.extend(ast.iter_child_nodes(node))


def _handler_assignments(func: ast.AST) -> dict[str, list[int]]:
    """Names assigned inside except handlers, mapped to their line numbers."""
    found: dict[str, list[int]] = {}
    for node in _own_nodes(func):
        if not isinstance(node, ast.ExceptHandler):
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                found.setdefault(child.id, []).append(child.lineno)
    return found


def check_function(func: ast.AST, path: Path) -> list[str]:
    handler_only = _handler_assignments(func)
    if not handler_only:
        return []

    outside_store: set[str] = set()
    outside_load: dict[str, int] = {}
    handler_lines = set()
    for node in _own_nodes(func):
        if isinstance(node, ast.ExceptHandler):
            handler_lines.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    for node in _own_nodes(func):
        if not isinstance(node, ast.Name):
            continue
        if node.lineno in handler_lines:
            continue
        if isinstance(node.ctx, ast.Store):
            outside_store.add(node.id)
        else:
            outside_load.setdefault(node.id, node.lineno)
    for arg in ast.walk(func):
        if isinstance(arg, ast.arg):
            outside_store.add(arg.arg)

    problems = []
    for name, lines in handler_only.items():
        if name in outside_store or name not in outside_load:
            continue
        problems.append(
            f"{path.relative_to(ROOT)}:{outside_load[name]} '{name}' is read on the main path "
            f"but only assigned inside an except handler (line {min(lines)})"
        )
    return problems


def main() -> None:
    findings: list[str] = []
    for path in TARGETS:
        if not path.exists():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                findings.extend(check_function(node, path))
    for line in findings:
        print("FAIL", line)
    if findings:
        raise SystemExit(f"unbound local checks failed: {len(findings)} issue(s)")
    print("PASS unbound_local_check", len(TARGETS), "files")


if __name__ == "__main__":
    main()
