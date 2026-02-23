# Case studies

This document focuses on **reproducible** examples you can run locally.
It avoids claiming results from third-party repositories unless the steps and
outputs are fully reproducible.

If you have an interesting false positive/negative (or a public repo you want us
to validate against), please open an issue using the “false positive” template.

## Case study: `demo/` (synthetic “AI slop” patterns)

The repository includes a small `demo/` directory used to generate stable
README screenshots.

### Goal

Demonstrate a realistic mix of findings:

- fingerprint-style narrative comments
- unused imports + empty/broad exception handling
- credential-like literals
- redundant boolean returns

### Reproduce

From the repo root:

```bash
slop scan demo/ --format json > demo.json
```

At the time of writing, this produces:

- `score`: `73/100`
- `files_scanned`: `1`
- `violations`: `7`
- rule ids: `A03`, `C09`, `D01`, `E03`, `E04`, `E09`, `E11`

### AutoFix preview (dry-run)

```bash
slop fix demo/bad_code.py --dry-run
```

Example excerpt (diff):

```diff
-api_token = "abc123"  # hardcoded credential-like literal (E09)
+api_token = os.environ.get("API_TOKEN", "")

-    if x > 0:
-        return True
-    else:
-        return False
+    return x > 0

     except Exception:
-        pass
+        raise
```

Notes:

- Fixes are conservative and may skip a file if safety checks fail.
- SlopSentinel will not do cross-file refactors.

## Case study: gradual adoption via baseline + CI gate

This workflow is designed for existing repos where “fix everything now” is not
practical.

### 1) Generate a baseline

```bash
slop baseline .
```

Commit the baseline file (default: `.slopsentinel-baseline.json`).

### 2) Gate in CI using the wrapper

```bash
slop ci . --fail-under 75
```

This is baseline-aware and uses stable exit codes:

- `0`: pass
- `1`: policy failure (score below threshold, regression, etc.)
- `2`: configuration error

### 3) Improve over time (trend)

Enable history recording:

```toml
[tool.slopsentinel.history]
enabled = true
```

Then use:

```bash
slop trend --format terminal
slop trend --format html > trend.html
```

## Case study: PR-focused scanning (diff)

When reviewing PRs, a common pattern is to focus on *changed lines only*:

```bash
slop diff --staged --format github
```

This is useful for pre-commit hooks and for keeping signal high on large repos.

