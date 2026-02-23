from __future__ import annotations

import re
from dataclasses import dataclass

from slopsentinel.engine.context import FileContext
from slopsentinel.engine.types import Violation
from slopsentinel.rules.base import BaseRule, RuleMeta, loc_from_line
from slopsentinel.rules.utils import iter_code_lines, iter_comment_lines

_JS_TS_LANGUAGES = {"javascript", "typescript"}
_JS_TS_IDENTIFIER_RE = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")

_JS_TS_IMPORT_FROM_RE = re.compile(
    r"(?ms)^[ \t]*import(?:\s+type)?\s+(?P<clause>[\s\S]*?)\s+from\s+(?P<q>['\"])(?P<mod>[^'\"\n]+)(?P=q)\s*;?"
)
_JS_TS_IMPORT_SIDE_EFFECT_RE = re.compile(r"(?m)^[ \t]*import\s+(?P<q>['\"])(?P<mod>[^'\"\n]+)(?P=q)\s*;?")
_JS_TS_EXPORT_FROM_RE = re.compile(
    r"(?ms)^[ \t]*export\s+[\s\S]*?\s+from\s+(?P<q>['\"])(?P<mod>[^'\"\n]+)(?P=q)\s*;?"
)
_JS_TS_REQUIRE_IMPORT_CALL_RE = re.compile(r"\b(?:require|import)\s*\(\s*(['\"])([^'\"\n]+)\1\s*\)")

_IDENTIFIER_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_IDENTIFIER_ACRONYM_BOUNDARY_RE = re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])")


def _merge_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not spans:
        return []
    spans_sorted = sorted(spans)
    merged: list[tuple[int, int]] = []
    start, end = spans_sorted[0]
    for s, e in spans_sorted[1:]:
        if s <= end:
            end = max(end, e)
            continue
        merged.append((start, end))
        start, end = s, e
    merged.append((start, end))
    return merged


def _blank_out_spans(text: str, spans: list[tuple[int, int]]) -> str:
    if not spans:
        return text
    merged = _merge_spans(spans)
    out: list[str] = []
    cursor = 0
    for start, end in merged:
        out.append(text[cursor:start])
        segment = text[start:end]
        out.append("".join("\n" if ch == "\n" else " " for ch in segment))
        cursor = end
    out.append(text[cursor:])
    return "".join(out)


