from __future__ import annotations

import difflib
import io
import re
import tokenize
from dataclasses import dataclass
from pathlib import Path

from slopsentinel.audit import AuditResult, audit_path
from slopsentinel.engine.types import Violation
from slopsentinel.languages.registry import detect_language
from slopsentinel.patterns import (
    BANNER_RE,
    COMPREHENSIVE_RE,
    LAST_UPDATE_RE,
    POLITE_RE,
    THINKING_RE,
)

_FIXABLE_RULE_IDS = frozenset(
    {
        "A03",  # Overly polite/narrative comment
        "A04",  # Trivial function with verbose docstring (trim boilerplate sections)
        "A06",  # <thinking> tag leak
        "A10",  # Banner/separator comment
        "C09",  # Training cutoff reference
        "D01",  # "Here's a comprehensive..." preamble
        "E03",  # Unused imports (very conservative)
        "E04",  # except: pass -> raise (very conservative)
        "E06",  # repeated string literal -> extract constant (very conservative)
        "E09",  # Hard-coded credential -> environment variable lookup (very conservative)
        "E11",  # redundant boolean return -> simplify (very conservative)
    }
)


@dataclass(frozen=True, slots=True)
class LineRemoval:
    """
    A conservative edit that deletes a contiguous range of lines (1-based, inclusive).
    """

    rule_ids: tuple[str, ...]
    start_line: int
    end_line: int


@dataclass(frozen=True, slots=True)
class LineReplacement:
    """
    A conservative edit that replaces a single line (1-based) with new content.
    """

    rule_ids: tuple[str, ...]
    line: int
    content: str


@dataclass(frozen=True, slots=True)
class AutoFixFileResult:
    path: Path
    changed: bool
    diff: str
    removals: tuple[LineRemoval, ...]
    replacements: tuple[LineReplacement, ...]


@dataclass(frozen=True, slots=True)
class AutoFixResult:
    scan_path: Path
    project_root: Path
    changed_files: tuple[Path, ...]
    file_results: tuple[AutoFixFileResult, ...]

    @property
    def diff(self) -> str:
        chunks = [fr.diff for fr in self.file_results if fr.diff]
        return "\n".join(chunks)


def supported_rule_ids() -> frozenset[str]:
    return _FIXABLE_RULE_IDS


def autofix_path(scan_path: Path, *, dry_run: bool, backup: bool) -> AutoFixResult:
    audit = audit_path(scan_path, record_history=False)
    return autofix_audit_result(audit, dry_run=dry_run, backup=backup)


def autofix_audit_result(audit: AuditResult, *, dry_run: bool, backup: bool) -> AutoFixResult:
    fixable = _fixable_violations(audit.summary.violations)
    by_path: dict[Path, list[Violation]] = {}
    for v in fixable:
        if v.location is None or v.location.path is None:
            continue
        by_path.setdefault(Path(v.location.path), []).append(v)

    file_results: list[AutoFixFileResult] = []
    changed: list[Path] = []
    for file_path in sorted(by_path):
        res = _autofix_file(file_path, by_path[file_path], dry_run=dry_run, backup=backup)
        file_results.append(res)
        if res.changed:
            changed.append(file_path)

    return AutoFixResult(
        scan_path=audit.target.scan_path,
        project_root=audit.target.project_root,
        changed_files=tuple(changed),
        file_results=tuple(file_results),
    )


def _fixable_violations(violations: tuple[Violation, ...]) -> list[Violation]:
    out: list[Violation] = []
    for v in violations:
        if v.rule_id not in _FIXABLE_RULE_IDS:
            continue
        if v.location is None or v.location.path is None or v.location.start_line is None:
            continue
        out.append(v)
    return out


@dataclass(frozen=True, slots=True)
class _CommentMask:
    # 1-based indexing; element 0 is a dummy.
    is_comment: tuple[bool, ...]
    in_block_comment: tuple[bool, ...]


def _autofix_file(path: Path, violations: list[Violation], *, dry_run: bool, backup: bool) -> AutoFixFileResult:
    original = path.read_text(encoding="utf-8", errors="replace")
    updated, removals, replacements = _apply_fixes_to_text(path=path, text=original, violations=violations)

    diff = _unified_diff(original, updated, path=path)
    changed = original != updated

    if changed and not dry_run:
        if backup:
            backup_path = path.with_suffix(path.suffix + ".slopsentinel.bak")
            if not backup_path.exists():
                backup_path.write_text(original, encoding="utf-8")
        path.write_text(updated, encoding="utf-8")

    return AutoFixFileResult(path=path, changed=changed, diff=diff, removals=removals, replacements=replacements)


def apply_fixes(path: Path, text: str, violations: list[Violation]) -> str:
    """
    Apply conservative, rule-driven fixes to `text` and return the updated content.

    This is used by integrations (e.g. LSP code actions) that want to apply the
    same safe transformations without writing to disk.
    """

    updated, _removals, _replacements = _apply_fixes_to_text(path=path, text=text, violations=violations)
    return updated


def _apply_fixes_to_text(
    *,
    path: Path,
    text: str,
    violations: list[Violation],
) -> tuple[str, tuple[LineRemoval, ...], tuple[LineReplacement, ...]]:
    lines = text.splitlines(keepends=True)

    language = detect_language(path) or ""
    comment_mask = _build_comment_mask(language, text, lines)

    removals = _plan_removals(lines, comment_mask, violations, language=language)
    replacements = _plan_replacements(lines, comment_mask, violations, language=language)
    to_remove = _flatten_removals(removals)
    replacement_map = {r.line: r.content for r in replacements}

    updated_lines: list[str] = []
    for idx, line in enumerate(lines, start=1):
        if idx in to_remove:
            continue
        replacement = replacement_map.get(idx)
        updated_lines.append(replacement if replacement is not None else line)
    updated = "".join(updated_lines)
    return updated, removals, replacements


