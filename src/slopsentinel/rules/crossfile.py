from __future__ import annotations

import ast
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from slopsentinel.engine.context import ProjectContext
from slopsentinel.engine.types import Location, Violation
from slopsentinel.languages.registry import detect_language
from slopsentinel.rules.base import BaseRule, RuleMeta
from slopsentinel.utils import safe_relpath


def _repo_loc(_: ProjectContext) -> Location:
    return Location(path=None, start_line=None, start_col=None)


def _normalize_code_lines(text: str) -> tuple[str, ...]:
    """
    Best-effort normalization for duplicate detection.

    This intentionally avoids language-specific parsing: it strips blank lines
    and comment-only lines for common comment styles, and collapses whitespace.
    """

    lines = text.splitlines()
    out: list[str] = []
    in_block_comment = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        lstripped = line.lstrip()
        if in_block_comment:
            if "*/" in lstripped:
                in_block_comment = False
            continue

        if lstripped.startswith(("#", "//")):
            continue
        if lstripped.startswith("/*"):
            if "*/" not in lstripped:
                in_block_comment = True
            continue

        out.append(" ".join(stripped.split()))

    return tuple(out)


def _code_fingerprint(text: str) -> tuple[str, int]:
    normalized = _normalize_code_lines(text)
    raw = "\n".join(normalized).encode("utf-8", errors="replace")
    return sha256(raw).hexdigest(), len(normalized)


def _filename_style(stem: str) -> str:
    if re.fullmatch(r"[a-z][a-z0-9_]*", stem):
        return "snake"
    if re.fullmatch(r"[a-z][a-z0-9-]*", stem) and "-" in stem:
        return "kebab"
    if re.fullmatch(r"[a-z][A-Za-z0-9]*", stem) and any(c.isupper() for c in stem):
        return "camel"
    if re.fullmatch(r"[A-Z][A-Za-z0-9]*", stem):
        return "pascal"
    return "other"


def _rel_posix(path: Path, root: Path) -> str:
    return safe_relpath(path, root).replace("\\", "/")


def _src_py_to_module(rel: str) -> tuple[str, bool] | None:
    rel_norm = rel.replace("\\", "/")
    if not rel_norm.startswith("src/"):
        return None
    if not rel_norm.endswith(".py"):
        return None

    rel_path = Path(rel_norm)
    if rel_path.name == "__init__.py":
        parts = list(rel_path.parts[1:-1])  # drop src/ and __init__.py
        if not parts:
            return None
        return ".".join(parts), True

    parts = list(rel_path.parts[1:])  # drop src/
    if not parts:
        return None
    parts[-1] = Path(parts[-1]).stem
    return ".".join(parts), False


def _module_package(module: str, *, is_package: bool) -> str:
    if is_package:
        return module
    if "." in module:
        return module.rsplit(".", 1)[0]
    return ""


def _tarjan_scc(graph: dict[str, set[str]]) -> list[list[str]]:
    """
    Tarjan strongly-connected components (SCC) algorithm.

    Returns a list of components; components of size >1 imply at least one cycle.
    """

    index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    out: list[list[str]] = []

    def strongconnect(v: str) -> None:
        nonlocal index
        indices[v] = index
        lowlinks[v] = index
        index += 1
        stack.append(v)
        on_stack.add(v)

        for w in sorted(graph.get(v, set())):
            if w not in indices:
                strongconnect(w)
                lowlinks[v] = min(lowlinks[v], lowlinks[w])
            elif w in on_stack:
                lowlinks[v] = min(lowlinks[v], indices[w])

        if lowlinks[v] == indices[v]:
            component: list[str] = []
            while True:
                w = stack.pop()
                on_stack.remove(w)
                component.append(w)
                if w == v:
                    break
            out.append(component)

    for v in sorted(graph):
        if v not in indices:
            strongconnect(v)

    return out


