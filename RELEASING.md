# Releasing SlopSentinel

This repo ships **both** a Python package and a GitHub Action.

## Versioning

- Git tags: `vX.Y.Z` (recommended)
- GitHub Action reference: `slopsentinel/action@v1` style (major tag moving forward)
- Python package version: `pyproject.toml` + `src/slopsentinel/__init__.py`

## Release checklist

1) Bump version
- `pyproject.toml`
- `src/slopsentinel/__init__.py`

2) Run tests

```bash
python -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pytest
```

3) Create a git tag

```bash
git tag vX.Y.Z
git push origin vX.Y.Z
```

Pushing a `v*` tag triggers GitHub workflows:
- `.github/workflows/release-pypi.yml` publishes the Python package to PyPI (trusted publishing via OIDC).
- `.github/workflows/release-action-image.yml` builds and pushes the GitHub Action image to GHCR (optional).

4) Move the major tag (`v1`)

```bash
git tag -f v1 vX.Y.Z
git push -f origin v1
```

5) Publish GitHub Release + Marketplace

On GitHub:
- Create a Release from the `vX.Y.Z` tag
- Publish the GitHub Action to the Marketplace (optional but recommended)

## Action Docker image (optional)

This repo includes `.github/workflows/release-action-image.yml` which builds and pushes an image to GHCR on `v*` tags.

If you later want to switch the action to a prebuilt image (faster startup), you can change `action.yml`:
- from `runs.image: Dockerfile`
- to `runs.image: docker://ghcr.io/<owner>/<repo>:vX.Y.Z`

Do this only after GHCR publishing is verified.