def _build_comment_mask(language: str, source: str, lines: list[str]) -> _CommentMask:
    # Prefer language-aware parsing when feasible; fall back to the same
    # lightweight heuristics used by the rules engine.
    if language == "python":
        comment_lines = _python_comment_lines(source)
        is_comment = [False] * (len(lines) + 1)
        in_block_comment = [False] * (len(lines) + 1)
        for idx, line in enumerate(lines, start=1):
            if idx in comment_lines and line.lstrip().startswith("#"):
                is_comment[idx] = True
        return _CommentMask(is_comment=tuple(is_comment), in_block_comment=tuple(in_block_comment))

    is_comment = [False] * (len(lines) + 1)
    in_block_comment = [False] * (len(lines) + 1)

    in_block = False
    for idx, line in enumerate(lines, start=1):
        stripped = line.lstrip()
        if in_block:
            is_comment[idx] = True
            in_block_comment[idx] = True
            if "*/" in stripped:
                in_block = False
            continue

        if stripped.startswith("//"):
            is_comment[idx] = True
            continue

        if stripped.startswith("/*"):
            is_comment[idx] = True
            in_block_comment[idx] = True
            if "*/" not in stripped:
                in_block = True
            continue

    return _CommentMask(is_comment=tuple(is_comment), in_block_comment=tuple(in_block_comment))


def _python_comment_lines(source: str) -> set[int]:
    """
    Return the set of 1-based line numbers containing Python `# ...` comments.

    Tokenization avoids treating docstrings / multiline strings as comments,
    which keeps auto-fixes conservative.
    """

    out: set[int] = set()
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for tok in tokens:
            if tok.type == tokenize.COMMENT:
                out.add(tok.start[0])
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # Fall back to a conservative empty set.
        return set()
    return out


_A04_REMOVE_SECTIONS = frozenset({"args", "arguments", "parameters", "returns", "raises"})
_A04_GOOGLE_STYLE_SECTIONS = frozenset(
    {
        "args",
        "arguments",
        "parameters",
        "returns",
        "raises",
        "note",
        "notes",
        "warning",
        "warnings",
        "example",
        "examples",
    }
)
_A04_NUMPY_UNDERLINE_RE = re.compile(r"^[-=]{3,}\s*$")
_A04_NUMPY_HEADER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 ]*$")