def _find_cycle_path(nodes: set[str], graph: dict[str, set[str]]) -> list[str] | None:
    """
    Find a single representative cycle path within `nodes`.

    Returns a list like ["a", "b", "c", "a"] or None if no cycle is found.
    """

    visited: set[str] = set()
    stack: list[str] = []
    stack_index: dict[str, int] = {}

    def dfs(u: str) -> list[str] | None:
        visited.add(u)
        stack_index[u] = len(stack)
        stack.append(u)

        for v in sorted(graph.get(u, set())):
            if v not in nodes:
                continue
            if v not in visited:
                res = dfs(v)
                if res is not None:
                    return res
            elif v in stack_index:
                start = stack_index[v]
                return stack[start:] + [v]

        stack.pop()
        stack_index.pop(u, None)
        return None

    for start in sorted(nodes):
        if start in visited:
            continue
        res = dfs(start)
        if res is not None:
            return res

    return None


def _expected_test_for_src_module(rel: str) -> str | None:
    rel_norm = rel.replace("\\", "/")
    if not rel_norm.startswith("src/"):
        return None
    if not rel_norm.endswith(".py"):
        return None

    rel_path = Path(rel_norm)
    if rel_path.name in {"__init__.py", "__main__.py"}:
        return None
    if rel_path.name.startswith("test_"):
        return None
    if rel_path.stem.startswith("_"):
        return None
    if rel_path.name.endswith(("_pb2.py", "_pb2_grpc.py")):
        return None

    exempt_dirs = {"vendor", "third_party", "migrations", "generated", "gen"}
    if any(part in exempt_dirs for part in rel_path.parts):
        return None

    parts = list(rel_path.parts[1:])  # drop src/
    if not parts:
        return None
    parts[-1] = Path(parts[-1]).stem
    module_id = "_".join(parts)
    if not module_id:
        return None
    return f"tests/test_{module_id}.py"


@dataclass(frozen=True, slots=True)
class X01CrossFileDuplicateCode(BaseRule):
    meta = RuleMeta(
        rule_id="X01",
        title="Duplicate code across files",
        description="Exact or near-exact copy/paste across multiple files often indicates AI scaffolding or cargo-cult duplication.",
        default_severity="warn",
        score_dimension="maintainability",
        fingerprint_model=None,
    )

    def check_project(self, ctx: ProjectContext) -> list[Violation]:
        by_fp: dict[str, list[str]] = defaultdict(list)
        line_counts: dict[str, int] = {}

        for path in ctx.files:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            fp, line_count = _code_fingerprint(text)
            # Keep false positives low by requiring a minimum size.
            if line_count < 20:
                continue
            rel = safe_relpath(path, ctx.project_root)
            by_fp[fp].append(rel)
            line_counts[fp] = line_count

        violations: list[Violation] = []
        for fp, files in sorted(by_fp.items(), key=lambda t: (-len(t[1]), t[0])):
            if len(files) < 2:
                continue
            examples = ", ".join(sorted(files)[:5])
            suffix = "..." if len(files) > 5 else ""
            violations.append(
                self._violation(
                    message=f"Found duplicated code across {len(files)} files ({line_counts.get(fp, 0)}+ lines): {examples}{suffix}",
                    suggestion="Extract shared logic into a helper/module or delete redundant files.",
                    location=_repo_loc(ctx),
                )
            )
            if len(violations) >= 10:
                break

        return violations


@dataclass(frozen=True, slots=True)
class X02CrossFileNamingConsistency(BaseRule):
    meta = RuleMeta(
        rule_id="X02",
        title="Inconsistent filename style",
        description="Mixed naming styles in the same directory/language can indicate AI-generated scaffolding and makes repos harder to navigate.",
        default_severity="info",
        score_dimension="maintainability",
        fingerprint_model=None,
    )

    def check_project(self, ctx: ProjectContext) -> list[Violation]:
        by_group: dict[tuple[str, str], list[str]] = defaultdict(list)

        for path in ctx.files:
            lang = detect_language(path)
            if lang is None:
                continue
            rel = safe_relpath(path, ctx.project_root).replace("\\", "/")
            group = (str(Path(rel).parent), lang)
            by_group[group].append(Path(rel).stem)

        violations: list[Violation] = []
        for (directory, language), stems in sorted(by_group.items()):
            if len(stems) < 4:
                continue
            styles = [_filename_style(stem) for stem in stems]
            counts = Counter(s for s in styles if s != "other")
            if len([c for c in counts.values() if c >= 2]) < 2:
                continue

            summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
            violations.append(
                self._violation(
                    message=f"Mixed filename styles in {directory or '.'} for {language}: {summary}",
                    suggestion="Pick one naming convention per language+directory (e.g. snake_case for Python, PascalCase for Java).",
                    location=_repo_loc(ctx),
                )
            )

        return violations


