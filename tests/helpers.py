from __future__ import annotations

from slopsentinel.engine.context import ProjectContext
from slopsentinel.scanner import build_file_context


def make_file_ctx(project_ctx: ProjectContext, *, relpath: str, content: str):
    path = project_ctx.project_root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    ctx = build_file_context(project_ctx, path)
    assert ctx is not None
    return ctx