def _python_a04_docstring_section_removals(lines: list[str], violations: list[Violation]) -> list[LineRemoval]:
    """
    Plan a conservative A04 auto-fix by deleting boilerplate docstring sections.

    Behavior (intentionally narrow):
    - Only trims docstrings of functions explicitly flagged with an A04 violation.
    - Removes full-line Numpy/Google-style sections named Parameters/Returns/Raises.
    - Preserves all other content (including Notes/Warning/Example sections).
    - Never deletes the opening/closing quote lines (to avoid breaking syntax).
    """

    a04_lines: set[int] = set()
    for v in violations:
        if v.rule_id != "A04" or v.location is None or v.location.start_line is None:
            continue
        line_no = int(v.location.start_line)
        if line_no > 0:
            a04_lines.add(line_no)

    if not a04_lines:
        return []

    source = "".join(lines)
    try:
        import ast

        tree = ast.parse(source)
    except SyntaxError:
        return []

    def docstring_span(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[int, int] | None:
        if not node.body:
            return None
        first = node.body[0]
        if not isinstance(first, ast.Expr):
            return None
        val = getattr(first, "value", None)
        if not (isinstance(val, ast.Constant) and isinstance(val.value, str)):
            return None
        start = int(getattr(first, "lineno", 0) or 0)
        end = int(getattr(first, "end_lineno", start) or start)
        if start <= 0 or end <= 0 or end < start:
            return None
        return start, end

    def indent_for_line(line: str) -> str:
        return line[: len(line) - len(line.lstrip())]

    def strip_base_indent(line: str, *, base_indent: str) -> str:
        if line.startswith(base_indent):
            return line[len(base_indent) :]
        return line.lstrip()

    def numpy_section_name(doc_lines: list[str], idx: int, *, base_indent: str) -> str | None:
        if idx < 0 or idx + 1 >= len(doc_lines):
            return None
        line = doc_lines[idx]
        if not line.startswith(base_indent):
            return None
        if '"""' in line or "'''" in line:
            return None
        header_src = strip_base_indent(line, base_indent=base_indent)
        if header_src.startswith((" ", "\t")):
            return None
        header = header_src.strip()
        if not header or not _A04_NUMPY_HEADER_RE.match(header):
            return None
        next_line = doc_lines[idx + 1]
        if not next_line.startswith(base_indent):
            return None
        underline_src = strip_base_indent(next_line, base_indent=base_indent)
        if underline_src.startswith((" ", "\t")):
            return None
        underline = underline_src.strip()
        if not _A04_NUMPY_UNDERLINE_RE.match(underline):
            return None
        return header

    def google_section_name(doc_lines: list[str], idx: int, *, base_indent: str) -> str | None:
        if idx < 0 or idx >= len(doc_lines):
            return None
        line = doc_lines[idx]
        if not line.startswith(base_indent):
            return None
        if '"""' in line or "'''" in line:
            return None
        header_src = strip_base_indent(line, base_indent=base_indent)
        if header_src.startswith((" ", "\t")):
            return None
        header = header_src.strip()
        if not header.endswith(":"):
            return None
        name = header[:-1].strip()
        if not name:
            return None
        lowered = name.lower()
        if lowered not in _A04_GOOGLE_STYLE_SECTIONS:
            return None
        return name

    removals: list[LineRemoval] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        span = docstring_span(node)
        if span is None:
            continue
        doc_start, doc_end = span
        if doc_start not in a04_lines:
            continue
        if doc_start <= 0 or doc_end > len(lines):
            continue

        doc_lines = lines[doc_start - 1 : doc_end]
        if not doc_lines:
            continue

        base_indent = indent_for_line(doc_lines[0])

        # Identify a safe "body end" for deletions: the last line containing a
        # triple-quote is assumed to be (or contain) the closing quotes. Never
        # delete that line via a whole-line removal.
        closing_rel = -1
        for rel_idx, text in enumerate(doc_lines):
            if '"""' in text or "'''" in text:
                closing_rel = rel_idx
        if closing_rel <= 0:
            continue

        section_starts: list[tuple[int, str]] = []
        for rel_idx in range(len(doc_lines) - 1):
            name = numpy_section_name(doc_lines, rel_idx, base_indent=base_indent)
            if name is not None:
                section_starts.append((rel_idx, name))
                continue
            gname = google_section_name(doc_lines, rel_idx, base_indent=base_indent)
            if gname is not None:
                section_starts.append((rel_idx, gname))

        if not section_starts:
            continue

        section_starts.sort(key=lambda t: t[0])
        for idx, (start_rel, raw_name) in enumerate(section_starts):
            name = raw_name.strip().rstrip(":").lower()
            if name not in _A04_REMOVE_SECTIONS:
                continue
            next_rel = section_starts[idx + 1][0] if idx + 1 < len(section_starts) else closing_rel
            end_rel = min(next_rel, closing_rel)
            if start_rel >= end_rel:
                continue
            start_line = doc_start + start_rel
            end_line = doc_start + end_rel - 1
            removals.append(LineRemoval(rule_ids=("A04",), start_line=start_line, end_line=end_line))

    return removals


_E09_ENCODING_RE = re.compile(r"^#.*coding[:=]\s*[-\w.]+", re.IGNORECASE)


def _python_e09_credential_redaction_replacements(lines: list[str], violations: list[Violation]) -> list[LineReplacement]:
    """
    Plan a conservative E09 auto-fix by replacing `name = "literal"` with an env var lookup.

    Rules:
    - Rewrites only simple assignments to a bare name (including `x: str = "..."`).
    - Skips dict literals (no assignment at the literal line) and class attributes.
    - Inserts `import os` once at module top if missing.
    """

    e09_lines: set[int] = set()
    for v in violations:
        if v.rule_id != "E09" or v.location is None or v.location.start_line is None:
            continue
        line_no = int(v.location.start_line)
        if line_no > 0:
            e09_lines.add(line_no)

    if not e09_lines:
        return []

    source = "".join(lines)
    try:
        import ast

        tree = ast.parse(source)
    except SyntaxError:
        return []

    # Skip class attributes by blocking non-method/class statements within class bodies.
    blocked_class_stmt_ranges: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                continue
            start = int(getattr(stmt, "lineno", 0) or 0)
            if start <= 0:
                continue
            end = int(getattr(stmt, "end_lineno", start) or start)
            blocked_class_stmt_ranges.append((start, max(start, end)))

    def line_is_blocked(line_no: int) -> bool:
        return any(start <= line_no <= end for start, end in blocked_class_stmt_ranges)

    # Only treat `import os` (binding the name `os`) as satisfying the requirement.
    os_imported = False
    if isinstance(tree, ast.Module):
        for stmt in tree.body:
            if not isinstance(stmt, ast.Import):
                continue
            for alias in stmt.names:
                if alias.name == "os" and (alias.asname is None or alias.asname == "os"):
                    os_imported = True
                    break
            if os_imported:
                break

    def insertion_line() -> int | None:
        if not isinstance(tree, ast.Module) or not lines:
            return None

        insert_after = 0
        body = list(tree.body)
        idx = 0

        # Respect module docstring (if present).
        if body:
            first = body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(getattr(first, "value", None), ast.Constant)
                and isinstance(getattr(getattr(first, "value", None), "value", None), str)
            ):
                insert_after = int(getattr(first, "end_lineno", getattr(first, "lineno", 0) or 0) or 0)
                idx = 1

        # Future imports must remain at the very top after docstring.
        while idx < len(body):
            node = body[idx]
            if isinstance(node, ast.ImportFrom) and node.module == "__future__":
                insert_after = max(insert_after, int(getattr(node, "end_lineno", getattr(node, "lineno", 0) or 0) or 0))
                idx += 1
                continue
            break

        # Extend through the initial import block.
        while idx < len(body):
            node = body[idx]
            if isinstance(node, ast.Import | ast.ImportFrom):
                insert_after = max(insert_after, int(getattr(node, "end_lineno", getattr(node, "lineno", 0) or 0) or 0))
                idx += 1
                continue
            break

        insert_line = insert_after + 1

        # Preserve shebang / encoding comment placement.
        preamble = 0
        if lines and lines[0].startswith("#!"):
            preamble = 1
        if preamble < len(lines) and _E09_ENCODING_RE.match(lines[preamble]):
            preamble += 1
        insert_line = max(insert_line, preamble + 1)

        if insert_line <= 0:
            return None
        return insert_line

    replacements: list[LineReplacement] = []

    # Replace flagged assignments.
    for node in ast.walk(tree):
        assign_line: int | None = None
        name: str | None = None
        value_is_str_literal = False

        if isinstance(node, ast.Assign):
            if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                continue
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                value_is_str_literal = True
            if not value_is_str_literal:
                continue
            assign_line = int(getattr(node, "lineno", 0) or 0)
            name = node.targets[0].id
        elif isinstance(node, ast.AnnAssign):
            if not isinstance(node.target, ast.Name):
                continue
            if node.value is None:
                continue
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                value_is_str_literal = True
            if not value_is_str_literal:
                continue
            assign_line = int(getattr(node, "lineno", 0) or 0)
            name = node.target.id
        else:
            continue

        if assign_line is None or assign_line <= 0 or assign_line > len(lines):
            continue
        if assign_line not in e09_lines:
            continue
        if line_is_blocked(assign_line):
            continue
        if not name:
            continue

        original_line = lines[assign_line - 1]
        indent = original_line[: len(original_line) - len(original_line.lstrip())]
        newline = "\n" if original_line.endswith("\n") else ""
        env_name = name.upper()
        replacements.append(
            LineReplacement(
                rule_ids=("E09",),
                line=assign_line,
                content=f'{indent}{name} = os.environ.get("{env_name}", ""){newline}',
            )
        )

    if not replacements:
        return []

    # Insert `import os` once when required.
    if not os_imported:
        insert_at = insertion_line()
        if insert_at is not None and 1 <= insert_at <= len(lines):
            base_line = lines[insert_at - 1]
            separator = "" if base_line.strip() == "" else "\n"
            replacements.append(
                LineReplacement(
                    rule_ids=("E09",),
                    line=insert_at,
                    content=f"import os\n{separator}{base_line}",
                )
            )
        elif insert_at is not None and insert_at == len(lines) + 1 and lines:
            # File ends at the import block; append `import os` after the last line.
            last_line_no = len(lines)
            base_line = lines[last_line_no - 1]
            newline = "" if base_line.endswith("\n") else "\n"
            replacements.append(
                LineReplacement(
                    rule_ids=("E09",),
                    line=last_line_no,
                    content=f"{base_line}{newline}import os\n",
                )
            )

    return replacements


