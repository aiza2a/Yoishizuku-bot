#!/usr/bin/env python3
import ast
import asyncio
import logging
import os
import resource
import tempfile
from pathlib import Path

from .registry import register_tool

DENIED_NAMES = {
    '__import__', 'eval', 'exec', 'compile', 'open', 'input', 'breakpoint',
    'globals', 'locals', 'vars', 'getattr', 'setattr', 'delattr', 'dir',
    'help', 'type', 'object', 'super', 'memoryview',
}
DENIED_NODES = (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal, ast.ClassDef)
MAX_CODE_CHARS = 20000
MAX_OUTPUT_BYTES = 65536
TIMEOUT_SECONDS = 8


def check_code_safety(code):
    if not isinstance(code, str) or not code.strip() or len(code) > MAX_CODE_CHARS:
        return False
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, DENIED_NODES):
            return False
        if isinstance(node, ast.Name):
            if node.id in DENIED_NAMES or node.id.startswith('__'):
                return False
        if isinstance(node, ast.Attribute):
            if node.attr.startswith('_'):
                return False
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in DENIED_NAMES:
                return False
    return True


def _limit_child_resources():
    resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
    resource.setrlimit(resource.RLIMIT_AS, (192 * 1024 * 1024, 192 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _safe_environment():
    return {
        'PATH': '/usr/local/bin:/usr/bin:/bin',
        'HOME': '/tmp',
        'TMPDIR': '/tmp',
        'LANG': 'C.UTF-8',
        'LC_ALL': 'C.UTF-8',
        'PYTHONNOUSERSITE': '1',
        'PYTHONDONTWRITEBYTECODE': '1',
    }


def _wrapper_source(code):
    return f'''import ast

SAFE_BUILTINS = {{
    "abs": abs, "all": all, "any": any, "bool": bool, "dict": dict,
    "enumerate": enumerate, "filter": filter, "float": float, "int": int,
    "len": len, "list": list, "map": map, "max": max, "min": min,
    "pow": pow, "print": print, "range": range, "reversed": reversed,
    "round": round, "set": set, "sorted": sorted, "str": str,
    "sum": sum, "tuple": tuple, "zip": zip,
    "Exception": Exception, "ValueError": ValueError, "TypeError": TypeError,
    "ZeroDivisionError": ZeroDivisionError,
}}
source = {code!r}
tree = ast.parse(source)
if tree.body and isinstance(tree.body[-1], ast.Expr):
    tree.body[-1] = ast.Assign(
        targets=[ast.Name(id="_last_expr", ctx=ast.Store())],
        value=tree.body[-1].value,
    )
    ast.fix_missing_locations(tree)
namespace = {{"__builtins__": SAFE_BUILTINS}}
exec(compile(tree, "<user-code>", "exec"), namespace, namespace)
if "_last_expr" in namespace and namespace["_last_expr"] is not None:
    print("Result:", repr(namespace["_last_expr"]))
'''


@register_tool()
async def run_python_script(code):
    """执行不含导入、文件、系统、网络或反射能力的轻量 Python 计算。"""
    if not check_code_safety(code):
        return 'Code contains unsupported or unsafe operations.\n'

    script_fd, script_name = tempfile.mkstemp(prefix='gptbot-python-', suffix='.py', dir='/tmp')
    output_fd, output_name = tempfile.mkstemp(prefix='gptbot-python-', suffix='.out', dir='/tmp')
    try:
        with os.fdopen(script_fd, 'w', encoding='utf-8') as handle:
            handle.write(_wrapper_source(code))
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(script_name, 0o600)

        with os.fdopen(output_fd, 'w+b', buffering=0) as output:
            process = await asyncio.create_subprocess_exec(
                'python', '-I', '-S', script_name,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=output,
                stderr=asyncio.subprocess.STDOUT,
                cwd='/tmp',
                env=_safe_environment(),
                preexec_fn=_limit_child_resources,
            )
            try:
                await asyncio.wait_for(process.wait(), timeout=TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return 'Process execution timed out.\n'
            output.seek(0)
            raw = output.read(MAX_OUTPUT_BYTES + 1)

        truncated = len(raw) > MAX_OUTPUT_BYTES
        text = raw[:MAX_OUTPUT_BYTES].decode('utf-8', errors='replace')
        if truncated:
            text += '\n[output truncated]'
        if process.returncode == 0:
            return f'Execution result:\n{text}\n'
        return f'Execution failed (code {process.returncode}):\n{text}\n'
    except Exception as exc:
        logging.exception('Sandboxed Python execution failed')
        return f'<tool_error>Error: {type(exc).__name__}</tool_error>'
    finally:
        Path(script_name).unlink(missing_ok=True)
        Path(output_name).unlink(missing_ok=True)
