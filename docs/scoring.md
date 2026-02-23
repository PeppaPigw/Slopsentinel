# Scoring

SlopSentinel reports a single **0–100 score** plus a per-dimension breakdown.

Important: the score is not an "AI vs human" classifier. It is a heuristic
signal for **AI-like patterns** (fingerprints) and **risk/quality issues** that
often correlate with AI-generated "slop".

## Dimensions (max points)

The score is the sum of five bounded dimension scores (max = 100):

- `fingerprint` (max 35): AI fingerprint signals (Claude/Cursor/Copilot/Gemini-style patterns)
- `quality` (max 25): general code quality anti-patterns
- `hallucination` (max 20): broken/invalid imports, fabricated APIs, etc.
- `maintainability` (max 15): readability and long-term maintenance risks
- `security` (max 5): security-adjacent slop signals (small budget but still meaningful)

These budgets are defined in `src/slopsentinel/engine/scoring.py`.

## How penalties work

Each violation has:

- `dimension` (one of the five above)
- `severity` (`info`, `warn`, `error`)

For each dimension, SlopSentinel sums **severity penalties**, then subtracts
from that dimension’s max budget (with saturation):

```
dimension_score = DIMENSION_MAX[dimension] - min(DIMENSION_MAX[dimension], total_penalty)
```

The final score is:

```
score = fingerprint + quality + hallucination + maintainability + security
```

### Severity penalty mapping

Penalties are dimension-specific: hallucinations are intentionally expensive,
while fingerprint signals are lighter. The default profile is:

- `fingerprint`: `info=1`, `warn=2`, `error=3`
- `quality`: `info=1`, `warn=3`, `error=5`
- `hallucination`: `info=4`, `warn=10`, `error=20`
- `maintainability`: `info=1`, `warn=3`, `error=5`
- `security`: `info=1`, `warn=3`, `error=5`

Profiles:

- `default`: balanced penalties
- `strict`: blocks earlier on quality/security risks
- `lenient`: gradual adoption (focus on high-severity findings)

You can select a profile via:

```toml
[tool.slopsentinel.scoring]
profile = "strict"  # or "default", "lenient"
```

Or override penalties per dimension/severity:

```toml
[tool.slopsentinel.scoring.penalties.quality]
warn = 4
error = 7
```

## Structure signals: density + clustering

In addition to per-violation penalties, scoring incorporates two *structure*
signals:

- **density** = violations per scanned file
- **clustering** = fraction of file-level violations concentrated in the worst file

These signals produce a small extra penalty (max 10 points) that is applied to
the `quality` dimension only, keeping the overall score bounded and stable.

This logic lives in `compute_density_and_clustering()` and `_structure_penalty()`.

## AI confidence label

Reports include `ai_confidence` (`low`, `medium`, `high`) based on how many
fingerprint-rule hits are present and whether multiple model fingerprints appear.

This is intentionally conservative and should be interpreted as a *signal*, not
a claim of authorship.

## CI usage: `--fail-under`

For CI gating, prefer:

```bash
slopsentinel scan . --fail-under 60
```

This is equivalent to:

```bash
slopsentinel scan . --threshold 60 --fail-on-slop
```

Suggested starting points:

- `--fail-under 60`: common baseline for "no obvious slop"
- `--fail-under 75`: standard teams / higher standards
- `--fail-under 85`: strict gating (pairs well with `profile = "strict"`)

## Worked example (simplified)

Imagine a scan finds:

- 2 fingerprint warnings (`fingerprint`, `warn`)
- 1 hallucination error (`hallucination`, `error`)

Using the default profile:

- fingerprint penalty = `2 × 2 = 4` → `35 - 4 = 31`
- hallucination penalty = `1 × 20 = 20` → `20 - 20 = 0`

Assuming other dimensions stay at max, the score becomes:

```
31 (fingerprint) + 25 (quality) + 0 (hallucination) + 15 (maintainability) + 5 (security) = 76
```

Density/clustering may further reduce `quality` by a small amount when findings
are very dense or heavily clustered.