def _plan_removals(
    lines: list[str],
    comment_mask: _CommentMask,
    violations: list[Violation],
    *,
    language: str,
) -> tuple[LineRemoval, ...]:
    candidates: list[LineRemoval] = []

    e03_bulk_handled: set[int] = set()
    if language == "python" and any(v.rule_id == "E03" for v in violations):
        bulk = _python_unused_import_statement_removals(lines, violations)
        for removal in bulk:
            e03_bulk_handled.add(removal.start_line)
        candidates.extend(bulk)

    # Single-line removals for comment-only rules.
    for v in violations:
        line_no = int(v.location.start_line or 0) if v.location else 0
        if line_no <= 0 or line_no > len(lines):
            continue
        line = lines[line_no - 1]

        if v.rule_id == "E03" and language == "python":
            if line_no in e03_bulk_handled:
                continue
            if _is_safe_simple_python_import_removal(line):
                candidates.append(LineRemoval(rule_ids=("E03",), start_line=line_no, end_line=line_no))
            continue

        if v.rule_id == "A06":
            # A06 is only auto-fixed when the tag appears in comments; avoid
            # rewriting strings / JSX / other contexts.
            if _should_remove_line("A06", line_no, line, comment_mask, allow_block_interior=True):
                candidates.append(LineRemoval(rule_ids=("A06",), start_line=line_no, end_line=line_no))
            continue

        if _should_remove_line(v.rule_id, line_no, line, comment_mask, allow_block_interior=True):
            candidates.append(LineRemoval(rule_ids=(v.rule_id,), start_line=line_no, end_line=line_no))

    # Range removals for <thinking>...</thinking> blocks inside comments.
    if any(v.rule_id == "A06" for v in violations):
        for start, end in _thinking_blocks(lines, comment_mask):
            candidates.append(LineRemoval(rule_ids=("A06",), start_line=start, end_line=end))

    # E11: remove the body/else lines of redundant boolean returns (the if-line
    # itself is replaced by _plan_replacements).
    if language == "python" and any(v.rule_id == "E11" for v in violations):
        candidates.extend(_python_boolean_return_extra_removals(lines, violations))

    # A04: trim boilerplate docstring sections for trivial, verbose functions.
    if language == "python" and any(v.rule_id == "A04" for v in violations):
        candidates.extend(_python_a04_docstring_section_removals(lines, violations))

    return _merge_removals(candidates)


def _plan_replacements(
    lines: list[str],
    comment_mask: _CommentMask,
    violations: list[Violation],
    *,
    language: str,
) -> tuple[LineReplacement, ...]:
    replacements: list[LineReplacement] = []

    if language != "python":
        return ()

    for v in violations:
        if v.rule_id != "E04":
            continue
        except_line_no = int(v.location.start_line or 0) if v.location else 0
        if except_line_no <= 0 or except_line_no > len(lines):
            continue

        pass_line_no = _python_bare_except_pass_line(lines, except_line_no)
        if pass_line_no is None:
            continue

        pass_line = lines[pass_line_no - 1]
        if "slop:" in pass_line.lower():
            continue

        indent = pass_line[: len(pass_line) - len(pass_line.lstrip())]
        newline = "\n" if pass_line.endswith("\n") else ""
        replacements.append(LineReplacement(rule_ids=("E04",), line=pass_line_no, content=f"{indent}raise{newline}"))

    if any(v.rule_id == "E09" for v in violations):
        replacements.extend(_python_e09_credential_redaction_replacements(lines, violations))

    replaced_lines = {r.line for r in replacements}
    if any(v.rule_id == "E06" for v in violations):
        replacements.extend(_python_plan_constant_extraction(lines, violations, replaced_lines=replaced_lines))

    if any(v.rule_id == "E11" for v in violations):
        replacements.extend(_python_plan_boolean_return_simplification(lines, violations, replaced_lines={r.line for r in replacements}))

    return _merge_replacements(lines, replacements)