@dataclass(frozen=True, slots=True)
class X03PythonStructureFingerprintClusters(BaseRule):
    meta = RuleMeta(
        rule_id="X03",
        title="Repeated Python file structure",
        description="Many Python files with identical structural skeletons can indicate AI-generated scaffolding across a repo.",
        default_severity="warn",
        score_dimension="fingerprint",
        fingerprint_model=None,
    )

    def check_project(self, ctx: ProjectContext) -> list[Violation]:
        import ast

        def is_test_path(rel: str) -> bool:
            rel_norm = rel.replace("\\", "/")
            return rel_norm.startswith("tests/") or "/tests/" in rel_norm or Path(rel_norm).name.startswith("test_")

        class Skeletonize(ast.NodeTransformer):
            def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
                node.name = "_"
                return self.generic_visit(node)

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
                node.name = "_"
                return self.generic_visit(node)

            def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:
                node.name = "_"
                return self.generic_visit(node)

            def visit_Name(self, node: ast.Name) -> ast.AST:
                node.id = "_"
                return node

            def visit_arg(self, node: ast.arg) -> ast.AST:
                node.arg = "_"
                return node

            def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
                node.attr = "_"
                return self.generic_visit(node)

            def visit_Constant(self, node: ast.Constant) -> ast.AST:
                if isinstance(node.value, str | int | float | bytes):
                    node.value = None
                return node

        by_fp: dict[str, list[str]] = defaultdict(list)

        for path in ctx.files:
            if path.suffix.lower() != ".py":
                continue
            rel = safe_relpath(path, ctx.project_root)
            if is_test_path(rel):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            # Skip small files to keep false positives low.
            if len(_normalize_code_lines(text)) < 30:
                continue

            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue

            skeleton = Skeletonize().visit(tree)
            ast.fix_missing_locations(skeleton)
            dumped = ast.dump(skeleton, include_attributes=False)
            fp = sha256(dumped.encode("utf-8", errors="replace")).hexdigest()
            by_fp[fp].append(rel)

        violations: list[Violation] = []
        for _fp, files in sorted(by_fp.items(), key=lambda t: (-len(t[1]), t[0])):
            if len(files) < 3:
                continue
            examples = ", ".join(sorted(files)[:5])
            suffix = "..." if len(files) > 5 else ""
            violations.append(
                self._violation(
                    message=f"Found {len(files)} Python files with the same structure fingerprint: {examples}{suffix}",
                    suggestion="Deduplicate scaffolding, extract shared helpers, or generate code via templates instead of copy/paste.",
                    location=_repo_loc(ctx),
                )
            )
            if len(violations) >= 10:
                break

        return violations


