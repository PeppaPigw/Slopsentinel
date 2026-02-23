from __future__ import annotations

import re

from slopsentinel.engine.context import FileContext
from slopsentinel.engine.types import Violation
from slopsentinel.rules.base import BaseRule, RuleMeta, loc_from_line
from slopsentinel.rules.utils import iter_code_lines

_GO_FUNC_DEF_RE = re.compile(r"^\s*func\s*(?:\([^)]*\)\s*)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\(")
_RUST_FN_DEF_RE = re.compile(
    r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\("
)

_GO_ERROR_LITERAL_RE = re.compile(
    r"""\b(?:errors\.New|fmt\.Errorf)\(\s*(?:"(?P<dbl>[^"]+)"|`(?P<raw>[^`]+)`)""",
    re.VERBOSE,
)
_GO_DEBUG_PRINT_RE = re.compile(r"\b(?:fmt|log)\.(?:Println|Printf|Print)\s*\(")
_GO_CONTEXT_TODO_RE = re.compile(r"\bcontext\.TODO\s*\(\s*\)")
_GO_TIME_SLEEP_RE = re.compile(r"\btime\.Sleep\s*\(")
_GO_IDENT_LIST_PATTERN = r"[A-Za-z_][A-Za-z0-9_]*(?:\s*,\s*[A-Za-z_][A-Za-z0-9_]*)*"
_GO_VAR_DECL_RE = re.compile(rf"^\s*var\s+(?P<lhs>{_GO_IDENT_LIST_PATTERN})\b")
_GO_VAR_BLOCK_START_RE = re.compile(r"^\s*var\s*\(\s*$")
_GO_SHORT_DECL_RE = re.compile(rf"^\s*(?P<lhs>{_GO_IDENT_LIST_PATTERN})\s*:=\s*")
_GO_ASSIGN_RE = re.compile(rf"^\s*(?P<lhs>{_GO_IDENT_LIST_PATTERN})\s*=\s*(?!=)")
_GO_COMPOUND_ASSIGN_RE = re.compile(r"^\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(?:\+=|-=|\*=|/=|%=|&=|\|=|\^=|<<=|>>=)\s*")
_GO_INC_DEC_RE = re.compile(r"^\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(?:\+\+|--)\s*$")
_GO_TWO_DIGIT_INT_RE = re.compile(r"\b[1-9][0-9]+\b")

_RUST_UNWRAP_RE = re.compile(r"\.\s*unwrap\s*\(\s*\)")
_RUST_EXPECT_RE = re.compile(r"\.\s*expect\s*\(")
_RUST_TODO_RE = re.compile(r"\b(?:todo|unimplemented)!\s*\(")
_RUST_DBG_RE = re.compile(r"\bdbg!\s*\(")
_RUST_PRINTLN_RE = re.compile(r"\bprintln!\s*\(")
_RUST_UNSAFE_RE = re.compile(r"\bunsafe\b")
_RUST_PANIC_RE = re.compile(r"\bpanic!\s*\(")
_RUST_CLONE_ON_COPY_REF_RE = re.compile(r"\(\s*&\s*(?!mut\b)[^)]+\)\s*\.\s*clone\s*\(\s*\)")
_RUST_CLONE_ON_COPY_BOOL_RE = re.compile(r"(?<!\.)\b(?:true|false)\b\s*\.\s*clone\s*\(\s*\)")
_RUST_CLONE_ON_COPY_INT_RE = re.compile(
    r"(?<!\.)\b\d+(?:_\d+)*\s*(?:[iu]\d+|usize|isize)?\b\s*\.\s*clone\s*\(\s*\)"
)
_RUST_CLONE_ON_COPY_CHAR_RE = re.compile(r"'(?:\\.|[^'\\])'\s*\.\s*clone\s*\(\s*\)")
_RUST_CLONE_ON_COPY_STR_RE = re.compile(r"\"(?:\\.|[^\"\\])*\"\s*\.\s*clone\s*\(\s*\)")

_JAVA_SYSTEM_OUT_RE = re.compile(r"\bSystem\.(?:out|err)\.println\s*\(")
_JAVA_RETURN_NULL_RE = re.compile(r"\breturn\s+null\s*;")
_JAVA_NULLABILITY_ANNOT_RE = re.compile(r"@\s*(?:Nullable|CheckForNull)\b")
_JAVA_CATCH_OPEN_RE = re.compile(r"\bcatch\s*\([^)]*\)\s*\{")
_KOTLIN_TODO_RE = re.compile(r"\bTODO\s*\(")
_KOTLIN_NONNULL_ASSERT_RE = re.compile(r"!!")
_KOTLIN_PRINTLN_RE = re.compile(r"\bprintln\s*\(")
_RUBY_DEBUGGER_RE = re.compile(r"\b(?:binding\.pry|byebug|debugger)\b")
_RUBY_PUTS_OR_P_RE = re.compile(r"^\s*(?:puts|p)\b")
_RUBY_RAISE_RUNTIME_ERROR_RE = re.compile(r"\braise\s*(?:\(|\s+)RuntimeError\b")
_PHP_DEBUG_RE = re.compile(r"\b(?:var_dump|print_r)\s*\(")
_PHP_DIE_EXIT_RE = re.compile(r"\b(?:die|exit)\b\s*(?:\(\s*)?(?:'[^'\n]*'|\"[^\"\n]*\"|0\b)\s*(?:\))?")
_PHP_EVAL_RE = re.compile(r"\beval\s*\(")


def _pair_create_delete(name: str) -> tuple[str, str] | None:
    if name.startswith("create_"):
        return name, "delete_" + name.removeprefix("create_")
    if name.startswith("add_"):
        return name, "remove_" + name.removeprefix("add_")
    if name.startswith("Create") and len(name) > len("Create"):
        return name, "Delete" + name.removeprefix("Create")
    if name.startswith("Add") and len(name) > len("Add"):
        return name, "Remove" + name.removeprefix("Add")
    return None


def _unused_symmetric_pairs(ctx: FileContext, *, defined: dict[str, int]) -> list[tuple[str, str, int]]:
    if not defined:
        return []

    haystack = "\n".join(line for _line_no, line in iter_code_lines(ctx))

    used: set[str] = set()
    for name in defined:
        # Consider a function "used" only if it appears at least twice as a
        # call-like token: once for its definition (`func Name(` / `fn name(`)
        # and at least once more elsewhere.
        pattern = re.compile(rf"\b{re.escape(name)}\s*\(")
        hits = 0
        for _m in pattern.finditer(haystack):
            hits += 1
            if hits >= 2:
                used.add(name)
                break

    pairs: list[tuple[str, str, int]] = []
    for name in defined:
        pair = _pair_create_delete(name)
        if pair is None:
            continue
        a, b = pair
        if b not in defined:
            continue
        if a in used or b in used:
            continue
        pairs.append((a, b, min(defined[a], defined[b])))

    # Deterministic output.
    return sorted(pairs, key=lambda t: (t[2], t[0], t[1]))


def _is_go_test_file(ctx: FileContext) -> bool:
    return ctx.path.name.endswith("_test.go")


def _is_rust_test_file(ctx: FileContext) -> bool:
    if ctx.path.name.endswith("_test.rs"):
        return True
    rel = ctx.relative_path.replace("\\", "/")
    if rel.startswith("tests/") or "/tests/" in rel:
        return True
    return any("cfg(test)" in line for line in ctx.lines) or any("mod tests" in line for line in ctx.lines)


def _is_java_test_file(ctx: FileContext) -> bool:
    name = ctx.path.name
    if name.endswith(("Test.java", "Tests.java")):
        return True
    rel = ctx.relative_path.replace("\\", "/")
    padded = f"/{rel}/"
    return "/test/" in padded or "/tests/" in padded


def _is_kotlin_test_file(ctx: FileContext) -> bool:
    name = ctx.path.name
    if name.endswith(("Test.kt", "Tests.kt")):
        return True
    rel = ctx.relative_path.replace("\\", "/")
    padded = f"/{rel}/"
    return "/test/" in padded or "/tests/" in padded


def _is_ruby_test_file(ctx: FileContext) -> bool:
    name = ctx.path.name
    if name.startswith("test_") or name.endswith(("_test.rb", "_spec.rb")):
        return True
    rel = ctx.relative_path.replace("\\", "/")
    padded = f"/{rel}/"
    return "/test/" in padded or "/tests/" in padded or "/spec/" in padded


def _is_php_test_file(ctx: FileContext) -> bool:
    name = ctx.path.name
    if name.startswith("test_") or name.endswith(("Test.php", "Tests.php")):
        return True
    rel = ctx.relative_path.replace("\\", "/")
    padded = f"/{rel}/"
    return "/test/" in padded or "/tests/" in padded


def _split_ident_list(text: str) -> list[str]:
    return [part.strip() for part in text.split(",") if part.strip()]


def _blank_out_kotlin_strings(line: str, *, in_triple: bool) -> tuple[str, bool]:
    """
    Replace Kotlin string/char literal contents with whitespace.

    This is a lightweight heuristic so regex-based rules (e.g. `!!`) don't
    trigger on string contents. It supports triple-quoted strings spanning
    multiple lines.
    """

    out: list[str] = []
    i = 0
    n = len(line)
    while i < n:
        if in_triple:
            if line.startswith('"""', i):
                out.append("   ")
                i += 3
                in_triple = False
                continue
            out.append(" ")
            i += 1
            continue

        if line.startswith('"""', i):
            out.append("   ")
            i += 3
            in_triple = True
            continue

        ch = line[i]
        if ch == '"':
            out.append(" ")
            i += 1
            while i < n:
                ch2 = line[i]
                if ch2 == "\\" and i + 1 < n:
                    out.append("  ")
                    i += 2
                    continue
                out.append(" ")
                i += 1
                if ch2 == '"':
                    break
            continue
        if ch == "'":
            out.append(" ")
            i += 1
            while i < n:
                ch2 = line[i]
                if ch2 == "\\" and i + 1 < n:
                    out.append("  ")
                    i += 2
                    continue
                out.append(" ")
                i += 1
                if ch2 == "'":
                    break
            continue

        out.append(ch)
        i += 1

    return "".join(out), in_triple


def _go_package_level_var_names(ctx: FileContext) -> set[str]:
    """
    Collect package-level `var` identifiers for a Go file.

    This intentionally ignores vars declared inside functions.
    """

    names: set[str] = set()
    in_var_block = False
    in_func = False
    pending_func = False
    func_depth = 0

    for _line_no, line in iter_code_lines(ctx):
        if in_func:
            func_depth += line.count("{") - line.count("}")
            if func_depth <= 0:
                in_func = False
            continue

        if pending_func:
            if "{" in line:
                brace_idx = line.find("{")
                func_depth = line[brace_idx:].count("{") - line[brace_idx:].count("}")
                pending_func = False
                in_func = True
                if func_depth <= 0:
                    in_func = False
            continue

        if _GO_FUNC_DEF_RE.match(line):
            pending_func = True
            if "{" in line:
                brace_idx = line.find("{")
                func_depth = line[brace_idx:].count("{") - line[brace_idx:].count("}")
                pending_func = False
                in_func = True
                if func_depth <= 0:
                    in_func = False
            continue

        if in_var_block:
            if line.strip().startswith(")"):
                in_var_block = False
                continue
            m_entry = re.match(rf"^\s*(?P<lhs>{_GO_IDENT_LIST_PATTERN})\b", line)
            if m_entry:
                names.update(_split_ident_list(m_entry.group("lhs")))
            continue

        if _GO_VAR_BLOCK_START_RE.match(line):
            in_var_block = True
            continue

        m_decl = _GO_VAR_DECL_RE.match(line)
        if m_decl:
            names.update(_split_ident_list(m_decl.group("lhs")))

    return names


def _go_first_global_mutation(ctx: FileContext, *, global_vars: set[str]) -> tuple[int, str] | None:
    if not global_vars:
        return None

    def mutation_in_statement(statement: str) -> str | None:
        stmt = statement.strip()
        if not stmt:
            return None

        m_short = _GO_SHORT_DECL_RE.match(stmt)
        if m_short:
            local_vars.update(_split_ident_list(m_short.group("lhs")))
            return None

        m_local_var = _GO_VAR_DECL_RE.match(stmt)
        if m_local_var:
            local_vars.update(_split_ident_list(m_local_var.group("lhs")))
            return None

        m_inc = _GO_INC_DEC_RE.match(stmt)
        if m_inc:
            name = m_inc.group("name")
            if name in global_vars and name not in local_vars:
                return name
            return None

        m_compound = _GO_COMPOUND_ASSIGN_RE.match(stmt)
        if m_compound:
            name = m_compound.group("name")
            if name in global_vars and name not in local_vars:
                return name
            return None

        m_assign = _GO_ASSIGN_RE.match(stmt)
        if m_assign:
            for name in _split_ident_list(m_assign.group("lhs")):
                if name in global_vars and name not in local_vars:
                    return name
        return None

    def mutation_in_inline_body(line: str, *, brace_idx: int) -> str | None:
        tail = line[brace_idx + 1 :]
        if "}" in tail:
            tail = tail.split("}", 1)[0]
        for stmt in tail.split(";"):
            hit = mutation_in_statement(stmt)
            if hit is not None:
                return hit
        return None

    in_func = False
    pending_func = False
    func_depth = 0
    func_name: str | None = None
    local_vars: set[str] = set()
    in_local_var_block = False

    for line_no, line in iter_code_lines(ctx):
        if not in_func and not pending_func:
            m_func = _GO_FUNC_DEF_RE.match(line)
            if m_func:
                func_name = m_func.group("name")
                local_vars = set()
                in_local_var_block = False
                pending_func = True
                if "{" in line:
                    brace_idx = line.find("{")
                    func_depth = line[brace_idx:].count("{") - line[brace_idx:].count("}")
                    pending_func = False
                    in_func = True
                    if func_name != "init":
                        hit = mutation_in_inline_body(line, brace_idx=brace_idx)
                        if hit is not None:
                            return int(line_no), hit
                    if func_depth <= 0:
                        in_func = False
                        func_name = None
                continue

        if pending_func:
            if "{" in line:
                brace_idx = line.find("{")
                func_depth = line[brace_idx:].count("{") - line[brace_idx:].count("}")
                pending_func = False
                in_func = True
                if func_name != "init":
                    hit = mutation_in_inline_body(line, brace_idx=brace_idx)
                    if hit is not None:
                        return int(line_no), hit
                if func_depth <= 0:
                    in_func = False
                    func_name = None
            continue

        if not in_func:
            continue

        if func_name != "init":
            if in_local_var_block:
                if line.strip().startswith(")"):
                    in_local_var_block = False
                else:
                    m_entry = re.match(rf"^\s*(?P<lhs>{_GO_IDENT_LIST_PATTERN})\b", line)
                    if m_entry:
                        local_vars.update(_split_ident_list(m_entry.group("lhs")))
                func_depth += line.count("{") - line.count("}")
                if func_depth <= 0:
                    in_func = False
                    func_name = None
                continue

            if _GO_VAR_BLOCK_START_RE.match(line):
                in_local_var_block = True
                func_depth += line.count("{") - line.count("}")
                if func_depth <= 0:
                    in_func = False
                    func_name = None
                continue

            hit = mutation_in_statement(line)
            if hit is not None:
                return int(line_no), hit

        func_depth += line.count("{") - line.count("}")
        if func_depth <= 0:
            in_func = False
            func_name = None

    return None


class G01GoSymmetricCreateDeleteUnused(BaseRule):
    meta = RuleMeta(
        rule_id="G01",
        title="Symmetric create/delete pair unused (Go)",
        description="AI-generated Go code often includes symmetric CRUD helpers even when unused.",
        default_severity="warn",
        score_dimension="quality",
        fingerprint_model=None,
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "go":
            return []

        defined: dict[str, int] = {}
        for line_no, line in iter_code_lines(ctx):
            m = _GO_FUNC_DEF_RE.match(line)
            if not m:
                continue
            defined[m.group("name")] = int(line_no)

        pairs = _unused_symmetric_pairs(ctx, defined=defined)
        return [
            self._violation(
                message=f"Found symmetric function pair `{a}`/`{b}` with no in-file calls.",
                suggestion="Remove unused symmetry or add tests/usages that justify both functions.",
                location=loc_from_line(ctx, line=line_no),
            )
            for a, b, line_no in pairs
        ]


class G02GoNonIdiomaticErrorString(BaseRule):
    meta = RuleMeta(
        rule_id="G02",
        title="Non-idiomatic error string (Go)",
        description="Go error strings should not be capitalized or end with punctuation; AI-generated code often violates this convention.",
        default_severity="warn",
        score_dimension="maintainability",
        fingerprint_model=None,
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "go":
            return []

        violations: list[Violation] = []
        for line_no, line in iter_code_lines(ctx):
            m = _GO_ERROR_LITERAL_RE.search(line)
            if not m:
                continue
            msg = (m.group("dbl") or m.group("raw") or "").strip()
            if not msg:
                continue
            if msg.startswith("%"):
                continue

            first = msg[0]
            ends_punct = msg.endswith((".", "!", "?"))
            starts_cap = first.isalpha() and first.upper() == first and first.lower() != first
            if not (starts_cap or ends_punct):
                continue

            violations.append(
                self._violation(
                    message="Go error strings should start with a lowercase letter and not end with punctuation.",
                    suggestion="Prefer lowercased, punctuation-free messages (e.g. \"failed to ...\").",
                    location=loc_from_line(ctx, line=int(line_no)),
                )
            )
        return violations


class G03GoDebugPrintStatements(BaseRule):
    meta = RuleMeta(
        rule_id="G03",
        title="Debug print statements (Go)",
        description="Debug prints like fmt.Println(\"DEBUG...\") are common AI scaffolding and should not ship to production.",
        default_severity="warn",
        score_dimension="quality",
        fingerprint_model=None,
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "go":
            return []
        if _is_go_test_file(ctx):
            return []

        for line_no, line in iter_code_lines(ctx):
            if not _GO_DEBUG_PRINT_RE.search(line):
                continue
            if re.search(r"(?i)\"[^\"]*(debug|todo|fixme)[^\"]*\"", line):
                return [
                    self._violation(
                        message="Found a debug print statement.",
                        suggestion="Remove debug prints or replace with structured logging behind a debug flag.",
                        location=loc_from_line(ctx, line=int(line_no)),
                    )
                ]
        return []


class G04GoContextTodoUsed(BaseRule):
    meta = RuleMeta(
        rule_id="G04",
        title="context.TODO() used (Go)",
        description="context.TODO() is a placeholder that frequently slips into AI-generated code.",
        default_severity="warn",
        score_dimension="maintainability",
        fingerprint_model=None,
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "go":
            return []
        if _is_go_test_file(ctx):
            return []

        for line_no, line in iter_code_lines(ctx):
            if _GO_CONTEXT_TODO_RE.search(line):
                return [
                    self._violation(
                        message="Found `context.TODO()` placeholder.",
                        suggestion="Thread a real context through call sites or use context.Background() only at top-level.",
                        location=loc_from_line(ctx, line=int(line_no)),
                    )
                ]
        return []


class G05GoTimeSleepUsed(BaseRule):
    meta = RuleMeta(
        rule_id="G05",
        title="time.Sleep used (Go)",
        description="time.Sleep in application code is often a flaky workaround used in AI-generated scaffolding.",
        default_severity="info",
        score_dimension="quality",
        fingerprint_model=None,
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "go":
            return []
        if _is_go_test_file(ctx):
            return []

        for line_no, line in iter_code_lines(ctx):
            if _GO_TIME_SLEEP_RE.search(line):
                return [
                    self._violation(
                        message="Found `time.Sleep(...)` usage.",
                        suggestion="Prefer explicit synchronization, timeouts, or retry backoff utilities instead of fixed sleeps.",
                        location=loc_from_line(ctx, line=int(line_no)),
                    )
                ]
        return []


class G06GoGlobalVarMutation(BaseRule):
    meta = RuleMeta(
        rule_id="G06",
        title="Global variable mutation (Go)",
        description="Mutating package-level variables is a common AI shortcut that introduces hidden state and potential races.",
        default_severity="warn",
        score_dimension="quality",
        fingerprint_model=None,
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "go":
            return []
        if _is_go_test_file(ctx):
            return []

        global_vars = _go_package_level_var_names(ctx)
        hit = _go_first_global_mutation(ctx, global_vars=global_vars)
        if hit is None:
            return []
        line_no, name = hit
        return [
            self._violation(
                message=f"Found mutation of package-level variable `{name}`.",
                suggestion="Prefer passing state explicitly (structs/interfaces) instead of mutating global vars.",
                location=loc_from_line(ctx, line=line_no),
            )
        ]


class G07GoMagicNumbers(BaseRule):
    meta = RuleMeta(
        rule_id="G07",
        title="Repeated magic numbers (Go)",
        description="Repeated multi-digit numeric literals often indicate AI-generated scaffolding; prefer named constants.",
        default_severity="info",
        score_dimension="maintainability",
        fingerprint_model=None,
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "go":
            return []
        if _is_go_test_file(ctx):
            return []

        in_const_block = False
        counts: dict[str, int] = {}
        first_line: dict[str, int] = {}

        for line_no, line in iter_code_lines(ctx):
            stripped = line.lstrip()
            if in_const_block:
                if stripped.startswith(")"):
                    in_const_block = False
                continue

            if stripped.startswith("const"):
                if "(" in stripped and ")" not in stripped:
                    in_const_block = True
                continue

            for m in _GO_TWO_DIGIT_INT_RE.finditer(line):
                lit = m.group(0)
                counts[lit] = counts.get(lit, 0) + 1
                first_line.setdefault(lit, int(line_no))

        # Conservative: only flag when a multi-digit literal repeats several times.
        for lit, count in sorted(counts.items(), key=lambda t: (-t[1], t[0])):
            if count >= 4:
                return [
                    self._violation(
                        message=f"Found repeated magic number `{lit}` used {count} times.",
                        suggestion="Extract a named constant (const) to document intent and avoid repetition.",
                        location=loc_from_line(ctx, line=first_line[lit]),
                    )
                ]

        return []


class R01RustSymmetricCreateDeleteUnused(BaseRule):
    meta = RuleMeta(
        rule_id="R01",
        title="Symmetric create/delete pair unused (Rust)",
        description="AI-generated Rust code often includes symmetric CRUD helpers even when unused.",
        default_severity="warn",
        score_dimension="quality",
        fingerprint_model=None,
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "rust":
            return []

        defined: dict[str, int] = {}
        for line_no, line in iter_code_lines(ctx):
            stripped = line.strip()
            # Skip trait signatures (`fn foo(&self);`) which are declarations, not definitions.
            if stripped.endswith(";"):
                continue
            m = _RUST_FN_DEF_RE.match(line)
            if not m:
                continue
            defined[m.group("name")] = int(line_no)

        pairs = _unused_symmetric_pairs(ctx, defined=defined)
        return [
            self._violation(
                message=f"Found symmetric function pair `{a}`/`{b}` with no in-file calls.",
                suggestion="Remove unused symmetry or add tests/usages that justify both functions.",
                location=loc_from_line(ctx, line=line_no),
            )
            for a, b, line_no in pairs
        ]


class R02RustExcessiveUnwrapExpect(BaseRule):
    meta = RuleMeta(
        rule_id="R02",
        title="Excessive unwrap/expect (Rust)",
        description="Frequent `.unwrap()`/`.expect(...)` in non-test Rust code is a common AI shortcut that reduces robustness.",
        default_severity="warn",
        score_dimension="security",
        fingerprint_model=None,
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "rust":
            return []
        if _is_rust_test_file(ctx):
            return []

        hits = 0
        first_line: int | None = None
        for line_no, line in iter_code_lines(ctx):
            if _RUST_UNWRAP_RE.search(line) or _RUST_EXPECT_RE.search(line):
                hits += 1
                if first_line is None:
                    first_line = int(line_no)
        if hits >= 3 and first_line is not None:
            return [
                self._violation(
                    message="Found 3+ uses of `.unwrap()`/`.expect(...)` in a single file.",
                    suggestion="Prefer `?` with error types, or handle the error explicitly.",
                    location=loc_from_line(ctx, line=first_line),
                )
            ]
        return []


class R03RustTodoMacros(BaseRule):
    meta = RuleMeta(
        rule_id="R03",
        title="todo!/unimplemented! macro used (Rust)",
        description="`todo!()` and `unimplemented!()` are placeholders that should not ship.",
        default_severity="warn",
        score_dimension="quality",
        fingerprint_model=None,
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "rust":
            return []
        for line_no, line in iter_code_lines(ctx):
            if _RUST_TODO_RE.search(line):
                return [
                    self._violation(
                        message="Found `todo!()`/`unimplemented!()` placeholder macro.",
                        suggestion="Implement the missing logic or replace with a tracked issue + explicit error.",
                        location=loc_from_line(ctx, line=int(line_no)),
                    )
                ]
        return []


class R04RustDebugMacros(BaseRule):
    meta = RuleMeta(
        rule_id="R04",
        title="Debug macros (Rust)",
        description="`dbg!` and println!-based debug logging often indicates AI scaffolding that should be removed or gated.",
        default_severity="warn",
        score_dimension="quality",
        fingerprint_model=None,
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "rust":
            return []
        if _is_rust_test_file(ctx):
            return []

        for line_no, line in iter_code_lines(ctx):
            if _RUST_DBG_RE.search(line):
                return [
                    self._violation(
                        message="Found `dbg!(...)` debug macro.",
                        suggestion="Remove dbg! or replace with structured logging behind a feature flag.",
                        location=loc_from_line(ctx, line=int(line_no)),
                    )
                ]
            if _RUST_PRINTLN_RE.search(line) and re.search(r"(?i)\"[^\"]*(debug|todo|fixme)[^\"]*\"", line):
                return [
                    self._violation(
                        message="Found a debug println! statement.",
                        suggestion="Remove debug println! or use logging with levels.",
                        location=loc_from_line(ctx, line=int(line_no)),
                    )
                ]
        return []


class R05RustUnsafeUsed(BaseRule):
    meta = RuleMeta(
        rule_id="R05",
        title="unsafe used (Rust)",
        description="Unnecessary `unsafe` in AI-generated code can introduce memory safety risks.",
        default_severity="info",
        score_dimension="security",
        fingerprint_model=None,
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "rust":
            return []
        for line_no, line in iter_code_lines(ctx):
            if _RUST_UNSAFE_RE.search(line):
                return [
                    self._violation(
                        message="Found `unsafe` usage.",
                        suggestion="Prefer safe abstractions; when unsafe is required, document safety invariants and add tests.",
                        location=loc_from_line(ctx, line=int(line_no)),
                    )
                ]
        return []


class R06RustCloneOnCopyTypes(BaseRule):
    meta = RuleMeta(
        rule_id="R06",
        title="Redundant clone on Copy-like values (Rust)",
        description="Cloning primitives/references is often an AI pattern; Copy types can be copied without `.clone()`.",
        default_severity="info",
        score_dimension="maintainability",
        fingerprint_model=None,
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "rust":
            return []
        if _is_rust_test_file(ctx):
            return []

        for line_no, line in iter_code_lines(ctx):
            if ".clone" not in line:
                continue
            if (
                _RUST_CLONE_ON_COPY_REF_RE.search(line)
                or _RUST_CLONE_ON_COPY_BOOL_RE.search(line)
                or _RUST_CLONE_ON_COPY_INT_RE.search(line)
                or _RUST_CLONE_ON_COPY_CHAR_RE.search(line)
                or _RUST_CLONE_ON_COPY_STR_RE.search(line)
            ):
                return [
                    self._violation(
                        message="Found `.clone()` on a Copy-like value.",
                        suggestion="Remove `.clone()` for Copy types; use the value directly or copy it implicitly.",
                        location=loc_from_line(ctx, line=int(line_no)),
                    )
                ]
        return []


class R07RustPanicMacroUsed(BaseRule):
    meta = RuleMeta(
        rule_id="R07",
        title="panic! macro used (Rust)",
        description="`panic!()` indicates unrecoverable failure; AI-generated code often leaves panics in production paths.",
        default_severity="warn",
        score_dimension="quality",
        fingerprint_model=None,
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "rust":
            return []
        if _is_rust_test_file(ctx):
            return []

        for line_no, line in iter_code_lines(ctx):
            if _RUST_PANIC_RE.search(line):
                return [
                    self._violation(
                        message="Found `panic!(...)` usage.",
                        suggestion="Prefer returning a Result/Option or handling the error explicitly.",
                        location=loc_from_line(ctx, line=int(line_no)),
                    )
                ]
        return []


class J01JavaDebugPrintStatements(BaseRule):
    meta = RuleMeta(
        rule_id="J01",
        title="Debug print statements (Java)",
        description="System.out/err debug prints often indicate scaffolding that should be replaced with proper logging.",
        default_severity="warn",
        score_dimension="quality",
        fingerprint_model=None,
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "java":
            return []
        for line_no, line in iter_code_lines(ctx):
            if _JAVA_SYSTEM_OUT_RE.search(line) and re.search(r"(?i)\"[^\"]*(debug|todo|fixme)[^\"]*\"", line):
                return [
                    self._violation(
                        message="Found a debug System.out/err print statement.",
                        suggestion="Remove debug prints or replace with a logger configured per environment.",
                        location=loc_from_line(ctx, line=int(line_no)),
                    )
                ]
        return []


class J02JavaNullableReturnHeuristic(BaseRule):
    meta = RuleMeta(
        rule_id="J02",
        title="Trivial null-returning method (Java)",
        description="AI-generated Java code often includes stub methods that only `return null;`, leading to nullable APIs.",
        default_severity="warn",
        score_dimension="quality",
        fingerprint_model=None,
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "java":
            return []
        if _is_java_test_file(ctx):
            return []
        if _JAVA_NULLABILITY_ANNOT_RE.search(ctx.text):
            return []

        code_lines = list(iter_code_lines(ctx))
        for idx, (line_no, line) in enumerate(code_lines):
            if "return" not in line:
                continue
            if not _JAVA_RETURN_NULL_RE.search(line):
                continue

            stripped = line.strip()
            # One-liner stub: `Type f() { return null; }`
            if "{" in stripped and "}" in stripped and re.search(r"\)\s*\{", stripped) and "return null" in stripped:
                return [
                    self._violation(
                        message="Found a trivial method that returns null.",
                        suggestion="Avoid null returns; throw a specific exception, return Optional, or implement the method.",
                        location=loc_from_line(ctx, line=int(line_no)),
                    )
                ]

            # Multi-line stub:
            #   Type f() {
            #       return null;
            #   }
            if idx == 0 or idx + 1 >= len(code_lines):
                continue
            prev = code_lines[idx - 1][1].strip()
            nxt = code_lines[idx + 1][1].lstrip()
            if prev.endswith("{") and re.search(r"\)\s*\{$", prev) and (nxt == "}" or nxt.startswith("} ")):
                return [
                    self._violation(
                        message="Found a trivial method that returns null.",
                        suggestion="Avoid null returns; throw a specific exception, return Optional, or implement the method.",
                        location=loc_from_line(ctx, line=int(line_no)),
                    )
                ]

        return []


class J03JavaEmptyCatchBlock(BaseRule):
    meta = RuleMeta(
        rule_id="J03",
        title="Empty catch block (Java)",
        description="Empty `catch` blocks silently swallow failures; AI-generated code often includes them.",
        default_severity="warn",
        score_dimension="quality",
        fingerprint_model=None,
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "java":
            return []
        if _is_java_test_file(ctx):
            return []

        code_lines = list(iter_code_lines(ctx))
        for idx, (line_no, line) in enumerate(code_lines):
            m = _JAVA_CATCH_OPEN_RE.search(line)
            if not m:
                continue

            brace_idx = line.find("{", m.start())
            if brace_idx != -1 and "}" in line[brace_idx:]:
                between = line[brace_idx + 1 : line.rfind("}")]
                # Remove simple inline comments.
                between = re.sub(r"//.*$", "", between)
                between = re.sub(r"/\*.*?\*/", "", between)
                if not between.strip():
                    return [
                        self._violation(
                            message="Found an empty catch block.",
                            suggestion="Handle the exception (log/return/propagate) or rethrow a specific error.",
                            location=loc_from_line(ctx, line=int(line_no)),
                        )
                    ]
                continue

            if idx + 1 >= len(code_lines):
                continue
            next_line = code_lines[idx + 1][1].lstrip()
            if next_line.startswith("}"):
                tail = next_line[1:].lstrip()
                if not tail or tail.startswith(("catch", "finally")):
                    return [
                        self._violation(
                            message="Found an empty catch block.",
                            suggestion="Handle the exception (log/return/propagate) or rethrow a specific error.",
                            location=loc_from_line(ctx, line=int(line_no)),
                        )
                    ]

        return []


class K01KotlinTodoUsed(BaseRule):
    meta = RuleMeta(
        rule_id="K01",
        title="TODO() used (Kotlin)",
        description="Kotlin's TODO() call is a placeholder that should not ship.",
        default_severity="warn",
        score_dimension="quality",
        fingerprint_model=None,
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "kotlin":
            return []
        for line_no, line in iter_code_lines(ctx):
            if _KOTLIN_TODO_RE.search(line):
                return [
                    self._violation(
                        message="Found `TODO(...)` placeholder.",
                        suggestion="Implement the missing logic or replace with an explicit exception + tracking issue.",
                        location=loc_from_line(ctx, line=int(line_no)),
                    )
                ]
        return []


class K02KotlinNonNullAssertionUsed(BaseRule):
    meta = RuleMeta(
        rule_id="K02",
        title="Non-null assertion used (Kotlin)",
        description="Kotlin's `!!` is a common AI shortcut that can cause runtime crashes; prefer safe null handling.",
        default_severity="warn",
        score_dimension="quality",
        fingerprint_model=None,
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "kotlin":
            return []
        if _is_kotlin_test_file(ctx):
            return []

        in_triple = False
        in_block_comment = False
        for line_no, raw in enumerate(ctx.lines, start=1):
            line, in_triple = _blank_out_kotlin_strings(raw, in_triple=in_triple)
            stripped = line.strip()
            if not stripped:
                continue

            lstripped = line.lstrip()
            if in_block_comment:
                if "*/" in lstripped:
                    in_block_comment = False
                continue
            if lstripped.startswith("//"):
                continue
            if lstripped.startswith("/*"):
                if "*/" not in lstripped:
                    in_block_comment = True
                continue

            if _KOTLIN_NONNULL_ASSERT_RE.search(line):
                return [
                    self._violation(
                        message="Found Kotlin non-null assertion operator `!!`.",
                        suggestion="Prefer safe calls (`?.`), Elvis operator (`?:`), or explicit null checks.",
                        location=loc_from_line(ctx, line=line_no),
                    )
                ]

        return []


class K03KotlinPrintlnDebug(BaseRule):
    meta = RuleMeta(
        rule_id="K03",
        title="Debug println (Kotlin)",
        description="println(\"DEBUG...\") statements often indicate AI scaffolding that should be removed or gated.",
        default_severity="warn",
        score_dimension="quality",
        fingerprint_model=None,
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "kotlin":
            return []
        if _is_kotlin_test_file(ctx):
            return []

        for line_no, line in iter_code_lines(ctx):
            if not _KOTLIN_PRINTLN_RE.search(line):
                continue
            if re.search(r"(?i)\"[^\"]*(debug|todo|fixme)[^\"]*\"", line):
                return [
                    self._violation(
                        message="Found a debug println statement.",
                        suggestion="Remove println debugging or replace with structured logging behind a debug flag.",
                        location=loc_from_line(ctx, line=int(line_no)),
                    )
                ]
        return []


class Y01RubyDebuggersPresent(BaseRule):
    meta = RuleMeta(
        rule_id="Y01",
        title="Debugger statements present (Ruby)",
        description="Ruby debugger hooks like `binding.pry` frequently leak from AI-assisted development.",
        default_severity="warn",
        score_dimension="quality",
        fingerprint_model=None,
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "ruby":
            return []
        for line_no, line in iter_code_lines(ctx):
            if _RUBY_DEBUGGER_RE.search(line):
                return [
                    self._violation(
                        message="Found a Ruby debugger statement.",
                        suggestion="Remove debugger hooks before merging; use logging or tests to validate behavior.",
                        location=loc_from_line(ctx, line=int(line_no)),
                    )
                ]
        return []


class Y02RubyDebugOutput(BaseRule):
    meta = RuleMeta(
        rule_id="Y02",
        title="Debug output via puts/p (Ruby)",
        description="Debug output like `puts \"DEBUG\"` or `p \"TODO\"` is common AI scaffolding and should not ship.",
        default_severity="warn",
        score_dimension="quality",
        fingerprint_model=None,
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "ruby":
            return []
        if _is_ruby_test_file(ctx):
            return []

        for line_no, line in iter_code_lines(ctx):
            if not _RUBY_PUTS_OR_P_RE.match(line):
                continue
            if re.search(r"(?i)[\"'][^\"']*(debug|todo|fixme)[^\"']*[\"']", line):
                return [
                    self._violation(
                        message="Found Ruby debug output via puts/p.",
                        suggestion="Remove debug output or replace with a logger guarded by environment/config.",
                        location=loc_from_line(ctx, line=int(line_no)),
                    )
                ]
        return []


class Y03RubyRaiseRuntimeError(BaseRule):
    meta = RuleMeta(
        rule_id="Y03",
        title="raise RuntimeError (Ruby)",
        description="Raising RuntimeError explicitly is often an AI default; prefer a specific exception type with context.",
        default_severity="info",
        score_dimension="maintainability",
        fingerprint_model=None,
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "ruby":
            return []
        if _is_ruby_test_file(ctx):
            return []

        for line_no, line in iter_code_lines(ctx):
            if _RUBY_RAISE_RUNTIME_ERROR_RE.search(line):
                return [
                    self._violation(
                        message="Found `raise RuntimeError ...` usage.",
                        suggestion="Raise a specific exception class (custom or standard) to preserve intent and handling.",
                        location=loc_from_line(ctx, line=int(line_no)),
                    )
                ]
        return []


class P01PhpDebugFunctions(BaseRule):
    meta = RuleMeta(
        rule_id="P01",
        title="Debug functions used (PHP)",
        description="Debug helpers like var_dump/print_r are often left in AI-generated PHP code.",
        default_severity="warn",
        score_dimension="quality",
        fingerprint_model=None,
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "php":
            return []
        for line_no, line in iter_code_lines(ctx):
            if _PHP_DEBUG_RE.search(line):
                return [
                    self._violation(
                        message="Found `var_dump(...)`/`print_r(...)` debug output.",
                        suggestion="Remove debug output or guard it behind environment-specific logging.",
                        location=loc_from_line(ctx, line=int(line_no)),
                    )
                ]
        return []


class P02PhpDieExitUsed(BaseRule):
    meta = RuleMeta(
        rule_id="P02",
        title="die/exit used with message (PHP)",
        description="Using die()/exit() with a string message is often AI scaffolding that abruptly terminates execution.",
        default_severity="warn",
        score_dimension="quality",
        fingerprint_model=None,
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "php":
            return []
        if _is_php_test_file(ctx):
            return []

        for line_no, line in iter_code_lines(ctx):
            if _PHP_DIE_EXIT_RE.search(line):
                return [
                    self._violation(
                        message="Found `die(...)`/`exit(...)` used with a string message.",
                        suggestion="Prefer proper error handling (exceptions/return codes) and centralized logging.",
                        location=loc_from_line(ctx, line=int(line_no)),
                    )
                ]
        return []


class P03PhpEvalUsed(BaseRule):
    meta = RuleMeta(
        rule_id="P03",
        title="eval used (PHP)",
        description="eval() is a dangerous dynamic execution primitive; it frequently appears in AI-generated quick fixes.",
        default_severity="warn",
        score_dimension="security",
        fingerprint_model=None,
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "php":
            return []
        if _is_php_test_file(ctx):
            return []

        for line_no, line in iter_code_lines(ctx):
            if _PHP_EVAL_RE.search(line):
                return [
                    self._violation(
                        message="Found `eval(...)` usage.",
                        suggestion="Avoid eval; use safer parsing/dispatch mechanisms and validate all inputs.",
                        location=loc_from_line(ctx, line=int(line_no)),
                    )
                ]
        return []


def builtin_polyglot_rules() -> list[BaseRule]:
    return [
        G01GoSymmetricCreateDeleteUnused(),
        G02GoNonIdiomaticErrorString(),
        G03GoDebugPrintStatements(),
        G04GoContextTodoUsed(),
        G05GoTimeSleepUsed(),
        G06GoGlobalVarMutation(),
        G07GoMagicNumbers(),
        R01RustSymmetricCreateDeleteUnused(),
        R02RustExcessiveUnwrapExpect(),
        R03RustTodoMacros(),
        R04RustDebugMacros(),
        R05RustUnsafeUsed(),
        R06RustCloneOnCopyTypes(),
        R07RustPanicMacroUsed(),
        J01JavaDebugPrintStatements(),
        J02JavaNullableReturnHeuristic(),
        J03JavaEmptyCatchBlock(),
        K01KotlinTodoUsed(),
        K02KotlinNonNullAssertionUsed(),
        K03KotlinPrintlnDebug(),
        Y01RubyDebuggersPresent(),
        Y02RubyDebugOutput(),
        Y03RubyRaiseRuntimeError(),
        P01PhpDebugFunctions(),
        P02PhpDieExitUsed(),
        P03PhpEvalUsed(),
    ]