def _python_bare_except_pass_line(lines: list[str], except_line_no: int) -> int | None:
    """
    Return the 1-based line number of the `pass` statement inside `except:`.

    The corresponding rule only triggers for `except: pass`, but we still keep
    this text-based matcher conservative.
    """

    except_line = lines[except_line_no - 1]
    except_indent = len(except_line) - len(except_line.lstrip())

    for i in range(except_line_no + 1, len(lines) + 1):
        line = lines[i - 1]
        stripped = line.strip()
        if stripped == "":
            continue
        if stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= except_indent:
            return None
        if stripped.startswith("pass"):
            return i
        return None

    return None


_E03_UNUSED_IMPORT_RE = re.compile(r"Imported name `(?P<name>[^`]+)` is never used\.")


def _python_unused_import_statement_removals(lines: list[str], violations: list[Violation]) -> list[LineRemoval]:
    """
    Plan safe removals for Python unused imports, including multi-line `from ... import (...)`.

    Conservative behavior:
    - Only removes a whole import statement when *all* imported bindings from that statement are unused.
    - Only removes statements at indentation level 0 (module scope).
    - Skips statements containing `slop:` directives or semicolons.
    """

    unused_by_line: dict[int, set[str]] = {}
    for v in violations:
        if v.rule_id != "E03" or v.location is None or v.location.start_line is None:
            continue
        m = _E03_UNUSED_IMPORT_RE.search(v.message)
        if not m:
            continue
        line_no = int(v.location.start_line)
        if line_no <= 0:
            continue
        unused_by_line.setdefault(line_no, set()).add(m.group("name"))

    if not unused_by_line:
        return []

    source = "".join(lines)
    try:
        import ast

        tree = ast.parse(source)
    except SyntaxError:
        return []

    info_by_start: dict[int, tuple[int, set[str]]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Import | ast.ImportFrom):
            continue
        if not hasattr(node, "lineno"):
            continue
        start = int(getattr(node, "lineno", 0) or 0)
        if start <= 0 or start > len(lines):
            continue
        if start in info_by_start:
            # Multiple import statements on the same physical line (e.g. via
            # semicolons) are too risky to edit safely.
            continue

        start_line = lines[start - 1]
        if start_line.startswith((" ", "\t")):
            continue
        if ";" in start_line:
            continue

        end = int(getattr(node, "end_lineno", start) or start)
        end = max(start, min(end, len(lines)))

        names: set[str] = set()
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name.split(".", 1)[0]
                names.add(name)
        else:
            if node.module == "__future__":
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                name = alias.asname or alias.name
                names.add(name)

        if not names:
            continue

        info_by_start[start] = (end, names)

    removals: list[LineRemoval] = []
    for start, (end, names) in sorted(info_by_start.items()):
        unused = unused_by_line.get(start)
        if not unused or unused != names:
            continue
        if any("slop:" in lines[i - 1].lower() for i in range(start, end + 1)):
            continue
        removals.append(LineRemoval(rule_ids=("E03",), start_line=start, end_line=end))

    return removals


_E06_LITERAL_RE = re.compile(r"String literal repeats\s+\d+\s+times:\s+(?P<literal>.+)$")


def _python_token_is_fstring(token: str) -> bool:
    lower = token.lower()
    for idx, ch in enumerate(lower):
        if ch in {"'", '"'}:
            return "f" in lower[:idx]
    return False


def _python_constant_name(value: str, *, source: str) -> str | None:
    words = re.findall(r"[A-Za-z0-9]+", value)
    base = "_".join(w.upper() for w in words if w) if words else "SLOP_STRING"
    base = re.sub(r"[^A-Z0-9_]", "_", base)
    if not base or not base[0].isalpha():
        base = "SLOP_" + (base or "STRING")
    base = base[:40].rstrip("_") or "SLOP_STRING"
    # If the name is already present, skip the auto-fix rather than guessing
    # a different identifier (safer + avoids surprising `_2` constants).
    if re.search(rf"\b{re.escape(base)}\b", source):
        return None
    return base


