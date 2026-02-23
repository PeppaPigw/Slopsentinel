from __future__ import annotations

import os
import random
import string
import time
from pathlib import Path

from slopsentinel.audit import audit_path


def _random_identifier(rng: random.Random, *, n: int = 8) -> str:
    letters = string.ascii_lowercase
    return "".join(rng.choice(letters) for _ in range(n))


def _synthetic_python_file(rng: random.Random) -> str:
    # Small but rule-rich synthetic content.
    name = _random_identifier(rng)
    return (
        "# We need to ensure this is safe\n"
        f"def {name}(x):\n"
        "    # Initialize an empty list for results\n"
        "    results = []\n"
        "    try:\n"
        "        return x / 1\n"
        "    except Exception:\n"
        "        pass\n"
    )


def _generate_repo(root: Path, *, files: int, seed: int = 0) -> tuple[int, int]:
    rng = random.Random(seed)
    src = root / "src"
    src.mkdir(parents=True, exist_ok=True)

    total_bytes = 0
    for idx in range(files):
        path = src / f"file_{idx:04d}.py"
        content = _synthetic_python_file(rng)
        path.write_text(content, encoding="utf-8")
        total_bytes += len(content.encode("utf-8"))
    return files, total_bytes


def _bench_once(root: Path, *, workers: int) -> float:
    os.environ["SLOPSENTINEL_WORKERS"] = str(workers)
    start = time.perf_counter()
    _ = audit_path(root, record_history=False)
    end = time.perf_counter()
    return end - start


def main() -> int:
    bench_root = Path(".slopsentinel-bench")
    bench_root.mkdir(parents=True, exist_ok=True)

    sizes = [100, 500, 1000]
    workers_list = [1, min(8, os.cpu_count() or 4)]

    print("SlopSentinel scan benchmark (synthetic repo)")
    print(f"CPU count: {os.cpu_count()}")
    print()

    for n in sizes:
        case = bench_root / f"repo_{n}"
        if case.exists():
            # Reuse existing.
            files, total_bytes = n, sum(p.stat().st_size for p in (case / "src").glob("*.py"))
        else:
            files, total_bytes = _generate_repo(case, files=n, seed=n)

        mb = total_bytes / (1024 * 1024)
        print(f"Case: {files} files ({mb:.2f} MiB)")
        for workers in workers_list:
            elapsed = _bench_once(case, workers=workers)
            fps = files / max(elapsed, 1e-9)
            mbs = mb / max(elapsed, 1e-9)
            print(f"  workers={workers:<2d}  {elapsed:>7.3f}s  {fps:>8.1f} files/s  {mbs:>6.2f} MiB/s")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
