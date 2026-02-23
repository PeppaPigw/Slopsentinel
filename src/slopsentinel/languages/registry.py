from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class LanguageSpec:
    name: str
    extensions: tuple[str, ...]


LANGUAGES: tuple[LanguageSpec, ...] = (
    LanguageSpec("python", (".py",)),
    LanguageSpec("javascript", (".js", ".jsx", ".mjs", ".cjs")),
    LanguageSpec("typescript", (".ts", ".tsx")),
    LanguageSpec("go", (".go",)),
    LanguageSpec("rust", (".rs",)),
    LanguageSpec("java", (".java",)),
    LanguageSpec("kotlin", (".kt", ".kts")),
    LanguageSpec("ruby", (".rb",)),
    LanguageSpec("php", (".php",)),
)

_EXT_TO_LANG = {ext: spec.name for spec in LANGUAGES for ext in spec.extensions}


def detect_language(path: Path) -> str | None:
    """
    Best-effort language detection based on file extension.

    Returns the canonical language name from `LANGUAGES` or None if unsupported.
    """

    return _EXT_TO_LANG.get(path.suffix.lower())


def allowed_extensions(enabled_languages: tuple[str, ...]) -> set[str]:
    enabled = {lang.strip().lower() for lang in enabled_languages}
    exts: set[str] = set()
    for spec in LANGUAGES:
        if spec.name in enabled:
            exts.update(spec.extensions)
    return exts


def tree_sitter_language_for_path(path: Path, *, detected_language: str) -> str:
    """
    Map a file path + detected language to the tree-sitter language name.

    Some extensions require a different grammar name (e.g. TSX).
    """

    suffix = path.suffix.lower()
    if detected_language == "typescript" and suffix == ".tsx":
        return "tsx"
    return detected_language