def _python_plan_constant_extraction(
    lines: list[str],
    violations: list[Violation],
    *,
    replaced_lines: set[int],
) -> list[LineReplacement]:
    """
    Plan a conservative E06 auto-fix by extracting the first repeated string literal into a module constant.

    Safety constraints:
    - Only Python files.
    - Skips files using `match` (pattern matching).
    - Skips literals that appear in annotations or f-strings.
    - Only replaces single-line string tokens (no triple-quoted spans).
    """

    e06_candidates: list[tuple[int, Violation]] = []
    for v in violations:
        if v.rule_id != "E06":
            continue
        if v.location is None or v.location.start_line is None:
            continue
        e06_candidates.append((int(v.location.start_line), v))

    if not e06_candidates:
        return []

    e06_candidates.sort(key=lambda t: t[0])
    m = _E06_LITERAL_RE.search(e06_candidates[0][1].message)
    if not m:
        return []

    try:
        import ast

        value_obj = ast.literal_eval(m.group("literal"))
    except (SyntaxError, ValueError):
        return []
    # Keep extraction conservative: short strings rarely benefit from constants.
    if not isinstance(value_obj, str) or len(value_obj) < 6:
        return []

    source = "".join(lines)
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    # Skip files that use pattern matching: replacing literals in patterns can change semantics.
    if any(isinstance(n, ast.Match) for n in ast.walk(tree)):
        return []

    def annotation_contains_value(expr: ast.AST | None) -> bool:
        if expr is None:
            return False
        return any(isinstance(n, ast.Constant) and n.value == value_obj for n in ast.walk(expr))

    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and annotation_contains_value(node.annotation):
            return []
        if isinstance(node, ast.arg) and annotation_contains_value(node.annotation):
            return []
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and annotation_contains_value(node.returns):
            return []
        if isinstance(node, ast.JoinedStr):
            if any(isinstance(n, ast.Constant) and n.value == value_obj for n in ast.walk(node)):
                return []

    def record_docstring_start(body: list[ast.stmt]) -> int | None:
        if not body:
            return None
        first = body[0]
        if not isinstance(first, ast.Expr):
            return None
        val = getattr(first, "value", None)
        if not (isinstance(val, ast.Constant) and isinstance(val.value, str)):
            return None
        return int(getattr(first, "lineno", 0) or 0) or None

    docstring_starts: set[int] = set()
    module_doc_end = 0
    if isinstance(tree, ast.Module):
        start = record_docstring_start(list(tree.body))
        if start is not None:
            docstring_starts.add(start)
            first = tree.body[0]
            module_doc_end = int(getattr(first, "end_lineno", getattr(first, "lineno", 0) or 0) or 0)

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            start = record_docstring_start(list(node.body))
            if start is not None:
                docstring_starts.add(start)

    blocked_class_stmt_ranges: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                continue
            start = int(getattr(stmt, "lineno", 0) or 0)
            if start <= 0:
                continue
            end = int(getattr(stmt, "end_lineno", start) or start)
            blocked_class_stmt_ranges.append((start, max(start, end)))

    def line_is_blocked(line_no: int) -> bool:
        return any(start <= line_no <= end for start, end in blocked_class_stmt_ranges)

    # Insert after the initial module docstring + top-level import block.
    insert_after = max(0, module_doc_end)
    if isinstance(tree, ast.Module):
        body = list(tree.body)
        idx = 0
        if body:
            first = body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(getattr(first, "value", None), ast.Constant)
                and isinstance(getattr(getattr(first, "value", None), "value", None), str)
            ):
                idx = 1

        while idx < len(body):
            node = body[idx]
            if isinstance(node, ast.Import | ast.ImportFrom):
                end = int(getattr(node, "end_lineno", getattr(node, "lineno", 0) or 0) or 0)
                insert_after = max(insert_after, end)
                idx += 1
                continue
            break

    insert_line = int(insert_after) + 1
    if insert_line <= 0 or insert_line > len(lines):
        return []
    if insert_line in replaced_lines:
        return []

    const_name = _python_constant_name(value_obj, source=source)
    if const_name is None:
        return []

    # Identify safe token-level replacements.
    spans_by_line: dict[int, list[tuple[int, int]]] = {}
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return []

    hit_count = 0
    for tok in tokens:
        if tok.type != tokenize.STRING:
            continue
        if tok.start[0] != tok.end[0]:
            continue
        if line_is_blocked(tok.start[0]):
            continue
        if tok.start[0] in docstring_starts:
            continue
        if _python_token_is_fstring(tok.string):
            continue
        try:
            lit = ast.literal_eval(tok.string)
        except (SyntaxError, ValueError):
            continue
        if lit != value_obj:
            continue
        hit_count += 1
        spans_by_line.setdefault(tok.start[0], []).append((tok.start[1], tok.end[1]))

    # Keep this conservative: only extract when it clearly repeats.
    if hit_count < 3:
        return []

    line_replacements: dict[int, str] = {}
    for line_no, spans in spans_by_line.items():
        if line_no in replaced_lines:
            continue
        if line_no <= 0 or line_no > len(lines):
            continue
        original_line = lines[line_no - 1]
        new_line = original_line
        for start_col, end_col in sorted(spans, reverse=True):
            new_line = new_line[:start_col] + const_name + new_line[end_col:]
        line_replacements[line_no] = new_line

    base_line = line_replacements.get(insert_line, lines[insert_line - 1])
    const_def = f"{const_name} = {value_obj!r}\n"
    separator = "" if base_line.strip() == "" else "\n"
    line_replacements[insert_line] = const_def + separator + base_line

    return [LineReplacement(rule_ids=("E06",), line=line_no, content=content) for line_no, content in sorted(line_replacements.items())]


