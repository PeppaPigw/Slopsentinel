# SlopSentinel (VS Code extension skeleton)

This directory contains a buildable VS Code extension skeleton for SlopSentinel.

It is intentionally minimal:

- Starts the SlopSentinel stdio LSP server (`slopsentinel lsp`) for diagnostics/hover/quickfix
- Adds commands to run `slopsentinel scan`, `slopsentinel fix --dry-run`, and `slopsentinel trend`

## Prerequisites

Install the SlopSentinel CLI:

```bash
pip install slopsentinel
```

Ensure `slopsentinel` (or `slop`) is on your `PATH`.

## Build

```bash
npm install
npm run compile
```

## Configuration

In VS Code settings:

- `slopsentinel.executablePath` (default: `slopsentinel`)
- `slopsentinel.lspEnabled` (default: `true`)
- `slopsentinel.threshold` (default: `60`)

## Notes

This is a skeleton intended for iteration. It is not published to the Marketplace by default.

