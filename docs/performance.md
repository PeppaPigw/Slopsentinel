# Performance

This project includes a small, reproducible benchmark suite under `tests/bench/`.

The goals are:
- Track scan throughput over time (serial vs parallel).
- Identify slow rules before they become hot-path bottlenecks.

## Running benchmarks

Run:

```bash
python tests/bench/bench_scan.py
python tests/bench/bench_rules.py
```

Notes:
- Benchmarks generate synthetic repos under `.slopsentinel-bench*` in the current directory.
- Results vary by machine; compare relative numbers (e.g. workers=1 vs workers=8).

## What to look for

- `bench_scan.py`: `files/s` should increase with more workers for larger repos.
- `bench_rules.py`: focus on rules with high `ms/call` — they dominate CPU time.

## Sample results (example run)

These numbers are **machine-dependent**. Use them to compare relative changes
over time (before/after), not as absolute targets.

From a sample run on a 14‑CPU machine:

- `bench_rules.py` (top slow rules, ms/call, 500 iterations):
  - `C03`: ~2.06 ms/call (hallucinated import checks tend to be I/O + lookup heavy)
  - `E03`: ~0.10 ms/call (unused imports uses AST walk + name tracking)
  - `E06`: ~0.05 ms/call (repeated string literal heuristic)

- `bench_scan.py` (synthetic repos, files/s):
  - For tiny files, parallelism can be slower due to worker overhead.
  - For real repos (larger files, heavier rules), additional workers often help.

## Optimization opportunities

If benchmarks show scan throughput regressing, start with:

1. `C03` (hallucinated import): cache expensive lookups per run/project where possible.
2. AST-heavy rules: avoid repeated `ast.walk()` when a single pass can collect data.
3. Cross-file rules: keep caches keyed by content hash to avoid redundant work.