def _python_plan_boolean_return_simplification(
    lines: list[str],
    violations: list[Violation],
    *,
    replaced_lines: set[int],
) -> list[LineReplacement]:
    """
    Plan a conservative E11 auto-fix by replacing ``if cond: return True else: return False``
    with ``return cond`` (or ``return not cond`` for the inverted case).

    Safety constraints:
    - Only Python files.
    - Only handles the pattern when the if/else is on separate lines with single-statement bodies.
    - Uses AST to extract the condition text safely.
    """

    import ast

    e11_lines: list[int] = []
    for v in violations:
        if v.rule_id != "E11":
            continue
        if v.location is None or v.location.start_line is None:
            continue
        line_no = int(v.location.start_line)
        if line_no > 0 and line_no not in replaced_lines:
            e11_lines.append(line_no)

    if not e11_lines:
        return []

    source = "".join(lines)
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    # Build a map of if-statement line -> AST node for matching.
    if_nodes: dict[int, ast.If] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and hasattr(node, "lineno"):
            if_nodes[int(node.lineno)] = node

    replacements: list[LineReplacement] = []
    for line_no in e11_lines:
        if_node = if_nodes.get(line_no)
        if if_node is None:
            continue
        if not if_node.orelse or len(if_node.body) != 1 or len(if_node.orelse) != 1:
            continue
        body_stmt = if_node.body[0]
        else_stmt = if_node.orelse[0]
        if not isinstance(body_stmt, ast.Return) or not isinstance(else_stmt, ast.Return):
            continue
        body_val = getattr(body_stmt, "value", None)
        else_val = getattr(else_stmt, "value", None)
        if not isinstance(body_val, ast.Constant) or not isinstance(else_val, ast.Constant):
            continue
        if not isinstance(body_val.value, bool) or not isinstance(else_val.value, bool):
            continue

        # Extract the condition source text.
        cond = if_node.test
        cond_start_line = int(getattr(cond, "lineno", 0) or 0)
        cond_end_line = int(getattr(cond, "end_lineno", cond_start_line) or cond_start_line)
        cond_start_col = int(getattr(cond, "col_offset", 0) or 0)
        cond_end_col = int(getattr(cond, "end_col_offset", 0) or 0)

        # Only handle single-line conditions for safety.
        if cond_start_line != cond_end_line or cond_start_line <= 0:
            continue

        cond_line = lines[cond_start_line - 1]
        cond_text = cond_line[cond_start_col:cond_end_col].strip()
        if not cond_text:
            continue

        # Determine the full range of lines to replace.
        if_end_line = int(getattr(if_node, "end_lineno", 0) or 0)
        if if_end_line <= 0 or if_end_line > len(lines):
            continue

        # Check no lines in range are already replaced.
        if any(ln in replaced_lines for ln in range(line_no, if_end_line + 1)):
            continue

        # Build the replacement.
        if_line = lines[line_no - 1]
        indent = if_line[: len(if_line) - len(if_line.lstrip())]
        newline = "\n" if if_line.endswith("\n") else ""

        if body_val.value is True and else_val.value is False:
            replacement = f"{indent}return {cond_text}{newline}"
        else:
            replacement = f"{indent}return not {cond_text}{newline}"

        # Replace the first line only; extra lines are removed by _python_boolean_return_extra_removals.
        replacements.append(LineReplacement(rule_ids=("E11",), line=line_no, content=replacement))

    return replacements


def _python_boolean_return_extra_removals(
    lines: list[str],
    violations: list[Violation],
) -> list[LineRemoval]:
    """Return LineRemoval entries for the body/else lines of E11 patterns (lines after the if-line)."""

    import ast

    e11_lines: list[int] = []
    for v in violations:
        if v.rule_id != "E11" or v.location is None or v.location.start_line is None:
            continue
        line_no = int(v.location.start_line)
        if line_no > 0:
            e11_lines.append(line_no)

    if not e11_lines:
        return []

    source = "".join(lines)
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    if_nodes: dict[int, ast.If] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and hasattr(node, "lineno"):
            if_nodes[int(node.lineno)] = node

    removals: list[LineRemoval] = []
    for line_no in e11_lines:
        if_node = if_nodes.get(line_no)
        if if_node is None:
            continue
        if_end_line = int(getattr(if_node, "end_lineno", 0) or 0)
        if if_end_line <= line_no or if_end_line > len(lines):
            continue
        # Remove lines after the if-line (body + else).
        removals.append(LineRemoval(rule_ids=("E11",), start_line=line_no + 1, end_line=if_end_line))

    return removals


def _is_safe_simple_python_import_removal(line: str) -> bool:
    # Never delete suppression directives.
    if "slop:" in line.lower():
        return False

    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return False
    if stripped.startswith("from __future__ import"):
        return False
    if "\\" in stripped or "(" in stripped or ")" in stripped or "," in stripped:
        return False
    if stripped.startswith("import "):
        # Keep this extremely conservative: only `import <name>` / `import <name> as <alias>`.
        module = stripped[len("import ") :].split("#", 1)[0].strip()
        module = module.split(" as ", 1)[0].strip()
        if "." in module:
            return False
        return True
    if stripped.startswith("from ") and " import " in stripped and " import *" not in stripped:
        return True
    return False

def _should_remove_line(
    rule_id: str,
    line_no: int,
    line: str,
    comment_mask: _CommentMask,
    *,
    allow_block_interior: bool,
) -> bool:
    if not comment_mask.is_comment[line_no]:
        return False

    if "slop:" in line.lower():
        # Never remove suppression directives (even if they look like "slop").
        return False

    stripped = line.lstrip()
    if stripped.startswith("#") or stripped.startswith("//"):
        return _line_matches_rule(rule_id, line)

    if comment_mask.in_block_comment[line_no]:
        if not allow_block_interior:
            return False

        # Avoid deleting block comment boundaries unless it's a single-line /* ... */.
        if "/*" in stripped or "*/" in stripped:
            if stripped.startswith("/*") and "*/" in stripped:
                return _line_matches_rule(rule_id, line)
            return False
        return _line_matches_rule(rule_id, line)

    return False


def _line_matches_rule(rule_id: str, line: str) -> bool:
    if rule_id == "A03":
        return POLITE_RE.search(line) is not None
    if rule_id == "A10":
        return BANNER_RE.match(line) is not None
    if rule_id == "D01":
        return COMPREHENSIVE_RE.search(line) is not None
    if rule_id == "C09":
        return LAST_UPDATE_RE.search(line) is not None
    if rule_id == "A06":
        return THINKING_RE.search(line) is not None
    return False


