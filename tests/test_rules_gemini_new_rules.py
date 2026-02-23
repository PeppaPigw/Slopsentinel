from __future__ import annotations

from helpers import make_file_ctx

from slopsentinel.rules.gemini import D02DebugPrintSpray, D05GlobalKeywordUsed, D06ExecEvalUsed


def test_d02_debug_print_spray(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content="print('a')\nprint('b')\nprint('c')\nprint('d')\nprint('e')\n",
    )
    violations = D02DebugPrintSpray().check_file(ctx)
    assert any(v.rule_id == "D02" for v in violations)


def test_d02_debug_print_spray_skips_test_files(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="tests/test_example.py",
        content="print('a')\nprint('b')\nprint('c')\nprint('d')\nprint('e')\n",
    )
    assert D02DebugPrintSpray().check_file(ctx) == []


def test_d05_global_keyword_used(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content="counter = 0\n\ndef inc() -> None:\n    global counter\n    counter += 1\n",
    )
    violations = D05GlobalKeywordUsed().check_file(ctx)
    assert any(v.rule_id == "D05" for v in violations)


def test_d06_exec_eval_used(project_ctx) -> None:
    ctx = make_file_ctx(project_ctx, relpath="src/example.py", content="result = eval('1 + 1')\n")
    violations = D06ExecEvalUsed().check_file(ctx)
    assert any(v.rule_id == "D06" for v in violations)


def test_d06_exec_eval_used_negative(project_ctx) -> None:
    ctx = make_file_ctx(project_ctx, relpath="src/example.py", content="result = 1 + 1\n")
    assert D06ExecEvalUsed().check_file(ctx) == []

