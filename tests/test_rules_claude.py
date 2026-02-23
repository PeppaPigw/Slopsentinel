from __future__ import annotations

from helpers import make_file_ctx

from slopsentinel.rules.claude import (
    A01CoAuthoredByClaude,
    A02ClaudeMdExists,
    A03OverlyPoliteComment,
    A04TrivialFunctionVerboseDocstring,
    A05RobustComprehensiveElegantHighFrequency,
    A06ThinkingTagLeak,
    A07TooManyExceptClauses,
    A08SymmetricCreateDeleteUnused,
    A09DefensiveReturnTypeComment,
    A10BannerComment,
    A11NarrativeControlFlowComment,
    A12PlaceholderApologyComment,
)


def test_a01_coauthored_by_claude_triggers(monkeypatch, project_ctx) -> None:
    def fake_git_log(*_args, **_kwargs) -> str:
        return "Fix: stuff\n\nCo-Authored-By: Claude <claude@example.com>\n"

    monkeypatch.setattr("slopsentinel.rules.claude.git_check_output", fake_git_log)
    violations = A01CoAuthoredByClaude().check_project(project_ctx)
    assert any(v.rule_id == "A01" for v in violations)


def test_a01_coauthored_by_claude_no_hit(monkeypatch, project_ctx) -> None:
    def fake_git_log(*_args, **_kwargs) -> str:
        return "Fix: stuff\n\nCo-Authored-By: Human <human@example.com>\n"

    monkeypatch.setattr("slopsentinel.rules.claude.git_check_output", fake_git_log)
    violations = A01CoAuthoredByClaude().check_project(project_ctx)
    assert violations == []


def test_a02_claude_md_exists(project_ctx) -> None:
    (project_ctx.project_root / "CLAUDE.md").write_text("memory\n", encoding="utf-8")
    violations = A02ClaudeMdExists().check_project(project_ctx)
    assert any(v.rule_id == "A02" for v in violations)


def test_a03_overly_polite_comment(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content="# We need to ensure the connection is properly closed\nx = 1\n",
    )
    violations = A03OverlyPoliteComment().check_file(ctx)
    assert any(v.rule_id == "A03" for v in violations)


def test_a03_overly_polite_comment_additional_phrases(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "# As you can see, this is straightforward\n"
            "# Please note that this is best-effort\n"
            "x = 1\n"
        ),
    )
    violations = A03OverlyPoliteComment().check_file(ctx)
    assert any(v.rule_id == "A03" for v in violations)


def test_a03_overly_polite_comment_negative(project_ctx) -> None:
    ctx = make_file_ctx(project_ctx, relpath="src/example.py", content="# Close the connection\nx = 1\n")
    assert A03OverlyPoliteComment().check_file(ctx) == []


def test_a04_verbose_docstring_ratio(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "def trivial():\n"
            '    """\n'
            "    Line 1\n"
            "    Line 2\n"
            "    Line 3\n"
            "    Line 4\n"
            "    Line 5\n"
            "    Line 6\n"
            "    Line 7\n"
            '    """\n'
            "    return 1\n"
        ),
    )
    violations = A04TrivialFunctionVerboseDocstring().check_file(ctx)
    assert any(v.rule_id == "A04" for v in violations)


def test_a05_high_frequency_words(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "# robust robust robust\n"
            "x = 1\n"
        ),
    )
    violations = A05RobustComprehensiveElegantHighFrequency().check_file(ctx)
    assert any(v.rule_id == "A05" for v in violations)


def test_a05_does_not_count_identifiers(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "def robust():\n"
            "    return 1\n\n"
            "robust = 1\n"
            "robust = robust + 1\n"
            "robust = robust + 1\n"
        ),
    )
    assert A05RobustComprehensiveElegantHighFrequency().check_file(ctx) == []


def test_a05_counts_docstrings(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "def f():\n"
            '    """robust robust robust"""\n'
            "    return 1\n"
        ),
    )
    violations = A05RobustComprehensiveElegantHighFrequency().check_file(ctx)
    assert any(v.rule_id == "A05" for v in violations)


