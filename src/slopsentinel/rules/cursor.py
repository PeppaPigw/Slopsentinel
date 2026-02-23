from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from slopsentinel.engine.context import FileContext, ProjectContext
from slopsentinel.engine.types import Location, Violation
from slopsentinel.rules.base import BaseRule, RuleMeta, loc_from_line
from slopsentinel.rules.utils import iter_code_lines, iter_comment_lines

_TODO_TICKET_RE = re.compile(r"\btodo\s*\(\s*#?[a-z0-9][a-z0-9-]*\s*\)\s*:", re.IGNORECASE)
_CONSOLE_LOG_RE = re.compile(r"\bconsole\.log\s*\(")
_EMPTY_INTERFACE_RE = re.compile(
    r"^\s*interface\s+[A-Za-z_$][\w$]*(?:\s+extends\s+[^{]+)?\s*\{\s*\}\s*;?\s*$"
)
_EMPTY_TYPE_RE = re.compile(r"^\s*type\s+[A-Za-z_$][\w$]*\s*=\s*\{\s*\}\s*;?\s*$")
_AS_ANY_RE = re.compile(r"\bas\s+any\b")


def _repo_loc(_: ProjectContext) -> Location:
    return Location(path=None, start_line=None, start_col=None)


@dataclass(frozen=True, slots=True)
class B01CursorRulesExists(BaseRule):
    meta = RuleMeta(
        rule_id="B01",
        title=".cursorrules exists",
        description="Cursor configuration file exists in repository root.",
        default_severity="info",
        score_dimension="fingerprint",
        fingerprint_model="cursor",
    )

    def check_project(self, ctx: ProjectContext) -> list[Violation]:
        if (ctx.project_root / ".cursorrules").exists():
            return [
                self._violation(
                    message="Found `.cursorrules` in repository root.",
                    suggestion="If this repo is not meant to be Cursor-assisted, consider removing it or documenting its usage.",
                    location=_repo_loc(ctx),
                )
            ]
        return []