def _thinking_blocks(lines: list[str], comment_mask: _CommentMask) -> list[tuple[int, int]]:
    """
    Return safe (start_line, end_line) pairs for <thinking> blocks within comments.

    Conservative behavior:
    - Only consider lines already classified as comments.
    - Only delete a block if every line in the range is safe to delete.
    """

    blocks: list[tuple[int, int]] = []
    open_start: int | None = None

    for idx, line in enumerate(lines, start=1):
        if not comment_mask.is_comment[idx]:
            continue

        lowered = line.lower()
        has_open = "<thinking>" in lowered
        has_close = "</thinking>" in lowered
        if not (has_open or has_close):
            continue

        if has_open and has_close:
            if _range_is_safe(lines, comment_mask, start=idx, end=idx):
                blocks.append((idx, idx))
            continue

        if open_start is None:
            if has_open:
                open_start = idx
            elif has_close:
                # Stray close tag; remove just that line when safe.
                if _range_is_safe(lines, comment_mask, start=idx, end=idx):
                    blocks.append((idx, idx))
            continue

        if has_close:
            if _range_is_safe(lines, comment_mask, start=open_start, end=idx):
                blocks.append((open_start, idx))
            open_start = None

    return blocks


def _range_is_safe(lines: list[str], comment_mask: _CommentMask, *, start: int, end: int) -> bool:
    for line_no in range(start, end + 1):
        if line_no <= 0 or line_no > len(lines):
            return False
        if not comment_mask.is_comment[line_no]:
            return False
        if not _is_safe_any_comment_deletion(line_no, lines[line_no - 1], comment_mask):
            return False
    return True


def _is_safe_any_comment_deletion(line_no: int, line: str, comment_mask: _CommentMask) -> bool:
    if "slop:" in line.lower():
        return False

    stripped = line.lstrip()
    if stripped.startswith("#") or stripped.startswith("//"):
        return True

    if comment_mask.in_block_comment[line_no]:
        # Single-line /* ... */ is safe, interior lines are safe.
        if "/*" in stripped or "*/" in stripped:
            return stripped.startswith("/*") and "*/" in stripped
        return True

    return False


def _merge_removals(removals: list[LineRemoval]) -> tuple[LineRemoval, ...]:
    if not removals:
        return ()

    # Merge overlapping/adjacent ranges and union their rule IDs.
    merged: list[LineRemoval] = []
    for removal in sorted(removals, key=lambda r: (r.start_line, r.end_line, r.rule_ids)):
        if not merged:
            merged.append(removal)
            continue

        prev = merged[-1]
        if removal.start_line <= prev.end_line + 1:
            merged[-1] = LineRemoval(
                rule_ids=tuple(sorted(set(prev.rule_ids).union(removal.rule_ids))),
                start_line=min(prev.start_line, removal.start_line),
                end_line=max(prev.end_line, removal.end_line),
            )
            continue

        merged.append(removal)

    return tuple(merged)


def _merge_replacements(lines: list[str], replacements: list[LineReplacement]) -> tuple[LineReplacement, ...]:
    """
    Merge multiple planned replacements targeting the same physical line.

    Auto-fix planning is intentionally rule-local, which can lead to "insertion"
    replacements (prefixing `import ...` before an existing line) colliding with
    "rewrite" replacements (replacing that existing line). This helper merges
    those safely so we don't drop one edit on the floor.
    """

    if not replacements:
        return ()

    by_line: dict[int, list[LineReplacement]] = {}
    for rep in replacements:
        by_line.setdefault(rep.line, []).append(rep)

    def insertion_weight(rep: LineReplacement) -> int:
        ids = set(rep.rule_ids)
        # Imports should appear before other inserted content.
        if "E09" in ids:
            return 0
        # Constants extracted after imports.
        if "E06" in ids:
            return 10
        return 50

    merged: list[LineReplacement] = []
    for line_no, group in sorted(by_line.items(), key=lambda t: t[0]):
        if len(group) == 1:
            merged.append(group[0])
            continue

        if line_no <= 0 or line_no > len(lines):
            # Out-of-range edits are ignored elsewhere; keep the last to be deterministic.
            merged.append(group[-1])
            continue

        original_line = lines[line_no - 1]
        insertion_reps: list[LineReplacement] = []
        full_reps: list[LineReplacement] = []
        for rep in group:
            if original_line and rep.content.endswith(original_line) and rep.content != original_line:
                insertion_reps.append(rep)
            else:
                full_reps.append(rep)

        base_content = full_reps[-1].content if full_reps else original_line

        prefixes: list[str] = []
        for rep in sorted(insertion_reps, key=insertion_weight):
            prefix = rep.content[: -len(original_line)] if original_line else rep.content
            if prefix and prefix not in prefixes:
                prefixes.append(prefix)

        rule_ids = tuple(sorted({rid for rep in group for rid in rep.rule_ids}))
        merged.append(LineReplacement(rule_ids=rule_ids, line=line_no, content="".join(prefixes) + base_content))

    return tuple(merged)


def _flatten_removals(removals: tuple[LineRemoval, ...]) -> set[int]:
    out: set[int] = set()
    for removal in removals:
        for line_no in range(removal.start_line, removal.end_line + 1):
            out.add(line_no)
    return out


def _unified_diff(before: str, after: str, *, path: Path) -> str:
    if before == after:
        return ""
    before_lines = before.splitlines(keepends=False)
    after_lines = after.splitlines(keepends=False)
    diff = difflib.unified_diff(
        before_lines,
        after_lines,
        fromfile=str(path),
        tofile=str(path),
        lineterm="",
    )
    return "\n".join(diff)