def test_a06_thinking_tag_leak(project_ctx) -> None:
    ctx = make_file_ctx(project_ctx, relpath="src/example.py", content="# <thinking>secret</thinking>\nx = 1\n")
    violations = A06ThinkingTagLeak().check_file(ctx)
    assert any(v.rule_id == "A06" for v in violations)


def test_a07_too_many_except_clauses(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "def f():\n"
            "    try:\n"
            "        return 1\n"
            "    except ValueError:\n"
            "        return 1\n"
            "    except TypeError:\n"
            "        return 1\n"
            "    except KeyError:\n"
            "        return 1\n"
            "    except Exception:\n"
            "        return 1\n"
        ),
    )
    violations = A07TooManyExceptClauses().check_file(ctx)
    assert any(v.rule_id == "A07" for v in violations)


def test_a08_symmetric_create_delete_unused(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "def create_user():\n"
            "    return 1\n\n"
            "def delete_user():\n"
            "    return 2\n"
        ),
    )
    violations = A08SymmetricCreateDeleteUnused().check_file(ctx)
    assert any(v.rule_id == "A08" for v in violations)


def test_a08_symmetric_add_remove_unused(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "def add_user():\n"
            "    return 1\n\n"
            "def remove_user():\n"
            "    return 2\n"
        ),
    )
    violations = A08SymmetricCreateDeleteUnused().check_file(ctx)
    assert any(v.rule_id == "A08" for v in violations)


def test_a08_symmetric_insert_drop_unused(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "def insert_row():\n"
            "    return 1\n\n"
            "def drop_row():\n"
            "    return 2\n"
        ),
    )
    violations = A08SymmetricCreateDeleteUnused().check_file(ctx)
    assert any(v.rule_id == "A08" for v in violations)


def test_a08_symmetric_enable_disable_unused(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "def enable_feature():\n"
            "    return 1\n\n"
            "def disable_feature():\n"
            "    return 2\n"
        ),
    )
    violations = A08SymmetricCreateDeleteUnused().check_file(ctx)
    assert any(v.rule_id == "A08" for v in violations)


def test_a08_symmetric_create_delete_negative_when_used(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "def create_user():\n"
            "    return 1\n\n"
            "def delete_user():\n"
            "    return 2\n\n"
            "create_user()\n"
        ),
    )
    assert A08SymmetricCreateDeleteUnused().check_file(ctx) == []


def test_a08_symmetric_create_delete_negative_when_used_as_method(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "class Svc:\n"
            "    def create_user(self):\n"
            "        return 1\n\n"
            "    def delete_user(self):\n"
            "        return 2\n\n"
            "    def run(self):\n"
            "        self.create_user()\n"
        ),
    )
    assert A08SymmetricCreateDeleteUnused().check_file(ctx) == []


def test_a09_at_this_point_comment(project_ctx) -> None:
    ctx = make_file_ctx(project_ctx, relpath="src/example.py", content="# At this point, the result is guaranteed.\n")
    violations = A09DefensiveReturnTypeComment().check_file(ctx)
    assert any(v.rule_id == "A09" for v in violations)


def test_a10_banner_comment(project_ctx) -> None:
    ctx = make_file_ctx(project_ctx, relpath="src/example.py", content="# --------------------------\n")
    violations = A10BannerComment().check_file(ctx)
    assert any(v.rule_id == "A10" for v in violations)


def test_a11_narrative_control_flow_comment(project_ctx) -> None:
    ctx = make_file_ctx(
        project_ctx,
        relpath="src/example.py",
        content=(
            "# First, we do this\n"
            "# Next, we do that\n"
            "# Finally, we finish\n"
            "x = 1\n"
        ),
    )
    violations = A11NarrativeControlFlowComment().check_file(ctx)
    assert any(v.rule_id == "A11" for v in violations)


def test_a12_production_disclaimer_comment(project_ctx) -> None:
    ctx = make_file_ctx(project_ctx, relpath="src/example.py", content="# TODO: In production you would want to handle retries.\n")
    violations = A12PlaceholderApologyComment().check_file(ctx)
    assert any(v.rule_id == "A12" for v in violations)