@dataclass(frozen=True, slots=True)
class B02TodoSpray(BaseRule):
    meta = RuleMeta(
        rule_id="B02",
        title="TODO spray",
        description="Three or more consecutive TODO comments suggests AI scaffolding.",
        default_severity="warn",
        score_dimension="fingerprint",
        fingerprint_model="cursor",
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if any("slop: allow-todo" in line.lower() for line in ctx.lines):
            return []

        todo_run: list[int] = []
        prev_line: int | None = None
        for line_no, line in iter_comment_lines(ctx):
            if prev_line is None or line_no != prev_line + 1:
                todo_run.clear()
            prev_line = line_no

            if "todo" in line.lower():
                if _TODO_TICKET_RE.search(line):
                    todo_run.clear()
                    continue
                todo_run.append(line_no)
                if len(todo_run) >= 3:
                    return [
                        self._violation(
                            message="Found 3+ consecutive TODO comments.",
                            suggestion="Replace TODO blocks with tracked issues or implement the missing pieces.",
                            location=loc_from_line(ctx, line=todo_run[0]),
                        )
                    ]
            else:
                todo_run.clear()
        return []


def _is_js_ts_test_file(ctx: FileContext) -> bool:
    rel = ctx.relative_path.replace("\\", "/").lower()
    name = Path(rel).name

    if rel.startswith("tests/") or "/tests/" in rel or rel.startswith("__tests__/") or "/__tests__/" in rel:
        return True
    if name.startswith("test_"):
        return True
    if any(name.endswith(suffix) for suffix in (".test.js", ".spec.js", ".test.ts", ".spec.ts", ".test.tsx", ".spec.tsx")):
        return True
    return False


@dataclass(frozen=True, slots=True)
class B03ConsoleLogSpray(BaseRule):
    meta = RuleMeta(
        rule_id="B03",
        title="Overuse of console.log",
        description="Frequent console.log calls are often left behind by AI scaffolding or debugging.",
        default_severity="warn",
        score_dimension="quality",
        fingerprint_model="cursor",
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language not in {"javascript", "typescript"}:
            return []
        if _is_js_ts_test_file(ctx):
            return []

        count = 0
        first_line: int | None = None
        for line_no, line in iter_code_lines(ctx):
            if _CONSOLE_LOG_RE.search(line):
                count += 1
                if first_line is None:
                    first_line = line_no

        if count < 5:
            return []

        return [
            self._violation(
                message=f"Found {count} `console.log(...)` calls in one file.",
                suggestion="Remove debug logs or guard them behind a debug flag / logger.",
                location=loc_from_line(ctx, line=first_line or 1),
            )
        ]


_IMPORT_RE = re.compile(r"^\s*import\s+(?P<body>.+?)\s+from\s+['\"][^'\"]+['\"]\s*;?\s*$")
_IMPORT_SIDE_EFFECT_RE = re.compile(r"^\s*import\s+['\"][^'\"]+['\"]\s*;?\s*$")
_IMPORT_DEFAULT_RE = re.compile(r"^(?P<name>[A-Za-z_$][\w$]*)\s*(?:,|$)")
_IMPORT_NAMESPACE_RE = re.compile(r"\*\s+as\s+(?P<name>[A-Za-z_$][\w$]*)")
_IMPORT_NAMED_BLOCK_RE = re.compile(r"\{(?P<inner>[^}]+)\}")
_IMPORT_NAMED_ITEM_RE = re.compile(r"(?P<name>[A-Za-z_$][\w$]*)(?:\s+as\s+(?P<alias>[A-Za-z_$][\w$]*))?")


@dataclass(frozen=True, slots=True)
class B04ImportThenStub(BaseRule):
    meta = RuleMeta(
        rule_id="B04",
        title="Import-then-stub pattern",
        description="Imports appear unused in a file that looks like a stub/scaffold.",
        default_severity="warn",
        score_dimension="fingerprint",
        fingerprint_model="cursor",
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language not in {"javascript", "typescript"}:
            return []

        imported: list[tuple[str, int]] = []
        last_import_line = 0
        for line_no, line in enumerate(ctx.lines, start=1):
            if _IMPORT_SIDE_EFFECT_RE.match(line):
                last_import_line = line_no
                continue
            m = _IMPORT_RE.match(line)
            if not m:
                # Stop scanning imports after the initial contiguous import block.
                lstripped = line.lstrip()
                is_commentish = lstripped.startswith(("//", "/*", "*", "*/"))
                if imported and line.strip() and not is_commentish:
                    break
                continue

            last_import_line = line_no
            body = m.group("body").strip()
            imported.extend((name, line_no) for name in _extract_import_names(body))

        if not imported:
            return []

        rest_text = "\n".join(ctx.lines[last_import_line:])
        stub_markers = ("todo", "not implemented", "throw new error", "stub", "placeholder")
        non_comment_lines = sum(1 for _line_no, _line_text in iter_code_lines(ctx))
        is_stubby = non_comment_lines <= 30 or any(marker in rest_text.lower() for marker in stub_markers)
        if not is_stubby:
            return []

        unused = [(name, line_no) for (name, line_no) in imported if not _word_in_text(name, rest_text)]
        if not unused:
            return []

        # Report the first unused import as a Cursor-style fingerprint signal.
        name, line_no = unused[0]
        return [
            self._violation(
                message=f"Imported identifier `{name}` appears unused in a stub-like file.",
                suggestion="Remove unused imports or finish the implementation so imports are justified.",
                location=loc_from_line(ctx, line=line_no),
            )
        ]


@dataclass(frozen=True, slots=True)
class B05TypeAssertionAbuse(BaseRule):
    meta = RuleMeta(
        rule_id="B05",
        title="Type assertion abuse (as any / as unknown)",
        description="Frequent type assertions can indicate AI-driven typing workarounds.",
        default_severity="warn",
        score_dimension="fingerprint",
        fingerprint_model="cursor",
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "typescript":
            return []

        violations = []
        for line_no, line in enumerate(ctx.lines, start=1):
            if re.search(r"\bas\s+(any|unknown)\b", line):
                violations.append(
                    self._violation(
                        message="Suspicious type assertion (`as any` / `as unknown`).",
                        suggestion="Prefer correct typing; avoid `any` unless unavoidable and documented.",
                        location=loc_from_line(ctx, line=line_no),
                    )
                )
        return violations


@dataclass(frozen=True, slots=True)
class B06EmptyInterfaceOrType(BaseRule):
    meta = RuleMeta(
        rule_id="B06",
        title="Empty interface/type definition",
        description="Empty TypeScript interfaces/types often indicate placeholder scaffolding.",
        default_severity="info",
        score_dimension="quality",
        fingerprint_model="cursor",
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "typescript":
            return []

        for line_no, line in iter_code_lines(ctx):
            if _EMPTY_INTERFACE_RE.match(line) or _EMPTY_TYPE_RE.match(line):
                return [
                    self._violation(
                        message="Found an empty TypeScript interface/type definition (`{}` body).",
                        suggestion="Remove placeholder types or define actual properties/constraints.",
                        location=loc_from_line(ctx, line=line_no),
                    )
                ]
        return []


@dataclass(frozen=True, slots=True)
class B07AsAnyOveruse(BaseRule):
    meta = RuleMeta(
        rule_id="B07",
        title="Overuse of `as any`",
        description="Repeated `as any` assertions often indicate typing workarounds in AI-generated code.",
        default_severity="warn",
        score_dimension="quality",
        fingerprint_model="cursor",
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "typescript":
            return []

        count = 0
        first_line: int | None = None
        for line_no, line in iter_code_lines(ctx):
            if _AS_ANY_RE.search(line):
                count += 1
                if first_line is None:
                    first_line = line_no

        if count < 3:
            return []

        return [
            self._violation(
                message=f"Found {count} occurrences of `as any` in one file.",
                suggestion="Avoid `any` assertions; prefer correct types or narrow types safely.",
                location=loc_from_line(ctx, line=first_line or 1),
            )
        ]


@dataclass(frozen=True, slots=True)
class B08TabCompletionRepeatLines(BaseRule):
    meta = RuleMeta(
        rule_id="B08",
        title="Tab-completion repeated lines",
        description="Three or more consecutive highly-similar lines can be tab-completion artifacts.",
        default_severity="warn",
        score_dimension="fingerprint",
        fingerprint_model="cursor",
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        # Consider consecutive non-empty lines; ignore very short lines.
        candidate_lines: list[tuple[int, str]] = []
        for line_no, line in iter_code_lines(ctx):
            stripped = line.strip()
            if len(stripped) < 20:
                continue
            candidate_lines.append((line_no, stripped))

        for i in range(len(candidate_lines) - 2):
            (l1_no, l1), (_, l2), (_, l3) = candidate_lines[i : i + 3]
            if _similarity(l1, l2) >= 0.7 and _similarity(l2, l3) >= 0.7:
                return [
                    self._violation(
                        message="Found 3 consecutive highly-similar lines (possible tab-completion artifact).",
                        suggestion="Deduplicate or refactor repetitive code (loops, helper function, or data-driven structure).",
                        location=loc_from_line(ctx, line=l1_no),
                    )
                ]
        return []


def builtin_cursor_rules() -> list[BaseRule]:
    return [
        B01CursorRulesExists(),
        B02TodoSpray(),
        B03ConsoleLogSpray(),
        B04ImportThenStub(),
        B05TypeAssertionAbuse(),
        B06EmptyInterfaceOrType(),
        B07AsAnyOveruse(),
        B08TabCompletionRepeatLines(),
    ]


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _word_in_text(word: str, text: str) -> bool:
    return re.search(rf"\b{re.escape(word)}\b", text) is not None


def _extract_import_names(body: str) -> set[str]:
    """
    Extract identifier names from a JS/TS import clause body.

    Supports:
    - Default import: `Foo`
    - Namespace import: `* as Foo`
    - Named imports: `{ A, B as C }`
    """

    names: set[str] = set()

    m_default = _IMPORT_DEFAULT_RE.match(body)
    if m_default:
        names.add(m_default.group("name"))

    m_ns = _IMPORT_NAMESPACE_RE.search(body)
    if m_ns:
        names.add(m_ns.group("name"))

    m_named = _IMPORT_NAMED_BLOCK_RE.search(body)
    if m_named:
        inner = m_named.group("inner")
        for part in inner.split(","):
            part = part.strip()
            if not part:
                continue
            m_item = _IMPORT_NAMED_ITEM_RE.match(part)
            if not m_item:
                continue
            names.add(m_item.group("alias") or m_item.group("name"))

    return names
