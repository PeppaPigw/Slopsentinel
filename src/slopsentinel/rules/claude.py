from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from slopsentinel.engine.context import FileContext, ProjectContext
from slopsentinel.engine.types import Location, Violation
from slopsentinel.git import GitError, git_check_output
from slopsentinel.patterns import BANNER_RE, POLITE_RE, THINKING_RE
from slopsentinel.rules.base import BaseRule, RuleMeta, loc_from_line
from slopsentinel.rules.utils import iter_comment_lines, normalize_words

_DEFENSIVE_RE = re.compile(r"\bat this point\b", re.IGNORECASE)
_ROBUST_WORDS = ("robust", "comprehensive", "elegant")
_NARRATIVE_WORDS = ("first", "next", "finally")
_APOLOGY_RE = re.compile(r"(simplified.*production|in production.*would|todo:.*production)", re.IGNORECASE)


def _repo_loc(ctx: ProjectContext) -> Location:
    # Repo-level signals don't have a stable file location.
    return Location(path=None, start_line=None, start_col=None)


@dataclass(frozen=True, slots=True)
class A01CoAuthoredByClaude(BaseRule):
    meta = RuleMeta(
        rule_id="A01",
        title="Co-Authored-By: Claude trailer",
        description="Git trailer indicates Claude-assisted commits.",
        default_severity="info",
        score_dimension="fingerprint",
        fingerprint_model="claude",
    )

    def check_project(self, ctx: ProjectContext) -> list[Violation]:
        try:
            out = git_check_output(["log", "-n", "50", "--pretty=%B"], cwd=ctx.project_root)
        except GitError:
            return []

        if "Co-Authored-By: Claude" not in out and "Co-authored-by: Claude" not in out:
            return []

        return [
            self._violation(
                message="Found `Co-Authored-By: Claude` in git history.",
                suggestion="Review recent PRs for AI slop patterns; consider requiring human review for AI-assisted commits.",
                location=_repo_loc(ctx),
            )
        ]


@dataclass(frozen=True, slots=True)
class A02ClaudeMdExists(BaseRule):
    meta = RuleMeta(
        rule_id="A02",
        title="CLAUDE.md exists",
        description="Project contains a CLAUDE.md memory file.",
        default_severity="info",
        score_dimension="fingerprint",
        fingerprint_model="claude",
    )

    def check_project(self, ctx: ProjectContext) -> list[Violation]:
        if (ctx.project_root / "CLAUDE.md").exists():
            return [
                self._violation(
                    message="Found `CLAUDE.md` in repository root.",
                    suggestion="If this repo is not meant to be AI-assisted, consider removing or documenting its purpose.",
                    location=_repo_loc(ctx),
                )
            ]
        return []