def _line_no_at_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _split_top_level_commas(text: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    start = 0
    for idx, ch in enumerate(text):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth = max(depth - 1, 0)
        elif ch == "," and depth == 0:
            parts.append(text[start:idx])
            start = idx + 1
    parts.append(text[start:])
    return parts


def _blank_js_ts_comments(text: str) -> str:
    """
    Replace JS/TS comments with whitespace while preserving newlines/length.

    This intentionally does not attempt to parse strings or regex literals; it is
    only used for import clause parsing where strings are not expected.
    """

    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "/" and i + 1 < n:
            nxt = text[i + 1]
            if nxt == "/":  # line comment
                out.append("  ")
                i += 2
                while i < n and text[i] != "\n":
                    out.append(" ")
                    i += 1
                continue
            if nxt == "*":  # block comment
                out.append("  ")
                i += 2
                while i < n - 1:
                    if text[i] == "*" and text[i + 1] == "/":
                        out.append("  ")
                        i += 2
                        break
                    out.append("\n" if text[i] == "\n" else " ")
                    i += 1
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def _js_ts_parse_import_clause(clause: str) -> list[str]:
    cleaned = _blank_js_ts_comments(clause).strip()
    if cleaned.startswith("type "):
        cleaned = cleaned[5:].lstrip()

    bindings: list[str] = []
    for part in _split_top_level_commas(cleaned):
        token = part.strip()
        if not token:
            continue

        if token.startswith("type "):
            token = token[5:].lstrip()

        if token.startswith("{"):
            end = token.rfind("}")
            if end == -1:
                continue
            inside = token[1:end]
            for spec in inside.split(","):
                spec_clean = spec.strip()
                if not spec_clean:
                    continue
                if spec_clean.startswith("type "):
                    spec_clean = spec_clean[5:].lstrip()
                if " as " in spec_clean:
                    _, alias = spec_clean.split(" as ", 1)
                    candidate = alias.strip()
                else:
                    candidate = spec_clean
                if _JS_TS_IDENTIFIER_RE.match(candidate):
                    bindings.append(candidate)
            continue

        if token.startswith("*"):
            m = re.match(r"^\*\s+as\s+([A-Za-z_$][A-Za-z0-9_$]*)$", token)
            if m:
                bindings.append(m.group(1))
            continue

        if _JS_TS_IDENTIFIER_RE.match(token):
            bindings.append(token)

    return bindings


def _looks_like_jsx(ctx: FileContext) -> bool:
    suffix = ctx.path.suffix.lower()
    if suffix in {".jsx", ".tsx"}:
        return True
    # Heuristic: JSX almost always contains either a closing tag or a self-closing tag.
    if "/>" in ctx.text:
        return True
    return bool(re.search(r"</[A-Za-z]", ctx.text))


def _js_ts_import_spans_and_bindings(text: str) -> tuple[list[tuple[int, int]], list[tuple[str, int]]]:
    spans: list[tuple[int, int]] = []
    bindings: list[tuple[str, int]] = []

    for match in _JS_TS_IMPORT_FROM_RE.finditer(text):
        spans.append(match.span())
        clause = match.group("clause")
        line_no = _line_no_at_offset(text, match.start())
        for name in _js_ts_parse_import_clause(clause):
            bindings.append((name, line_no))

    for match in _JS_TS_IMPORT_SIDE_EFFECT_RE.finditer(text):
        spans.append(match.span())

    return spans, bindings


def _js_ts_repeated_string_literals(text: str) -> dict[str, list[int]]:
    literals: dict[str, list[int]] = {}
    i = 0
    line_no = 1
    n = len(text)

    while i < n:
        ch = text[i]
        if ch == "\n":
            line_no += 1
            i += 1
            continue

        if ch == "/" and i + 1 < n:
            nxt = text[i + 1]
            if nxt == "/":  # line comment
                i += 2
                while i < n and text[i] != "\n":
                    i += 1
                continue
            if nxt == "*":  # block comment
                i += 2
                while i < n - 1:
                    if text[i] == "\n":
                        line_no += 1
                    if text[i] == "*" and text[i + 1] == "/":
                        i += 2
                        break
                    i += 1
                continue

        if ch in {"'", '"'}:
            quote = ch
            start_line = line_no
            i += 1
            buf: list[str] = []
            while i < n:
                c = text[i]
                if c == "\n":
                    line_no += 1
                    i += 1
                    break
                if c == "\\":
                    if i + 1 < n:
                        buf.append(text[i + 1])
                        i += 2
                        continue
                    i += 1
                    continue
                if c == quote:
                    i += 1
                    break
                buf.append(c)
                i += 1
            value = "".join(buf)
            if len(value) >= 4:
                literals.setdefault(value, []).append(start_line)
            continue

        if ch == "`":
            # Templates are intentionally ignored to keep heuristics conservative.
            i += 1
            while i < n:
                c = text[i]
                if c == "\n":
                    line_no += 1
                    i += 1
                    continue
                if c == "\\":
                    i += 2 if i + 1 < n else 1
                    continue
                if c == "`":
                    i += 1
                    break
                i += 1
            continue

        i += 1

    return literals


def _split_identifier_words(name: str) -> list[str]:
    if not name:
        return []

    spaced = name.replace("_", " ")
    spaced = _IDENTIFIER_ACRONYM_BOUNDARY_RE.sub(" ", spaced)
    spaced = _IDENTIFIER_CAMEL_BOUNDARY_RE.sub(" ", spaced)
    return [part.lower() for part in spaced.split() if part]


def _looks_like_credential_variable(name: str) -> bool:
    words = _split_identifier_words(name)
    if not words:
        return False
    if "password" in words or "secret" in words or "token" in words:
        return True
    if "apikey" in words:
        return True
    for idx, word in enumerate(words[:-1]):
        if word == "api" and words[idx + 1] == "key":
            return True
    return False


def _js_ts_tokenize_for_simple_assignments(text: str) -> list[tuple[str, str, int]]:
    """
    Tokenize JS/TS with a small, conservative lexer.

    This only emits tokens needed for assignment pattern matching:
    - identifiers
    - single/double-quoted string literals
    - selected punctuation tokens
    - newlines

    Templates (backticks) are skipped entirely to avoid false positives on
    embedded snippets.
    """

    tokens: list[tuple[str, str, int]] = []
    i = 0
    line_no = 1
    n = len(text)

    while i < n:
        ch = text[i]
        if ch == "\n":
            tokens.append(("nl", "\n", line_no))
            line_no += 1
            i += 1
            continue

        if ch in {" ", "\t", "\r"}:
            i += 1
            continue

        if ch == "/" and i + 1 < n:
            nxt = text[i + 1]
            if nxt == "/":  # line comment
                i += 2
                while i < n and text[i] != "\n":
                    i += 1
                continue
            if nxt == "*":  # block comment
                i += 2
                while i < n - 1:
                    if text[i] == "\n":
                        line_no += 1
                    if text[i] == "*" and text[i + 1] == "/":
                        i += 2
                        break
                    i += 1
                continue

        if ch in {"'", '"'}:
            quote = ch
            start_line = line_no
            i += 1
            buf: list[str] = []
            while i < n:
                c = text[i]
                if c == "\n":
                    line_no += 1
                    i += 1
                    break
                if c == "\\":
                    if i + 1 < n:
                        buf.append(text[i + 1])
                        i += 2
                        continue
                    i += 1
                    continue
                if c == quote:
                    i += 1
                    break
                buf.append(c)
                i += 1
            tokens.append(("str", "".join(buf), start_line))
            continue

        if ch == "`":
            i += 1
            while i < n:
                c = text[i]
                if c == "\n":
                    line_no += 1
                    i += 1
                    continue
                if c == "\\":
                    i += 2 if i + 1 < n else 1
                    continue
                if c == "`":
                    i += 1
                    break
                i += 1
            continue

        if ch.isalpha() or ch in {"_", "$"}:
            start = i
            i += 1
            while i < n and (text[i].isalnum() or text[i] in {"_", "$"}):
                i += 1
            tokens.append(("ident", text[start:i], line_no))
            continue

        if ch in {"=", ";", ",", ":", "."}:
            tokens.append(("punct", ch, line_no))
            i += 1
            continue

        i += 1

    return tokens


def _js_ts_hardcoded_credential_assignments(text: str) -> list[tuple[str, int]]:
    tokens = _js_ts_tokenize_for_simple_assignments(text)
    hits: list[tuple[str, int]] = []

    i = 0
    n = len(tokens)

    def skip_newlines(idx: int) -> int:
        while idx < n and tokens[idx][0] == "nl":
            idx += 1
        return idx

    while i < n:
        kind, value, line_no = tokens[i]

        if kind != "ident":
            i += 1
            continue

        if value == "export":
            i += 1
            continue

        if value in {"const", "let", "var"}:
            i += 1
            while i < n:
                i = skip_newlines(i)
                if i >= n:
                    break
                if tokens[i][0] != "ident":
                    break
                name = tokens[i][1]
                name_line = tokens[i][2]
                i += 1

                if i < n and tokens[i][0] == "punct" and tokens[i][1] == ":":
                    i += 1
                    while i < n:
                        k, v, _ln = tokens[i]
                        if k == "punct" and v in {"=", ",", ";"}:
                            break
                        if k == "nl":
                            break
                        i += 1

                i = skip_newlines(i)
                if i < n and tokens[i][0] == "punct" and tokens[i][1] == "=":
                    if i + 1 < n and tokens[i + 1][0] == "punct" and tokens[i + 1][1] == "=":
                        i += 1
                        continue
                    i += 1
                    i = skip_newlines(i)
                    if i < n and tokens[i][0] == "str":
                        literal = tokens[i][1]
                        if literal and _looks_like_credential_variable(name):
                            hits.append((name, name_line))
                        i += 1

                end_statement = False
                while i < n:
                    k, v, _ln = tokens[i]
                    if k == "punct" and v == ",":
                        i += 1
                        break
                    if k == "punct" and v == ";":
                        end_statement = True
                        i += 1
                        break
                    if k == "nl":
                        end_statement = True
                        i += 1
                        break
                    i += 1
                if end_statement:
                    break
            continue

        if not _looks_like_credential_variable(value):
            i += 1
            continue

        prev = i - 1
        while prev >= 0 and tokens[prev][0] == "nl":
            prev -= 1
        if prev >= 0 and tokens[prev][0] == "punct" and tokens[prev][1] == ".":
            i += 1
            continue

        j = skip_newlines(i + 1)
        if j < n and tokens[j][0] == "punct" and tokens[j][1] == "=":
            if j + 1 < n and tokens[j + 1][0] == "punct" and tokens[j + 1][1] == "=":
                i += 1
                continue
            literal_idx = skip_newlines(j + 1)
            if literal_idx < n and tokens[literal_idx][0] == "str" and tokens[literal_idx][1]:
                hits.append((value, line_no))

        i += 1

    seen: set[tuple[str, int]] = set()
    unique_hits: list[tuple[str, int]] = []
    for name, line in hits:
        key = (name, line)
        if key in seen:
            continue
        seen.add(key)
        unique_hits.append(key)
    return unique_hits


@dataclass(frozen=True, slots=True)
class E01CommentCodeRatioAnomalous(BaseRule):
    meta = RuleMeta(
        rule_id="E01",
        title="Comment/code ratio too high",
        description="Comment-heavy files can indicate AI-generated scaffolding or over-explaining.",
        default_severity="warn",
        score_dimension="hallucination",
        fingerprint_model=None,
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        comment_lines = sum(1 for _ in iter_comment_lines(ctx))
        code_lines = sum(1 for _ in iter_code_lines(ctx))

        if (comment_lines + code_lines) < 10:
            return []

        ratio = comment_lines / max(code_lines, 1)
        if ratio > 0.5:
            return [
                self._violation(
                    message=f"High comment/code ratio: {comment_lines} comments vs {code_lines} code lines (ratio {ratio:.2f}).",
                    suggestion="Remove redundant comments; keep only intent/invariants and non-obvious reasoning.",
                    location=loc_from_line(ctx, line=1),
                )
            ]
        return []


@dataclass(frozen=True, slots=True)
class E02OverlyDefensiveProgramming(BaseRule):
    """Detect excessive non-leading guard clauses.

    This rule is intentionally scoped to guard clauses that appear *after* the
    initial leading run of guard clauses at the top of a function. Leading
    consecutive guard clauses are handled by E10 to avoid double-reporting.
    """

    meta = RuleMeta(
        rule_id="E02",
        title="Overly defensive programming",
        description="Too many scattered guard clauses beyond the leading run can indicate over-engineered AI output.",
        default_severity="warn",
        score_dimension="quality",
        fingerprint_model=None,
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "python" or ctx.python_ast is None:
            return []

        import ast

        def is_guard_if(stmt: ast.stmt) -> bool:
            if not isinstance(stmt, ast.If):
                return False
            if stmt.orelse:
                return False
            if not stmt.body:
                return False
            return isinstance(stmt.body[0], ast.Return | ast.Raise)

        violations = []
        for node in ast.walk(ctx.python_ast):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue

            body = list(node.body)
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant):
                if isinstance(getattr(body[0].value, "value", None), str):
                    body = body[1:]

            leading_consecutive = 0
            for stmt in body:
                if is_guard_if(stmt):
                    leading_consecutive += 1
                    continue
                break

            if leading_consecutive > 5:
                continue

            scattered_guards = 0
            for stmt in body[leading_consecutive:]:
                if is_guard_if(stmt):
                    scattered_guards += 1

            if scattered_guards > 5 and hasattr(node, "lineno"):
                violations.append(
                    self._violation(
                        message=(
                            f"Function `{node.name}` contains {scattered_guards} guard-style if statements beyond the leading guard run."
                        ),
                        suggestion="Keep guards minimal; prefer validating at boundaries and simplifying logic.",
                        location=loc_from_line(ctx, line=int(node.lineno)),
                    )
                )
        return violations


@dataclass(frozen=True, slots=True)
class E03UnusedImports(BaseRule):
    meta = RuleMeta(
        rule_id="E03",
        title="Unused imports",
        description="Unused imports increase confusion and can indicate AI hallucination/scaffolding.",
        default_severity="warn",
        score_dimension="quality",
        fingerprint_model=None,
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language == "python":
            if ctx.python_ast is None:
                return []

            import ast

            imported: list[tuple[str, int]] = []

            def is_type_checking_test(expr: ast.AST) -> bool:
                if isinstance(expr, ast.Name) and expr.id == "TYPE_CHECKING":
                    return True
                if (
                    isinstance(expr, ast.Attribute)
                    and expr.attr == "TYPE_CHECKING"
                    and isinstance(expr.value, ast.Name)
                    and expr.value.id in {"typing"}
                ):
                    return True
                return False

            type_checking_import_lines: set[int] = set()
            for node in ast.walk(ctx.python_ast):
                if not isinstance(node, ast.If):
                    continue
                if not is_type_checking_test(node.test):
                    continue
                for child in ast.walk(node):
                    if isinstance(child, ast.Import | ast.ImportFrom) and hasattr(child, "lineno"):
                        type_checking_import_lines.add(int(getattr(child, "lineno", 0) or 0))

            for node in ast.walk(ctx.python_ast):
                if isinstance(node, ast.Import):
                    line_no = int(getattr(node, "lineno", 1))
                    if line_no in type_checking_import_lines:
                        continue
                    if ctx.path.name == "__init__.py" and int(getattr(node, "col_offset", 0) or 0) == 0:
                        continue
                    for alias in node.names:
                        name = alias.asname or alias.name.split(".", 1)[0]
                        imported.append((name, line_no))
                elif isinstance(node, ast.ImportFrom):
                    line_no = int(getattr(node, "lineno", 1))
                    if line_no in type_checking_import_lines:
                        continue
                    if ctx.path.name == "__init__.py" and int(getattr(node, "col_offset", 0) or 0) == 0:
                        continue
                    if node.module == "__future__":
                        continue
                    for alias in node.names:
                        if alias.name == "*":
                            continue
                        name = alias.asname or alias.name
                        imported.append((name, line_no))

            if not imported:
                return []

            def exported_names(tree: ast.AST) -> set[str]:
                exported: set[str] = set()

                def add_from_sequence(seq: ast.AST) -> None:
                    if not isinstance(seq, ast.List | ast.Tuple):
                        return
                    for elt in seq.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            exported.add(elt.value)

                for n in ast.walk(tree):
                    if isinstance(n, ast.Assign):
                        if any(isinstance(t, ast.Name) and t.id == "__all__" for t in n.targets):
                            add_from_sequence(n.value)
                    elif isinstance(n, ast.AnnAssign):
                        if isinstance(n.target, ast.Name) and n.target.id == "__all__" and n.value is not None:
                            add_from_sequence(n.value)

                return exported

            used_names: set[str] = set()
            for node in ast.walk(ctx.python_ast):
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                    used_names.add(node.id)
            used_names.update(exported_names(ctx.python_ast))

            violations = []
            for name, line_no in imported:
                if name not in used_names:
                    violations.append(
                        self._violation(
                            message=f"Imported name `{name}` is never used.",
                            suggestion="Remove the import or use it; avoid scaffolding leftovers.",
                            location=loc_from_line(ctx, line=line_no),
                        )
                    )
            return violations

        if ctx.language not in _JS_TS_LANGUAGES:
            return []

        spans, imported = _js_ts_import_spans_and_bindings(ctx.text)
        if not imported:
            return []

        haystack = _blank_out_spans(ctx.text, spans)
        used_bindings: set[str] = set()
        for name, _line_no in imported:
            if name == "React" and _looks_like_jsx(ctx):
                used_bindings.add(name)
                continue
            if re.search(rf"\b{re.escape(name)}\b", haystack):
                used_bindings.add(name)

        violations = []
        for name, line_no in sorted(imported, key=lambda t: (t[1], t[0])):
            if name not in used_bindings:
                violations.append(
                    self._violation(
                        message=f"Imported name `{name}` is never used.",
                        suggestion="Remove the import or use it; avoid scaffolding leftovers.",
                        location=loc_from_line(ctx, line=line_no),
                    )
                )
        return violations


@dataclass(frozen=True, slots=True)
class E04EmptyExceptBlock(BaseRule):
    meta = RuleMeta(
        rule_id="E04",
        title="Empty except block",
        description="Bare except/pass hides errors and makes debugging difficult.",
        default_severity="error",
        score_dimension="quality",
        fingerprint_model=None,
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "python" or ctx.python_ast is None:
            return []

        import ast

        violations = []
        for node in ast.walk(ctx.python_ast):
            if not isinstance(node, ast.ExceptHandler):
                continue

            is_bare = node.type is None
            is_broad = False
            if isinstance(node.type, ast.Name) and node.type.id in {"Exception", "BaseException"}:
                is_broad = True
            elif isinstance(node.type, ast.Tuple):
                for elt in node.type.elts:
                    if isinstance(elt, ast.Name) and elt.id in {"Exception", "BaseException"}:
                        is_broad = True
                        break

            if is_bare or is_broad:
                if len(node.body) != 1 or not hasattr(node, "lineno"):
                    continue

                stmt = node.body[0]
                empty_action: str | None = None
                if isinstance(stmt, ast.Pass):
                    empty_action = "pass"
                elif isinstance(stmt, ast.Continue):
                    empty_action = "continue"
                elif isinstance(stmt, ast.Return) and (
                    stmt.value is None or (isinstance(stmt.value, ast.Constant) and stmt.value.value is None)
                ):
                    empty_action = "return None"

                if empty_action is None:
                    continue

                caught = "except"
                if not is_bare and node.type is not None:
                    caught = f"except {ast.unparse(node.type)}"
                violations.append(
                    self._violation(
                        message=f"Found `{caught}: {empty_action}` (empty except block).",
                        suggestion="Catch specific exceptions and handle/log them, or re-raise.",
                        location=loc_from_line(ctx, line=int(node.lineno)),
                    )
                )
        return violations


@dataclass(frozen=True, slots=True)
class E05LongFunctionSignature(BaseRule):
    meta = RuleMeta(
        rule_id="E05",
        title="Long function signature",
        description="Functions with many parameters are harder to maintain and often indicate AI over-generalization.",
        default_severity="info",
        score_dimension="hallucination",
        fingerprint_model=None,
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "python" or ctx.python_ast is None:
            return []

        import ast

        violations = []
        for node in ast.walk(ctx.python_ast):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue

            args = node.args
            count = len(args.posonlyargs) + len(args.args) + len(args.kwonlyargs)
            if args.vararg is not None:
                count += 1
            if args.kwarg is not None:
                count += 1

            if count > 7 and hasattr(node, "lineno"):
                violations.append(
                    self._violation(
                        message=f"Function `{node.name}` has {count} parameters.",
                        suggestion="Group related parameters into a dataclass/object, or split responsibilities.",
                        location=loc_from_line(ctx, line=int(node.lineno)),
                    )
                )
        return violations


@dataclass(frozen=True, slots=True)
class E06RepeatedStringLiteral(BaseRule):
    """Detect repeated string literals that should be extracted into constants."""

    meta = RuleMeta(
        rule_id="E06",
        title="Repeated string literal",
        description="Repeated literals suggest missing constants/enums and can be AI scaffolding.",
        default_severity="warn",
        score_dimension="quality",
        fingerprint_model=None,
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language == "python":
            if ctx.python_ast is None:
                return []

            import ast

            def record_docstring_start(body: list[ast.stmt]) -> int | None:
                if not body:
                    return None
                first = body[0]
                if not isinstance(first, ast.Expr):
                    return None
                value = getattr(first, "value", None)
                if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
                    return None
                return int(getattr(first, "lineno", 0) or 0) or None

            docstring_starts: set[int] = set()
            if isinstance(ctx.python_ast, ast.Module):
                start = record_docstring_start(list(ctx.python_ast.body))
                if start is not None:
                    docstring_starts.add(start)
            for node in ast.walk(ctx.python_ast):
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                    start = record_docstring_start(list(node.body))
                    if start is not None:
                        docstring_starts.add(start)

            literals: dict[str, list[int]] = {}
            for node in ast.walk(ctx.python_ast):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    value = node.value
                    # Keep this conservative: short strings are often legitimate
                    # (e.g. "id", "ok") and extracting them into constants adds noise.
                    if len(value) < 6:
                        continue
                    line_no = int(getattr(node, "lineno", 1))
                    if line_no in docstring_starts:
                        continue
                    literals.setdefault(value, []).append(line_no)

            violations = []
            for value, lines in sorted(literals.items(), key=lambda kv: (min(kv[1]), kv[0])):
                if len(lines) >= 3:
                    violations.append(
                        self._violation(
                            message=f"String literal repeats {len(lines)} times: {value!r}",
                            suggestion="Extract repeated strings into a constant (or enum) to avoid drift.",
                            location=loc_from_line(ctx, line=min(lines)),
                        )
                    )
            return violations

        if ctx.language not in _JS_TS_LANGUAGES:
            return []

        spans: list[tuple[int, int]] = []
        for match in _JS_TS_IMPORT_FROM_RE.finditer(ctx.text):
            spans.append(match.span())
        for match in _JS_TS_IMPORT_SIDE_EFFECT_RE.finditer(ctx.text):
            spans.append(match.span())
        for match in _JS_TS_EXPORT_FROM_RE.finditer(ctx.text):
            spans.append(match.span())
        code = _blank_out_spans(ctx.text, spans)
        code = _blank_out_spans(code, [m.span() for m in _JS_TS_REQUIRE_IMPORT_CALL_RE.finditer(code)])

        literals = _js_ts_repeated_string_literals(code)
        violations = []
        for value, lines in sorted(literals.items(), key=lambda kv: (min(kv[1]), kv[0])):
            if len(value) < 6:
                continue
            if len(lines) >= 3:
                violations.append(
                    self._violation(
                        message=f"String literal repeats {len(lines)} times: {value!r}",
                        suggestion="Extract repeated strings into a constant (or enum) to avoid drift.",
                        location=loc_from_line(ctx, line=min(lines)),
                    )
                )
        return violations


@dataclass(frozen=True, slots=True)
class E07ExcessiveNesting(BaseRule):
    meta = RuleMeta(
        rule_id="E07",
        title="Excessive nesting",
        description="Deep nesting (>5 indentation levels) reduces readability.",
        default_severity="warn",
        score_dimension="maintainability",
        fingerprint_model=None,
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        max_level = 0
        max_line = None
        max_col = None

        for line_no, line in iter_code_lines(ctx):
            indent = 0
            for ch in line:
                if ch == " ":
                    indent += 1
                elif ch == "\t":
                    indent += 4
                else:
                    break
            level = indent // 4
            if level > max_level:
                max_level = level
                max_line = line_no
                max_col = indent + 1

        if max_level > 5 and max_line is not None:
            return [
                self._violation(
                    message=f"Indentation nesting is {max_level} levels deep (>5).",
                    suggestion="Refactor into smaller functions or reduce branching/loop nesting.",
                    location=loc_from_line(ctx, line=max_line, col=max_col),
                )
            ]
        return []


@dataclass(frozen=True, slots=True)
class E08IsinstanceChain(BaseRule):
    meta = RuleMeta(
        rule_id="E08",
        title="Repeated isinstance chain",
        description="Chaining 3+ `isinstance(x, T)` checks on the same value is noisy; prefer `isinstance(x, (A, B, C))`.",
        default_severity="info",
        score_dimension="maintainability",
        fingerprint_model=None,
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "python" or ctx.python_ast is None:
            return []

        import ast

        violations: list[Violation] = []
        for node in ast.walk(ctx.python_ast):
            if not isinstance(node, ast.BoolOp) or not isinstance(node.op, ast.Or):
                continue

            counts: dict[str, int] = {}
            first_line: dict[str, int] = {}
            for value in node.values:
                candidate = value
                if isinstance(candidate, ast.UnaryOp) and isinstance(candidate.op, ast.Not):
                    candidate = candidate.operand

                if not isinstance(candidate, ast.Call):
                    continue
                func = candidate.func
                if not isinstance(func, ast.Name) or func.id != "isinstance":
                    continue
                if len(candidate.args) < 2:
                    continue
                first_arg = candidate.args[0]
                if not isinstance(first_arg, ast.Name):
                    continue

                name = first_arg.id
                counts[name] = counts.get(name, 0) + 1
                candidate_line = int(getattr(candidate, "lineno", 0) or 0)
                if candidate_line > 0:
                    first_line.setdefault(name, candidate_line)

            for name, count in counts.items():
                if count < 3:
                    continue
                first_line_no = first_line.get(name)
                if first_line_no is None:
                    continue
                violations.append(
                    self._violation(
                        message=f"Found {count} `isinstance({name}, ...)` checks in the same `or` chain.",
                        suggestion=f"Use `isinstance({name}, (A, B, C))` to avoid repeated checks.",
                        location=loc_from_line(ctx, line=first_line_no),
                    )
                )

        return violations


@dataclass(frozen=True, slots=True)
class E09HardcodedCredential(BaseRule):
    meta = RuleMeta(
        rule_id="E09",
        title="Hardcoded credential",
        description="Assigning non-empty string literals to credential-like variables risks secret leakage.",
        default_severity="error",
        score_dimension="security",
        fingerprint_model=None,
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        rel_norm = ctx.relative_path.replace("\\", "/").lower()
        name = rel_norm.rsplit("/", 1)[-1]
        if (
            rel_norm.startswith("tests/")
            or "/tests/" in rel_norm
            or rel_norm.startswith("__tests__/")
            or "/__tests__/" in rel_norm
            or name.startswith("test_")
            or name.endswith((".test.js", ".spec.js", ".test.ts", ".spec.ts", ".test.tsx", ".spec.tsx"))
        ):
            return []

        if ctx.language == "python":
            if ctx.python_ast is None:
                return []

            import ast

            def record_hit(name: str, line: int, literal: str) -> Violation | None:
                if not _looks_like_credential_variable(name):
                    return None
                if not literal:
                    return None
                return self._violation(
                    message=f"Hardcoded credential-like value assigned to `{name}`.",
                    suggestion="Load secrets from environment variables or a secret manager; do not commit credentials to source control.",
                    location=loc_from_line(ctx, line=line),
                )

            violations: list[Violation] = []
            for node in ast.walk(ctx.python_ast):
                if isinstance(node, ast.Assign):
                    value = node.value
                    if not (isinstance(value, ast.Constant) and isinstance(value.value, str) and value.value):
                        continue
                    line = int(getattr(node, "lineno", 0) or 0)
                    if line <= 0:
                        continue
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            hit = record_hit(target.id, line, value.value)
                            if hit is not None:
                                violations.append(hit)
                elif isinstance(node, ast.AnnAssign):
                    if not isinstance(node.target, ast.Name) or node.value is None:
                        continue
                    value = node.value
                    if not (isinstance(value, ast.Constant) and isinstance(value.value, str) and value.value):
                        continue
                    line = int(getattr(node, "lineno", 0) or 0)
                    if line <= 0:
                        continue
                    hit = record_hit(node.target.id, line, value.value)
                    if hit is not None:
                        violations.append(hit)
                elif isinstance(node, ast.NamedExpr):
                    target = node.target
                    if not isinstance(target, ast.Name):
                        continue
                    value = node.value
                    if not (isinstance(value, ast.Constant) and isinstance(value.value, str) and value.value):
                        continue
                    line = int(getattr(node, "lineno", 0) or 0)
                    if line <= 0:
                        continue
                    hit = record_hit(target.id, line, value.value)
                    if hit is not None:
                        violations.append(hit)

            return violations

        if ctx.language in _JS_TS_LANGUAGES:
            hits = _js_ts_hardcoded_credential_assignments(ctx.text)
            return [
                self._violation(
                    message=f"Hardcoded credential-like value assigned to `{name}`.",
                    suggestion="Use environment variables or a secret manager; avoid committing secrets.",
                    location=loc_from_line(ctx, line=line),
                )
                for name, line in sorted(hits, key=lambda t: (t[1], t[0]))
            ]

        return []


@dataclass(frozen=True, slots=True)
class E10ExcessiveGuardClauses(BaseRule):
    """Detect excessive leading guard clauses.

    This rule focuses on *consecutive* guard clauses at the very start of a
    function. Guard clauses beyond the initial leading run are handled by E02.
    """

    meta = RuleMeta(
        rule_id="E10",
        title="Excessive guard clauses",
        description="Too many consecutive guard clauses at the start of a function harms readability.",
        default_severity="warn",
        score_dimension="quality",
        fingerprint_model=None,
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "python" or ctx.python_ast is None:
            return []

        import ast

        violations = []
        for node in ast.walk(ctx.python_ast):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue

            body = list(node.body)
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant):
                if isinstance(getattr(body[0].value, "value", None), str):
                    body = body[1:]

            consecutive = 0
            for stmt in body:
                if not isinstance(stmt, ast.If) or stmt.orelse:
                    break
                if not stmt.body:
                    break
                if isinstance(stmt.body[0], ast.Return | ast.Raise):
                    consecutive += 1
                    continue
                break

            if consecutive > 5 and hasattr(node, "lineno"):
                violations.append(
                    self._violation(
                        message=f"Function `{node.name}` starts with {consecutive} consecutive guard clauses.",
                        suggestion="Keep only essential guards; consolidate checks or restructure the function.",
                        location=loc_from_line(ctx, line=int(node.lineno)),
                    )
                )

        return violations


@dataclass(frozen=True, slots=True)
class E11RedundantBooleanReturn(BaseRule):
    """Detect redundant boolean return patterns like ``if x: return True else: return False``."""

    meta = RuleMeta(
        rule_id="E11",
        title="Redundant boolean return",
        description="Returning True/False from an if/else can be simplified to `return <condition>`.",
        default_severity="warn",
        score_dimension="quality",
        fingerprint_model=None,
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "python" or ctx.python_ast is None:
            return []

        import ast

        violations = []
        for node in ast.walk(ctx.python_ast):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for stmt in ast.walk(node):
                if not isinstance(stmt, ast.If):
                    continue
                if not stmt.orelse:
                    continue
                if len(stmt.body) != 1 or len(stmt.orelse) != 1:
                    continue
                body_stmt = stmt.body[0]
                else_stmt = stmt.orelse[0]
                if not isinstance(body_stmt, ast.Return) or not isinstance(else_stmt, ast.Return):
                    continue
                body_val = getattr(body_stmt, "value", None)
                else_val = getattr(else_stmt, "value", None)
                if not isinstance(body_val, ast.Constant) or not isinstance(else_val, ast.Constant):
                    continue
                if not isinstance(body_val.value, bool) or not isinstance(else_val.value, bool):
                    continue
                if body_val.value is True and else_val.value is False:
                    line = int(getattr(stmt, "lineno", 0) or 0)
                    if line > 0:
                        violations.append(
                            self._violation(
                                message="Redundant `if ...: return True else: return False`.",
                                suggestion="Simplify to `return <condition>` (or `return bool(<condition>)`).",
                                location=loc_from_line(ctx, line=line),
                            )
                        )
                elif body_val.value is False and else_val.value is True:
                    line = int(getattr(stmt, "lineno", 0) or 0)
                    if line > 0:
                        violations.append(
                            self._violation(
                                message="Redundant `if ...: return False else: return True`.",
                                suggestion="Simplify to `return not <condition>` (or `return not bool(<condition>)`).",
                                location=loc_from_line(ctx, line=line),
                            )
                        )
        return violations


@dataclass(frozen=True, slots=True)
class E12FunctionTooLong(BaseRule):
    meta = RuleMeta(
        rule_id="E12",
        title="Function too long",
        description="Functions with very large bodies are hard to review and maintain.",
        default_severity="warn",
        score_dimension="maintainability",
        fingerprint_model=None,
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "python" or ctx.python_ast is None:
            return []

        import ast

        violations: list[Violation] = []
        total_lines = len(ctx.lines)

        for node in ast.walk(ctx.python_ast):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if not node.body:
                continue

            start_line = int(getattr(node.body[0], "lineno", 0) or 0)
            end_line = int(getattr(node, "end_lineno", 0) or 0)
            if start_line <= 0 or end_line <= 0 or end_line < start_line:
                continue

            excluded_lines: set[int] = set()
            for stmt in node.body:
                if not isinstance(stmt, ast.Expr):
                    continue
                value = getattr(stmt, "value", None)
                if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
                    continue
                lit_start = int(getattr(stmt, "lineno", 0) or 0)
                lit_end = int(getattr(stmt, "end_lineno", lit_start) or lit_start)
                if lit_start <= 0 or lit_end <= 0:
                    continue
                excluded_lines.update(range(lit_start, lit_end + 1))

            code_lines = 0
            for line_no in range(start_line, end_line + 1):
                if line_no in excluded_lines:
                    continue
                if not (1 <= line_no <= total_lines):
                    continue
                line = ctx.lines[line_no - 1]
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith("#"):
                    continue
                code_lines += 1

            if code_lines > 80 and hasattr(node, "lineno"):
                violations.append(
                    self._violation(
                        message=f"Function `{node.name}` body is {code_lines} code lines long (>80).",
                        suggestion="Split into smaller functions; extract helpers and simplify control flow.",
                        location=loc_from_line(ctx, line=int(node.lineno)),
                    )
                )

        return violations


def builtin_generic_rules() -> list[BaseRule]:
    return [
        E01CommentCodeRatioAnomalous(),
        E02OverlyDefensiveProgramming(),
        E03UnusedImports(),
        E04EmptyExceptBlock(),
        E05LongFunctionSignature(),
        E06RepeatedStringLiteral(),
        E07ExcessiveNesting(),
        E08IsinstanceChain(),
        E09HardcodedCredential(),
        E10ExcessiveGuardClauses(),
        E11RedundantBooleanReturn(),
        E12FunctionTooLong(),
    ]
