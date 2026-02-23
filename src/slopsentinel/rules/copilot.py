from __future__ import annotations

import os
import re
import sys
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from slopsentinel.engine.context import FileContext
from slopsentinel.engine.types import Violation
from slopsentinel.patterns import LAST_UPDATE_RE
from slopsentinel.rules.base import BaseRule, RuleMeta, loc_from_line
from slopsentinel.rules.utils import iter_code_lines, iter_comment_lines

_EXAMPLE_USAGE_RE = re.compile(r"\bexample usage\b", re.IGNORECASE)
_DEBUG_PRINT_RE = re.compile(r"\bprint\(\s*f?['\"]DEBUG[:\s]", re.IGNORECASE)
_CONSOLE_DEBUG_CALL_RE = re.compile(r"\bconsole\.debug\s*\(")
_CONSOLE_WARN_DEBUG_PREFIX_RE = re.compile(r"\bconsole\.warn\s*\(\s*(['\"`])DEBUG(?:[:\s]|$)", re.IGNORECASE)

_REDUNDANT_COMMENT_VERBS = (
    "initialize",
    "create",
    "set up",
    "setup",
    "define",
    "declare",
    "construct",
)


@dataclass(frozen=True, slots=True)
class C01RedundantCommentRestatesCode(BaseRule):
    meta = RuleMeta(
        rule_id="C01",
        title="Redundant comment restates code",
        description="Comments that narrate obvious single-line code are typical AI artifacts.",
        default_severity="warn",
        score_dimension="fingerprint",
        fingerprint_model="copilot",
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        code_by_line = {line_no: line for line_no, line in iter_code_lines(ctx)}
        violations = []
        for line_no, line in iter_comment_lines(ctx):
            comment_text = _strip_comment_prefix(line).strip()
            if not comment_text:
                continue
            lowered = comment_text.lower()
            if "noqa" in lowered or "type: ignore" in lowered:
                continue
            if not any(v in lowered for v in _REDUNDANT_COMMENT_VERBS):
                continue

            next_line = None
            for offset in (1, 2):
                candidate = code_by_line.get(line_no + offset)
                if candidate is not None:
                    next_line = candidate
                    break
            if next_line is None:
                continue

            if _looks_like_trivial_init_pair(comment_text=comment_text, code_line=next_line):
                violations.append(
                    self._violation(
                        message="Comment appears to restate the next line of code.",
                        suggestion="Remove the comment or rewrite it to explain intent/invariants (not mechanics).",
                        location=loc_from_line(ctx, line=line_no),
                    )
                )
        return violations


@dataclass(frozen=True, slots=True)
class C02ExampleUsageDoctestBlock(BaseRule):
    meta = RuleMeta(
        rule_id="C02",
        title="Example Usage doctest block",
        description="In-function 'Example Usage' blocks are a common AI template artifact.",
        default_severity="info",
        score_dimension="fingerprint",
        fingerprint_model="copilot",
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        # Prefer comment/docstring-aware matching for Python.
        if ctx.language == "python" and ctx.python_ast is not None:
            import ast

            docstrings: list[tuple[int, int, str]] = []
            for node in ast.walk(ctx.python_ast):
                if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                    continue
                if not node.body:
                    continue
                first = node.body[0]
                if not isinstance(first, ast.Expr):
                    continue
                value = getattr(first, "value", None)
                if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
                    continue
                start = int(getattr(first, "lineno", 0) or 0)
                if start <= 0:
                    continue
                end = int(getattr(first, "end_lineno", start) or start)
                docstrings.append((start, max(start, end), value.value))

            def docstring_for_line(line_no: int) -> str | None:
                for start, end, text in docstrings:
                    if start <= line_no <= end:
                        return text
                return None

            def looks_like_structured_docstring(text: str) -> bool:
                lowered = text.lower()
                if ":param" in lowered or ":return" in lowered or ":raises" in lowered:
                    return True
                # Google-style sections.
                if re.search(r"(?m)^\s*(args|arguments|parameters|returns|raises)\s*:\s*$", text, flags=re.IGNORECASE):
                    return True
                # NumPy-style headings.
                if re.search(r"(?m)^\s*(parameters|returns|raises)\s*\n\s*-{3,}\s*$", text, flags=re.IGNORECASE):
                    return True
                return False

            for line_no, line in enumerate(ctx.lines, start=1):
                if not _EXAMPLE_USAGE_RE.search(line):
                    continue
                # Heuristic: require indentation to reduce noise in top-level README-like comments.
                if not line.startswith((" ", "\t")):
                    continue
                lstripped = line.lstrip()
                if lstripped.startswith("#"):
                    return [
                        self._violation(
                            message="Found an indented 'Example Usage' block.",
                            suggestion="Move usage examples to README/docs, or keep only brief examples in public APIs.",
                            location=loc_from_line(ctx, line=line_no),
                        )
                    ]

                doc = docstring_for_line(line_no)
                if doc is None:
                    continue
                if looks_like_structured_docstring(doc):
                    continue
                return [
                    self._violation(
                        message="Found an indented 'Example Usage' block.",
                        suggestion="Move usage examples to README/docs, or keep only brief examples in public APIs.",
                        location=loc_from_line(ctx, line=line_no),
                    )
                ]
            return []

        # Other languages: only consider actual comments.
        for line_no, line in iter_comment_lines(ctx):
            if not _EXAMPLE_USAGE_RE.search(line):
                continue
            if line.startswith((" ", "\t")):
                return [
                    self._violation(
                        message="Found an indented 'Example Usage' block.",
                        suggestion="Move usage examples to README/docs, or keep only brief examples in public APIs.",
                        location=loc_from_line(ctx, line=line_no),
                    )
                ]
        return []


@dataclass(frozen=True, slots=True)
class C03HallucinatedImport(BaseRule):
    meta = RuleMeta(
        rule_id="C03",
        title="Hallucinated import",
        description="Imports that don't exist in stdlib, installed packages, or the repo tree are high-risk.",
        default_severity="error",
        score_dimension="hallucination",
        fingerprint_model="copilot",
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "python" or ctx.python_ast is None:
            return []

        import ast

        known = _known_top_level_modules(ctx.project_root)
        optional_lines = _optional_import_lines(ctx.python_ast)
        violations = []

        for node in ast.walk(ctx.python_ast):
            if isinstance(node, ast.Import):
                if int(getattr(node, "lineno", 0) or 0) in optional_lines:
                    continue
                for alias in node.names:
                    top = alias.name.split(".", 1)[0]
                    if top and top not in known:
                        violations.append(
                            self._violation(
                                message=f"Imported module `{top}` not found in stdlib/declared deps/installed/local modules.",
                                suggestion="Remove the import or add the correct dependency/module.",
                                location=loc_from_line(ctx, line=int(getattr(node, 'lineno', 1))),
                            )
                        )
            elif isinstance(node, ast.ImportFrom):
                if int(getattr(node, "lineno", 0) or 0) in optional_lines:
                    continue
                if node.level and node.level > 0:
                    continue  # relative import
                if not node.module:
                    continue
                top = node.module.split(".", 1)[0]
                if top and top not in known:
                    violations.append(
                        self._violation(
                            message=f"Imported module `{top}` not found in stdlib/declared deps/installed/local modules.",
                            suggestion="Remove the import or add the correct dependency/module.",
                            location=loc_from_line(ctx, line=int(getattr(node, 'lineno', 1))),
                        )
                    )

        return violations


@dataclass(frozen=True, slots=True)
class C04OptionalOveruse(BaseRule):
    meta = RuleMeta(
        rule_id="C04",
        title="Overuse of Optional[...] annotations",
        description="Frequent Optional[...] annotations can indicate cargo-cult typing; prefer `T | None` on Python 3.10+.",
        default_severity="info",
        score_dimension="quality",
        fingerprint_model="copilot",
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "python" or ctx.python_ast is None:
            return []

        import ast

        def is_optional_subscript(node: ast.AST) -> bool:
            if not isinstance(node, ast.Subscript):
                return False
            value = node.value
            if isinstance(value, ast.Name) and value.id == "Optional":
                return True
            if isinstance(value, ast.Attribute) and value.attr == "Optional":
                return True
            return False

        count = 0
        first_line: int | None = None
        for node in ast.walk(ctx.python_ast):
            if not is_optional_subscript(node):
                continue
            count += 1
            if first_line is None and hasattr(node, "lineno"):
                first_line = int(getattr(node, "lineno", 0) or 0) or None

        if count < 5:
            return []

        return [
            self._violation(
                message=f"Found {count} Optional[...] annotations in one file.",
                suggestion="Prefer `T | None` (PEP 604) for readability on Python 3.10+, or reduce unnecessary Optional usage.",
                location=loc_from_line(ctx, line=first_line or 1),
            )
        ]


@dataclass(frozen=True, slots=True)
class C05OverlyGenericVariableNames(BaseRule):
    meta = RuleMeta(
        rule_id="C05",
        title="Overly generic variable names",
        description="Overuse of generic names (data/result/output/temp) reduces clarity.",
        default_severity="warn",
        score_dimension="fingerprint",
        fingerprint_model="copilot",
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "python" or ctx.python_ast is None:
            return []

        import ast

        targets = {"data", "result", "output", "temp"}
        violations = []

        for node in ast.walk(ctx.python_ast):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            counts = {t: 0 for t in targets}
            for child in ast.walk(node):
                if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load | ast.Store):
                    name = child.id
                    if name in counts:
                        counts[name] += 1
            for name, c in counts.items():
                if c >= 3:
                    violations.append(
                        self._violation(
                            message=f"Generic name `{name}` used {c} times in a single function.",
                            suggestion="Use a specific name that encodes meaning (e.g., `user_rows`, `parsed_payload`).",
                            location=loc_from_line(ctx, line=int(getattr(node, "lineno", 1))),
                        )
                    )
        return violations


@dataclass(frozen=True, slots=True)
class C06MissingReturnTypeAnnotation(BaseRule):
    meta = RuleMeta(
        rule_id="C06",
        title="Missing return type annotation",
        description="Public functions without return type annotations reduce readability and type-checking effectiveness.",
        default_severity="info",
        score_dimension="maintainability",
        fingerprint_model="copilot",
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "python" or ctx.python_ast is None:
            return []

        import ast

        def file_has_any_type_annotations(tree: ast.AST) -> bool:
            for node in ast.walk(tree):
                if isinstance(node, ast.AnnAssign):
                    return True
                if isinstance(node, ast.arg) and node.annotation is not None:
                    return True
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.returns is not None:
                    return True
            return False

        if not file_has_any_type_annotations(ctx.python_ast):
            return []

        violations: list[Violation] = []
        for node in getattr(ctx.python_ast, "body", []):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if node.name.startswith("_"):
                continue
            if node.returns is not None:
                continue
            if not hasattr(node, "lineno"):
                continue
            violations.append(
                self._violation(
                    message=f"Public function `{node.name}` has no return type annotation.",
                    suggestion="Add an explicit return type (e.g. `-> None`, `-> int`) to improve readability and type checking.",
                    location=loc_from_line(ctx, line=int(getattr(node, "lineno", 1))),
                )
            )
            if len(violations) >= 10:
                break

        return violations


@dataclass(frozen=True, slots=True)
class C07DebugPrintStatements(BaseRule):
    meta = RuleMeta(
        rule_id="C07",
        title="Debug print left in code",
        description="DEBUG prints are often left behind by AI scaffolding.",
        default_severity="warn",
        score_dimension="fingerprint",
        fingerprint_model="copilot",
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language == "python":
            if ctx.python_ast is None:
                return []

            import ast

            def is_debug_prefix(text: str) -> bool:
                if not text:
                    return False
                upper = text.upper()
                if not upper.startswith("DEBUG"):
                    return False
                if len(text) == 5:
                    return True
                return text[5] in {":", " ", "\t"}

            def arg_is_debug_string(arg: ast.AST) -> bool:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    return is_debug_prefix(arg.value.strip())
                if isinstance(arg, ast.JoinedStr) and arg.values:
                    first = arg.values[0]
                    if isinstance(first, ast.Constant) and isinstance(first.value, str):
                        return is_debug_prefix(first.value.strip())
                return False

            def is_logging_debug_call(func: ast.AST) -> bool:
                if not isinstance(func, ast.Attribute) or func.attr != "debug":
                    return False
                base = func.value
                return isinstance(base, ast.Name) and base.id in {"logging", "logger"}

            violations = []
            for node in ast.walk(ctx.python_ast):
                if not isinstance(node, ast.Call):
                    continue
                if not node.args:
                    continue
                func = node.func
                is_print = isinstance(func, ast.Name) and func.id == "print"
                if not is_print and not is_logging_debug_call(func):
                    continue
                if not arg_is_debug_string(node.args[0]):
                    continue
                if not hasattr(node, "lineno"):
                    continue
                violations.append(
                    self._violation(
                        message="Found a DEBUG debug output statement.",
                        suggestion="Remove debug output or gate it behind structured logging and a debug flag.",
                        location=loc_from_line(ctx, line=int(getattr(node, "lineno", 1))),
                    )
                )
            return violations

        if ctx.language in {"javascript", "typescript"}:
            rel = ctx.relative_path.replace("\\", "/").lower()
            name = rel.rsplit("/", 1)[-1]
            if (
                rel.startswith("tests/")
                or "/tests/" in rel
                or rel.startswith("__tests__/")
                or "/__tests__/" in rel
                or name.startswith("test_")
                or name.endswith((".test.js", ".spec.js", ".test.ts", ".spec.ts", ".test.tsx", ".spec.tsx"))
            ):
                return []

            for line_no, line in iter_code_lines(ctx):
                if _CONSOLE_DEBUG_CALL_RE.search(line) or _CONSOLE_WARN_DEBUG_PREFIX_RE.search(line):
                    return [
                        self._violation(
                            message="Found debug output via console.* in a non-test file.",
                            suggestion="Remove debug output or gate it behind a logger/debug flag.",
                            location=loc_from_line(ctx, line=line_no),
                        )
                    ]
            return []

        return []


@dataclass(frozen=True, slots=True)
class C08AnyOveruse(BaseRule):
    meta = RuleMeta(
        rule_id="C08",
        title="Overuse of Any",
        description="Repeated use of `Any` weakens type checking and often indicates AI-generated type scaffolding.",
        default_severity="warn",
        score_dimension="quality",
        fingerprint_model="copilot",
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "python" or ctx.python_ast is None:
            return []

        import ast

        any_imported = False
        for node in ast.walk(ctx.python_ast):
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.module not in {"typing", "typing_extensions"}:
                continue
            for alias in node.names:
                if alias.name == "Any" and (alias.asname is None or alias.asname == "Any"):
                    any_imported = True
                    break
            if any_imported:
                break

        if not any_imported:
            return []

        count = 0
        first_line: int | None = None
        for node in ast.walk(ctx.python_ast):
            if isinstance(node, ast.Name) and node.id == "Any":
                count += 1
                if first_line is None and hasattr(node, "lineno"):
                    first_line = int(getattr(node, "lineno", 0) or 0) or None

        if count < 5:
            return []

        return [
            self._violation(
                message=f"Found {count} uses of `Any` in one file.",
                suggestion="Replace `Any` with precise types, protocols, or generics to keep type checking meaningful.",
                location=loc_from_line(ctx, line=first_line or 1),
            )
        ]


@dataclass(frozen=True, slots=True)
class C09TrainingCutoffReference(BaseRule):
    meta = RuleMeta(
        rule_id="C09",
        title="Training cutoff reference",
        description="Comments referencing training data cutoff are clear AI artifacts.",
        default_severity="warn",
        score_dimension="fingerprint",
        fingerprint_model="copilot",
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        for line_no, line in iter_comment_lines(ctx):
            if LAST_UPDATE_RE.search(line):
                return [
                    self._violation(
                        message="Found a training-cutoff style comment ('as of my last update').",
                        suggestion="Remove the comment; document version constraints using real dependency versions instead.",
                        location=loc_from_line(ctx, line=line_no),
                    )
                ]
        return []


@dataclass(frozen=True, slots=True)
class C10ExceptionSwallowing(BaseRule):
    meta = RuleMeta(
        rule_id="C10",
        title="Exception swallowing (except Exception: pass)",
        description="Catching Exception and passing is a high-risk anti-pattern.",
        default_severity="error",
        score_dimension="security",
        fingerprint_model="copilot",
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "python" or ctx.python_ast is None:
            return []

        import ast

        violations = []
        for node in ast.walk(ctx.python_ast):
            if not isinstance(node, ast.ExceptHandler):
                continue
            if node.type is None:
                continue
            if isinstance(node.type, ast.Name) and node.type.id == "Exception":
                if len(node.body) == 1 and isinstance(node.body[0], ast.Pass) and hasattr(node, "lineno"):
                    violations.append(
                        self._violation(
                            message="Found `except Exception: pass` (swallows all exceptions).",
                            suggestion="Catch specific exceptions and handle them explicitly (or re-raise).",
                            location=loc_from_line(ctx, line=int(node.lineno)),
                        )
                    )
        return violations


@dataclass(frozen=True, slots=True)
class C11LongLambdaExpression(BaseRule):
    meta = RuleMeta(
        rule_id="C11",
        title="Overly long lambda expression",
        description="Very long lambda expressions are hard to read and often indicate AI-generated inline scaffolding.",
        default_severity="info",
        score_dimension="maintainability",
        fingerprint_model="copilot",
    )

    def check_file(self, ctx: FileContext) -> list[Violation]:
        if ctx.language != "python" or ctx.python_ast is None:
            return []

        import ast

        violations: list[Violation] = []
        for node in ast.walk(ctx.python_ast):
            if not isinstance(node, ast.Lambda):
                continue
            segment = ast.get_source_segment(ctx.text, node)
            if segment is None:
                continue
            if len(segment) <= 60:
                continue
            line_no = int(getattr(node, "lineno", 0) or 0) or 1
            violations.append(
                self._violation(
                    message=f"Lambda expression is {len(segment)} characters long.",
                    suggestion="Extract the lambda into a named function for readability and testability.",
                    location=loc_from_line(ctx, line=line_no),
                )
            )
            if len(violations) >= 10:
                break
        return violations


def builtin_copilot_rules() -> list[BaseRule]:
    return [
        C01RedundantCommentRestatesCode(),
        C02ExampleUsageDoctestBlock(),
        C03HallucinatedImport(),
        C04OptionalOveruse(),
        C05OverlyGenericVariableNames(),
        C06MissingReturnTypeAnnotation(),
        C07DebugPrintStatements(),
        C08AnyOveruse(),
        C09TrainingCutoffReference(),
        C10ExceptionSwallowing(),
        C11LongLambdaExpression(),
    ]


def _strip_comment_prefix(line: str) -> str:
    stripped = line.lstrip()
    if stripped.startswith("#"):
        return stripped[1:]
    if stripped.startswith("//"):
        return stripped[2:]
    if stripped.startswith("/*"):
        return stripped[2:]
    if stripped.startswith("*"):
        return stripped[1:]
    return stripped


_PY_ASSIGN_RE = re.compile(r"^\s*(?P<name>[A-Za-z_]\w*)\s*=\s*(?P<rhs>.+)$")
_JS_DECL_RE = re.compile(r"^\s*(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*(?P<rhs>.+)$")
_JS_ASSIGN_RE = re.compile(r"^\s*(?P<name>[A-Za-z_$][\w$]*)\s*=\s*(?P<rhs>.+)$")


def _looks_like_trivial_init_pair(*, comment_text: str, code_line: str) -> bool:
    c = comment_text.lower()
    rhs = code_line.strip()

    var_name: str | None = None
    m = _PY_ASSIGN_RE.match(rhs) or _JS_DECL_RE.match(rhs) or _JS_ASSIGN_RE.match(rhs)
    if m:
        var_name = m.group("name")
        rhs = m.group("rhs").strip()

    empty_collection = rhs in {"[]", "{}", "dict()", "list()", "set()"} or rhs.startswith("[]") or rhs.startswith("{}")
    if not empty_collection:
        return False

    if "empty" not in c and "blank" not in c and "initialize" not in c:
        return False

    if var_name and var_name.lower() in c:
        return True

    # Fallback: common phrasing even without mentioning the variable.
    return "initialize" in c and "empty" in c


@lru_cache(maxsize=64)
def _known_top_level_modules(project_root: Path) -> frozenset[str]:
    known: set[str] = set()

    # Stdlib
    known.update(getattr(sys, "stdlib_module_names", set()))

    # Declared dependencies (best-effort). This matters for CI/Action use where
    # the target project's deps are typically not installed in the runner env.
    known.update(_declared_dependency_modules(project_root))

    # Installed packages (best-effort): enumerate importable top-level modules
    # once per process. `importlib.metadata.packages_distributions()` is often
    # surprisingly expensive, so prefer `pkgutil.iter_modules()` when possible.
    known.update(_installed_top_level_modules())

    # Local modules: scan `src/` (if present) and then project root excluding
    # `src/` to avoid double-walking large trees.
    known.update(_local_top_level_modules(project_root))

    return frozenset(known)


@lru_cache(maxsize=1)
def _installed_top_level_modules() -> frozenset[str]:
    try:
        import pkgutil

        return frozenset({m.name for m in pkgutil.iter_modules()})
    except (ImportError, OSError, RuntimeError):  # pragma: no cover
        pass

    try:  # pragma: no cover (fallback for unusual import setups)
        import importlib.metadata as importlib_metadata

        return frozenset(importlib_metadata.packages_distributions().keys())
    except (ImportError, OSError, RuntimeError):
        return frozenset()


_LOCAL_MODULE_SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
}


def _dir_contains_python_files(path: Path) -> bool:
    for _, dirnames, filenames in os.walk(path):
        dirnames[:] = [d for d in dirnames if d not in _LOCAL_MODULE_SKIP_DIRS]
        for filename in filenames:
            if filename.endswith(".py"):
                return True
    return False


def _top_level_modules_in(root: Path, *, exclude_dir_name: str | None = None) -> set[str]:
    modules: set[str] = set()
    try:
        with os.scandir(root) as it:
            for entry in it:
                name = entry.name
                if name in _LOCAL_MODULE_SKIP_DIRS:
                    continue
                if exclude_dir_name is not None and name == exclude_dir_name:
                    continue

                try:
                    if entry.is_file() and name.endswith(".py"):
                        stem = Path(name).stem
                        if stem != "__init__":
                            modules.add(stem)
                        continue

                    if entry.is_dir() and _dir_contains_python_files(Path(entry.path)):
                        modules.add(name)
                except OSError:
                    continue
    except OSError:
        return set()

    return modules


@lru_cache(maxsize=64)
def _local_top_level_modules(project_root: Path) -> frozenset[str]:
    src = project_root / "src"
    modules: set[str] = set()

    if src.is_dir():
        modules.update(_top_level_modules_in(src))
        modules.update(_top_level_modules_in(project_root, exclude_dir_name="src"))
    else:
        modules.update(_top_level_modules_in(project_root))

    return frozenset(modules)


def _optional_import_lines(tree: object) -> set[int]:
    import ast

    if not isinstance(tree, ast.AST):
        return set()

    def handles_import_error(node: ast.Try) -> bool:
        for handler in node.handlers:
            if handler.type is None:
                return True
            exc = handler.type
            names: list[str] = []
            if isinstance(exc, ast.Name):
                names = [exc.id]
            elif isinstance(exc, ast.Tuple):
                for elt in exc.elts:
                    if isinstance(elt, ast.Name):
                        names.append(elt.id)
            if any(n in {"ImportError", "ModuleNotFoundError"} for n in names):
                return True
        return False

    optional: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        if not handles_import_error(node):
            continue
        for stmt in node.body:
            for child in ast.walk(stmt):
                if isinstance(child, ast.Import | ast.ImportFrom) and hasattr(child, "lineno"):
                    optional.add(int(getattr(child, "lineno", 0) or 0))
    return optional


_REQUIREMENT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*")


@lru_cache(maxsize=64)
def _declared_dependency_modules(project_root: Path) -> frozenset[str]:
    out: set[str] = set()

    pyproject_path = project_root / "pyproject.toml"
    if pyproject_path.exists():
        try:
            with pyproject_path.open("rb") as f:
                data = tomllib.load(f)
        except (OSError, tomllib.TOMLDecodeError):
            data = {}

        project = data.get("project")
        if isinstance(project, dict):
            deps = project.get("dependencies", [])
            if isinstance(deps, list):
                out.update(_names_from_dependency_list(deps))
            optional = project.get("optional-dependencies", {})
            if isinstance(optional, dict):
                for group_deps in optional.values():
                    if isinstance(group_deps, list):
                        out.update(_names_from_dependency_list(group_deps))

        tool = data.get("tool")
        if isinstance(tool, dict):
            poetry = tool.get("poetry")
            if isinstance(poetry, dict):
                for key in ("dependencies", "dev-dependencies"):
                    table = poetry.get(key, {})
                    if isinstance(table, dict):
                        out.update(_names_from_dependency_table(table))
                groups = poetry.get("group", {})
                if isinstance(groups, dict):
                    for group in groups.values():
                        if not isinstance(group, dict):
                            continue
                        table = group.get("dependencies", {})
                        if isinstance(table, dict):
                            out.update(_names_from_dependency_table(table))

    for filename in ("requirements.txt", "requirements-dev.txt", "requirements.in", "requirements-dev.in"):
        path = project_root / filename
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for raw_line in text.splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if not line or line.startswith("-"):
                continue
            m = _REQUIREMENT_NAME_RE.match(line)
            if not m:
                continue
            out.update(_normalize_dist_to_modules(m.group(0)))

    return frozenset(out)


def _names_from_dependency_list(values: list[object]) -> set[str]:
    names: set[str] = set()
    for item in values:
        if not isinstance(item, str):
            continue
        m = _REQUIREMENT_NAME_RE.match(item.strip())
        if not m:
            continue
        names.update(_normalize_dist_to_modules(m.group(0)))
    return names


def _names_from_dependency_table(table: dict[object, object]) -> set[str]:
    names: set[str] = set()
    for raw_key in table:
        if not isinstance(raw_key, str):
            continue
        key = raw_key.strip()
        if not key or key.lower() == "python":
            continue
        names.update(_normalize_dist_to_modules(key))
    return names


def _normalize_dist_to_modules(dist_name: str) -> set[str]:
    """
    Best-effort mapping from distribution names to plausible import roots.

    This errs on the side of reducing false positives in CI (missing runtime deps).
    """

    base = dist_name.strip()
    if not base:
        return set()

    out = {base, base.replace("-", "_")}
    if "-" in base:
        out.add(base.split("-", 1)[0])
    return out