@dataclass(frozen=True, slots=True)
class A03OverlyPoliteComment(BaseRule):
    meta = RuleMeta(
        rule_id="A03",
        title="Overly polite comment",
        description="Narrative/polite phrasing often appears in AI-generated comments.",
        default_severity="warn",
        score_dimension="fingerprint",
        fingerprint_model="claude",
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        violations = []
        for line_no, line in iter_comment_lines(ctx):
            if not POLITE_RE.search(line):
                continue
            violations.append(
                self._violation(
                    message="Overly polite/narrative comment detected.",
                    suggestion="Rewrite as a concise, factual comment (or remove if redundant).",
                    location=loc_from_line(ctx, line=line_no),
                )
            )
        return violations


@dataclass(frozen=True, slots=True)
class A04TrivialFunctionVerboseDocstring(BaseRule):
    meta = RuleMeta(
        rule_id="A04",
        title="Trivial function with verbose docstring",
        description="Docstring significantly larger than implementation (docstring_lines > 3× code_lines).",
        default_severity="warn",
        score_dimension="fingerprint",
        fingerprint_model="claude",
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "python" or ctx.python_ast is None:
            return []

        import ast

        violations = []
        lines = ctx.lines

        for node in ast.walk(ctx.python_ast):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if not node.body:
                continue
            first = node.body[0]
            if not (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
                and hasattr(first, "lineno")
                and hasattr(first, "end_lineno")
            ):
                continue

            doc_start = int(getattr(first, "lineno", 0) or 0)
            doc_end = int(getattr(first, "end_lineno", doc_start) or doc_start)
            if doc_start <= 0 or doc_end <= 0:
                continue

            func_end = int(getattr(node, "end_lineno", doc_end) or doc_end)
            func_start = int(getattr(node, "lineno", doc_start) or doc_start)
            if func_end <= 0 or func_start <= 0 or func_end < func_start:
                continue

            doc_lines = lines[doc_start - 1 : doc_end]
            doc_line_count = sum(1 for line_text in doc_lines if line_text.strip())

            body_lines = lines[doc_end:func_end]
            code_line_count = sum(
                1 for line_text in body_lines if line_text.strip() and not line_text.lstrip().startswith("#")
            )

            if code_line_count <= 0:
                continue

            # "Trivial" guard to reduce noise: only flag small functions.
            if code_line_count > 20:
                continue

            if doc_line_count > 3 * code_line_count:
                violations.append(
                    self._violation(
                        message=f"Docstring is very large for a trivial function ({doc_line_count} doc lines vs {code_line_count} code lines).",
                        suggestion="Trim the docstring to essentials or move detailed docs to higher-level documentation.",
                        location=loc_from_line(ctx, line=doc_start),
                    )
                )

        return violations


@dataclass(frozen=True, slots=True)
class A05RobustComprehensiveElegantHighFrequency(BaseRule):
    meta = RuleMeta(
        rule_id="A05",
        title="High-frequency 'robust/comprehensive/elegant'",
        description="Certain adjectives frequently appear in AI-written prose within code comments/docstrings.",
        default_severity="warn",
        score_dimension="fingerprint",
        fingerprint_model="claude",
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        haystack_parts: list[str] = [line for _line_no, line in iter_comment_lines(ctx)]

        if ctx.language == "python" and ctx.python_ast is not None:
            import ast

            if isinstance(ctx.python_ast, ast.Module):
                module_doc = ast.get_docstring(ctx.python_ast, clean=False)
                if module_doc:
                    haystack_parts.append(module_doc)

            for node in ast.walk(ctx.python_ast):
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                    doc = ast.get_docstring(node, clean=False)
                    if doc:
                        haystack_parts.append(doc)

        words = normalize_words("\n".join(haystack_parts))
        if not words:
            return []

        counts = {w: 0 for w in _ROBUST_WORDS}
        for w in words:
            if w in counts:
                counts[w] += 1

        violations = []
        for w, c in counts.items():
            if c >= 3:
                line_no = _first_line_containing(ctx.lines, w)
                violations.append(
                    self._violation(
                        message=f"High frequency of '{w}' ({c} occurrences).",
                        suggestion="Reduce subjective adjectives in comments; prefer concrete, verifiable statements.",
                        location=loc_from_line(ctx, line=line_no) if line_no is not None else None,
                    )
                )
        return violations


@dataclass(frozen=True, slots=True)
class A06ThinkingTagLeak(BaseRule):
    meta = RuleMeta(
        rule_id="A06",
        title="<thinking> tag leak",
        description="Leaked chain-of-thought tags sometimes appear in AI-generated output.",
        default_severity="error",
        score_dimension="fingerprint",
        fingerprint_model="claude",
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        violations = []
        for line_no, line in enumerate(ctx.lines, start=1):
            if THINKING_RE.search(line):
                violations.append(
                    self._violation(
                        message="Found leaked `<thinking>` tag.",
                        suggestion="Remove the tag content from source control.",
                        location=loc_from_line(ctx, line=line_no),
                    )
                )
        return violations


@dataclass(frozen=True, slots=True)
class A07TooManyExceptClauses(BaseRule):
    meta = RuleMeta(
        rule_id="A07",
        title="Over-structured exception handling",
        description="Try blocks with too many except handlers often indicate over-engineered AI output.",
        default_severity="warn",
        score_dimension="fingerprint",
        fingerprint_model="claude",
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "python" or ctx.python_ast is None:
            return []

        import ast

        violations = []
        for node in ast.walk(ctx.python_ast):
            if isinstance(node, ast.Try) and len(node.handlers) > 3 and hasattr(node, "lineno"):
                violations.append(
                    self._violation(
                        message=f"Try statement has {len(node.handlers)} except handlers.",
                        suggestion="Collapse similar handlers and keep exception handling minimal and precise.",
                        location=loc_from_line(ctx, line=int(node.lineno)),
                    )
                )
        return violations


@dataclass(frozen=True, slots=True)
class A08SymmetricCreateDeleteUnused(BaseRule):
    meta = RuleMeta(
        rule_id="A08",
        title="Symmetric create/delete pair unused",
        description="AI often generates symmetric API pairs even when unused.",
        default_severity="warn",
        score_dimension="fingerprint",
        fingerprint_model="claude",
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "python" or ctx.python_ast is None:
            return []

        import ast

        defined: dict[str, int] = {}
        for node in ast.walk(ctx.python_ast):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                defined[node.name] = int(getattr(node, "lineno", 1))

        if not defined:
            return []

        used_names: set[str] = set()
        for node in ast.walk(ctx.python_ast):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    used_names.add(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    used_names.add(node.func.attr)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                used_names.add(node.id)
            elif isinstance(node, ast.Attribute):
                used_names.add(node.attr)

        def _pair(name: str) -> tuple[str, str] | None:
            if name.startswith("create_"):
                return name, "delete_" + name.removeprefix("create_")
            if name.startswith("add_"):
                return name, "remove_" + name.removeprefix("add_")
            if name.startswith("insert_"):
                return name, "drop_" + name.removeprefix("insert_")
            if name.startswith("enable_"):
                return name, "disable_" + name.removeprefix("enable_")
            return None

        violations = []
        for name in list(defined):
            pair = _pair(name)
            if pair is None:
                continue
            a, b = pair
            if b not in defined:
                continue
            if a in used_names or b in used_names:
                continue
            line_no = min(defined[a], defined[b])
            violations.append(
                self._violation(
                    message=f"Found symmetric function pair `{a}`/`{b}` with no in-file calls.",
                    suggestion="Remove unused symmetry or add tests/usages that justify both functions.",
                    location=loc_from_line(ctx, line=line_no),
                )
            )
        return violations


@dataclass(frozen=True, slots=True)
class A09DefensiveReturnTypeComment(BaseRule):
    meta = RuleMeta(
        rule_id="A09",
        title="Defensive 'at this point' comment",
        description="AI often adds defensive 'at this point' narrative comments.",
        default_severity="info",
        score_dimension="fingerprint",
        fingerprint_model="claude",
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        violations = []
        for line_no, line in iter_comment_lines(ctx):
            if _DEFENSIVE_RE.search(line):
                violations.append(
                    self._violation(
                        message="Defensive narrative comment detected ('at this point').",
                        suggestion="Remove or rewrite as a concrete invariant only if it adds value.",
                        location=loc_from_line(ctx, line=line_no),
                    )
                )
        return violations


@dataclass(frozen=True, slots=True)
class A10BannerComment(BaseRule):
    meta = RuleMeta(
        rule_id="A10",
        title="Banner/separator comment",
        description="Large banner separators are a common AI stylistic artifact.",
        default_severity="warn",
        score_dimension="fingerprint",
        fingerprint_model="claude",
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        violations = []
        for line_no, line in enumerate(ctx.lines, start=1):
            if BANNER_RE.match(line):
                violations.append(
                    self._violation(
                        message="Banner/separator comment detected.",
                        suggestion="Prefer minimal sectioning; remove banners unless they carry meaning.",
                        location=loc_from_line(ctx, line=line_no),
                    )
                )
        return violations


@dataclass(frozen=True, slots=True)
class A11NarrativeControlFlowComment(BaseRule):
    meta = RuleMeta(
        rule_id="A11",
        title="Narrative control-flow comment",
        description="Comments like 'First/Next/Finally' are common in AI explanations.",
        default_severity="warn",
        score_dimension="fingerprint",
        fingerprint_model="claude",
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        # Look for a nearby sequence of First -> Next -> Finally in comment lines.
        hits: dict[str, list[int]] = {w: [] for w in _NARRATIVE_WORDS}
        for line_no, line in iter_comment_lines(ctx):
            lowered = line.lower()
            for w in _NARRATIVE_WORDS:
                if re.search(rf"\b{re.escape(w)}\b", lowered):
                    hits[w].append(line_no)

        if not hits["first"] or not hits["next"] or not hits["finally"]:
            return []

        # Find the earliest ordered triple within a window.
        for first_line in hits["first"]:
            next_candidates = [n for n in hits["next"] if first_line < n <= first_line + 50]
            if not next_candidates:
                continue
            for next_line in next_candidates:
                finally_candidates = [f for f in hits["finally"] if next_line < f <= first_line + 50]
                if finally_candidates:
                    return [
                        self._violation(
                            message="Narrative control-flow comments detected (First/Next/Finally).",
                            suggestion="Replace with concise comments only where logic is non-obvious.",
                            location=loc_from_line(ctx, line=first_line),
                        )
                    ]
        return []


@dataclass(frozen=True, slots=True)
class A12PlaceholderApologyComment(BaseRule):
    meta = RuleMeta(
        rule_id="A12",
        title="Placeholder apology/prod disclaimer",
        description="AI often includes 'in production...' disclaimers and apologies.",
        default_severity="warn",
        score_dimension="fingerprint",
        fingerprint_model="claude",
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        violations = []
        for line_no, line in iter_comment_lines(ctx):
            if _APOLOGY_RE.search(line):
                violations.append(
                    self._violation(
                        message="Placeholder 'in production' disclaimer detected.",
                        suggestion="Replace with an actionable TODO linked to an issue, or implement the missing behavior.",
                        location=loc_from_line(ctx, line=line_no),
                    )
                )
        return violations


def builtin_claude_rules() -> list[BaseRule]:
    return [
        A01CoAuthoredByClaude(),
        A02ClaudeMdExists(),
        A03OverlyPoliteComment(),
        A04TrivialFunctionVerboseDocstring(),
        A05RobustComprehensiveElegantHighFrequency(),
        A06ThinkingTagLeak(),
        A07TooManyExceptClauses(),
        A08SymmetricCreateDeleteUnused(),
        A09DefensiveReturnTypeComment(),
        A10BannerComment(),
        A11NarrativeControlFlowComment(),
        A12PlaceholderApologyComment(),
    ]


def _first_line_containing(lines: Sequence[str], needle: str) -> int | None:
    for idx, line in enumerate(lines, start=1):
        if needle.lower() in line.lower():
            return idx
    return None