@dataclass(frozen=True, slots=True)
class X04PythonCircularImportRisk(BaseRule):
    meta = RuleMeta(
        rule_id="X04",
        title="Circular imports under src/",
        description="Circular imports between local Python modules under src/ are fragile and can cause import-time crashes.",
        default_severity="warn",
        score_dimension="quality",
        fingerprint_model=None,
    )

    def check_project(self, ctx: ProjectContext) -> list[Violation]:
        local_modules: dict[str, tuple[Path, bool]] = {}
        for path in ctx.files:
            if path.suffix.lower() != ".py":
                continue
            rel = _rel_posix(path, ctx.project_root)
            info = _src_py_to_module(rel)
            if info is None:
                continue
            module_name, is_package = info
            local_modules[module_name] = (path, is_package)

        if len(local_modules) < 2:
            return []

        module_names = set(local_modules)
        graph: dict[str, set[str]] = {name: set() for name in module_names}

        def resolve_import_from(current: str, current_is_package: bool, node: ast.ImportFrom) -> set[str]:
            base: str = ""
            if node.level:
                pkg = _module_package(current, is_package=current_is_package)
                pkg_parts = pkg.split(".") if pkg else []
                base_depth = len(pkg_parts) - (node.level - 1)
                if base_depth < 0:
                    return set()
                base_parts = pkg_parts[:base_depth]
                if node.module:
                    base_parts.extend(node.module.split("."))
                base = ".".join(p for p in base_parts if p)
            else:
                base = node.module or ""

            edges: set[str] = set()
            if base and base in module_names:
                edges.add(base)
            for alias in node.names:
                if alias.name == "*":
                    continue
                candidate = f"{base}.{alias.name}" if base else alias.name
                if candidate in module_names:
                    edges.add(candidate)
            return edges

        for module_name, (path, is_package) in local_modules.items():
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue

            for ast_node in ast.walk(tree):
                if isinstance(ast_node, ast.Import):
                    for alias in ast_node.names:
                        imported = alias.name
                        if imported in module_names:
                            graph[module_name].add(imported)
                elif isinstance(ast_node, ast.ImportFrom):
                    graph[module_name].update(resolve_import_from(module_name, is_package, ast_node))

        components = _tarjan_scc(graph)
        cyclic_components: list[set[str]] = []
        for comp in components:
            if len(comp) > 1:
                cyclic_components.append(set(comp))
                continue
            node_name = comp[0]
            if node_name in graph.get(node_name, set()):
                cyclic_components.append({node_name})

        cyclic_components.sort(key=lambda nodes: (len(nodes), ",".join(sorted(nodes))))

        violations: list[Violation] = []
        for nodes in cyclic_components:
            cycle_path = _find_cycle_path(nodes, graph)
            if cycle_path is not None:
                rendered = " -> ".join(cycle_path)
            else:
                rendered = ", ".join(sorted(nodes))

            violations.append(
                self._violation(
                    message=f"Detected circular import cycle under src/: {rendered}",
                    suggestion="Break the cycle by moving shared types to a common module, delaying imports, or refactoring package __init__.py imports.",
                    location=_repo_loc(ctx),
                )
            )
            if len(violations) >= 10:
                break

        return violations


@dataclass(frozen=True, slots=True)
class X05MissingTestFile(BaseRule):
    meta = RuleMeta(
        rule_id="X05",
        title="Missing test file for src module",
        description="Modules under src/ without a corresponding tests/test_<module>.py file often indicate untested or scaffolded code.",
        default_severity="info",
        score_dimension="maintainability",
        fingerprint_model=None,
    )

    def check_project(self, ctx: ProjectContext) -> list[Violation]:
        missing: list[tuple[str, str]] = []

        for path in ctx.files:
            if path.suffix.lower() != ".py":
                continue
            rel = _rel_posix(path, ctx.project_root)
            expected_rel = _expected_test_for_src_module(rel)
            if expected_rel is None:
                continue
            if not (ctx.project_root / expected_rel).exists():
                missing.append((rel, expected_rel))

        if not missing:
            return []

        missing.sort()
        examples = ", ".join(f"{src} -> {test}" for src, test in missing[:8])
        suffix = "..." if len(missing) > 8 else ""

        return [
            self._violation(
                message=f"Missing test files for {len(missing)} src modules: {examples}{suffix}",
                suggestion="Add a tests/test_<module>.py file (e.g. unit tests) or exempt generated/entrypoint modules from this convention.",
                location=_repo_loc(ctx),
            )
        ]


def builtin_crossfile_rules() -> list[BaseRule]:
    return [
        X01CrossFileDuplicateCode(),
        X02CrossFileNamingConsistency(),
        X03PythonStructureFingerprintClusters(),
        X04PythonCircularImportRisk(),
        X05MissingTestFile(),
    ]
