from __future__ import annotations

import json
import threading
from pathlib import Path

from slopsentinel.cache import FileViolationCache, config_fingerprint, file_content_hash
from slopsentinel.engine.types import Location, Violation


def test_cache_roundtrip_put_get(tmp_path: Path) -> None:
    project_root = tmp_path
    cache_path = tmp_path / ".slopsentinel" / "cache.json"
    fingerprint = config_fingerprint(enabled_rule_ids={"A03"}, overrides={}, plugins=())

    cache = FileViolationCache.load(cache_path, fingerprint=fingerprint, project_root=project_root)
    v = Violation(
        rule_id="A03",
        severity="warn",
        message="msg",
        dimension="fingerprint",
        suggestion="remove it",
        location=Location(path=tmp_path / "src" / "app.py", start_line=1, start_col=1),
    )
    h = file_content_hash("# We need to ensure\n")
    cache.put(relative_path="src/app.py", content_hash=h, violations=[v])
    cache.save()

    reloaded = FileViolationCache.load(cache_path, fingerprint=fingerprint, project_root=project_root)
    got = reloaded.get(relative_path="src/app.py", content_hash=h)
    assert got is not None
    assert got[0].rule_id == "A03"
    assert got[0].location is not None
    assert got[0].location.path is not None


def test_cache_fingerprint_mismatch_ignores_entries(tmp_path: Path) -> None:
    project_root = tmp_path
    cache_path = tmp_path / ".slopsentinel" / "cache.json"
    fp1 = config_fingerprint(enabled_rule_ids={"A03"}, overrides={}, plugins=())
    fp2 = config_fingerprint(enabled_rule_ids={"A03", "A06"}, overrides={}, plugins=())

    cache = FileViolationCache.load(cache_path, fingerprint=fp1, project_root=project_root)
    h = file_content_hash("# We need to ensure\n")
    cache.put(
        relative_path="src/app.py",
        content_hash=h,
        violations=[
            Violation(
                rule_id="A03",
                severity="warn",
                message="msg",
                dimension="fingerprint",
                location=Location(path=tmp_path / "src" / "app.py", start_line=1, start_col=1),
            )
        ],
    )
    cache.save()

    reloaded = FileViolationCache.load(cache_path, fingerprint=fp2, project_root=project_root)
    assert reloaded.get(relative_path="src/app.py", content_hash=h) is None


def test_audit_uses_cache_to_avoid_recomputing(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.slopsentinel]

[tool.slopsentinel.cache]
enabled = true
""".lstrip(),
        encoding="utf-8",
    )
    p = tmp_path / "src" / "example.py"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# We need to ensure the connection is properly closed\nx = 1\n", encoding="utf-8")

    from slopsentinel.audit import audit_path
    from slopsentinel.rules.claude import A03OverlyPoliteComment

    calls = {"n": 0}
    original = A03OverlyPoliteComment.check_file

    def wrapped(self: A03OverlyPoliteComment, ctx):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        return original(self, ctx)

    monkeypatch.setattr(A03OverlyPoliteComment, "check_file", wrapped)

    first = audit_path(tmp_path)
    second = audit_path(tmp_path)

    assert calls["n"] == 1
    assert list(first.summary.violations) == list(second.summary.violations)


def test_audit_cache_fingerprint_includes_directory_overrides(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.slopsentinel]

[tool.slopsentinel.cache]
enabled = true

[tool.slopsentinel.overrides."tests/"]
rules.disable = ["A03"]
""".lstrip(),
        encoding="utf-8",
    )
    p = tmp_path / "src" / "example.py"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# We need to ensure the connection is properly closed\nx = 1\n", encoding="utf-8")

    from slopsentinel.audit import audit_path
    from slopsentinel.rules.claude import A03OverlyPoliteComment

    calls = {"n": 0}
    original = A03OverlyPoliteComment.check_file

    def wrapped(self: A03OverlyPoliteComment, ctx):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        return original(self, ctx)

    monkeypatch.setattr(A03OverlyPoliteComment, "check_file", wrapped)

    _ = audit_path(tmp_path)
    _ = audit_path(tmp_path)

    # Directory override config should not prevent caching.
    assert calls["n"] == 1


def test_cache_save_holds_lock_during_write(monkeypatch, tmp_path: Path) -> None:
    project_root = tmp_path
    cache_path = tmp_path / ".slopsentinel" / "cache.json"
    fingerprint = config_fingerprint(enabled_rule_ids={"A03"}, overrides={}, plugins=())

    cache = FileViolationCache.load(cache_path, fingerprint=fingerprint, project_root=project_root)
    v = Violation(
        rule_id="A03",
        severity="warn",
        message="msg",
        dimension="fingerprint",
        location=Location(path=tmp_path / "src" / "app.py", start_line=1, start_col=1),
    )
    h = file_content_hash("# We need to ensure\n")
    cache.put(relative_path="src/app.py", content_hash=h, violations=[v])

    tmp_file = cache_path.with_suffix(cache_path.suffix + ".tmp")
    write_started = threading.Event()
    allow_write = threading.Event()

    original = Path.write_text

    def patched_write_text(self: Path, text: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        if self == tmp_file:
            write_started.set()
            allow_write.wait(timeout=1)
        return original(self, text, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", patched_write_text)

    t = threading.Thread(target=cache.save)
    t.start()
    assert write_started.wait(timeout=1), "save() did not reach tmp write in time"

    acquired = cache._lock.acquire(blocking=False)  # type: ignore[attr-defined]
    if acquired:
        cache._lock.release()  # type: ignore[attr-defined]
    assert acquired is False, "cache lock should be held during write/replace to avoid save/put races"

    allow_write.set()
    t.join(timeout=1)
    assert not t.is_alive()


def test_cache_deserialize_is_tolerant_and_sanitizes_location(tmp_path: Path) -> None:
    project_root = tmp_path
    cache_path = tmp_path / ".slopsentinel" / "cache.json"
    fingerprint = config_fingerprint(enabled_rule_ids={"A03"}, overrides={}, plugins=())
    h = file_content_hash("x = 1\n")

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {
                "version": 1,
                "fingerprint": fingerprint,
                "files": {
                    "src/app.py": {
                        "hash": h,
                        "violations": [
                            {
                                "rule_id": "a03",
                                "severity": "BOOM",
                                "message": 123,
                                "dimension": "weird",
                                "suggestion": ["nope"],
                                "location": {"path": "../escape.py", "start_line": 1, "start_col": 0},
                            },
                            "not-a-dict",
                            {
                                "rule_id": "A03",
                                "severity": "warn",
                                "message": "ok",
                                "dimension": "fingerprint",
                                "location": {"path": "/etc/passwd", "start_line": 1, "start_col": 1},
                            },
                        ],
                    }
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    cache = FileViolationCache.load(cache_path, fingerprint=fingerprint, project_root=project_root)
    got = cache.get(relative_path="src/app.py", content_hash=h)
    assert got is not None
    assert len(got) == 2
    assert got[0].rule_id == "A03"
    assert got[0].severity in {"info", "warn", "error"}
    assert got[0].dimension in {"fingerprint", "quality", "hallucination", "maintainability", "security"}
    assert got[0].location is None
    assert got[1].location is None
