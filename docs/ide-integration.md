# IDE integration

SlopSentinel ships a minimal stdio LSP server:

```bash
# both entrypoints are equivalent
slop lsp
# or:
slopsentinel lsp
```

It provides:

- Diagnostics (as you type / on save, depending on client)
- Hover (rule metadata + examples when available)
- Code actions (QuickFix) for conservative auto-fixable rules

## VS Code

This repository includes a buildable VS Code extension skeleton in `vscode-slopsentinel/`.

Build it:

```bash
cd vscode-slopsentinel
npm install
npm run compile
```

Then open `vscode-slopsentinel/` in VS Code and press `F5` to launch an
Extension Development Host.

Configuration keys:

- `slopsentinel.executablePath` (default: `slopsentinel`)
- `slopsentinel.lspEnabled` (default: `true`)
- `slopsentinel.threshold` (default: `60`)

If you prefer not to build the extension, you can also use a generic LSP client
extension and point it at `["slop", "lsp"]`.

## Neovim (nvim-lspconfig)

If you use `nvim-lspconfig`, you can register SlopSentinel as a custom server:

```lua
local lspconfig = require("lspconfig")
local configs = require("lspconfig.configs")

if not configs.slopsentinel then
  configs.slopsentinel = {
    default_config = {
      cmd = { "slopsentinel", "lsp" },
      filetypes = { "python", "javascript", "typescript" },
      root_dir = lspconfig.util.root_pattern("pyproject.toml", ".git"),
    },
  }
end

lspconfig.slopsentinel.setup({})
```

Notes:
- This example is not exhaustive; adapt `filetypes` to your repo.
- If you installed via `pip install slopsentinel`, ensure `slopsentinel` is on `PATH`.

More complete example (keymaps + optional `nvim-cmp` capabilities):

```lua
local lspconfig = require("lspconfig")
local util = require("lspconfig.util")

local capabilities = vim.lsp.protocol.make_client_capabilities()
pcall(function()
  capabilities = require("cmp_nvim_lsp").default_capabilities(capabilities)
end)

local function on_attach(_, bufnr)
  vim.keymap.set("n", "<leader>ss", function()
    vim.cmd("!slop scan .")
  end, { buffer = bufnr, desc = "SlopSentinel: Scan workspace" })
end

lspconfig.slopsentinel.setup({
  cmd = { "slop", "lsp" },
  filetypes = { "python", "javascript", "typescript" },
  root_dir = util.root_pattern("pyproject.toml", ".git"),
  on_attach = on_attach,
  capabilities = capabilities,
})
```

## Helix

In `~/.config/helix/languages.toml`:

```toml
[language-server.slopsentinel]
command = "slop"
args = ["lsp"]

[[language]]
name = "python"
language-servers = ["slopsentinel"]

[[language]]
name = "javascript"
language-servers = ["slopsentinel"]

[[language]]
name = "typescript"
language-servers = ["slopsentinel"]
```

## Emacs (eglot)

With `eglot`, add a mapping from major mode to the command:

```elisp
(add-to-list 'eglot-server-programs
             '((python-mode js-mode typescript-mode)
               . ("slopsentinel" "lsp")))
```

## Zed

Zed can run external language servers. The exact JSON keys may change across
Zed versions, but the core idea is the same: register a server that runs
`slop lsp` over stdio and attach it to supported languages.

Example `settings.json` snippet (adjust as needed for your Zed version):

```json
{
  "language_servers": {
    "slopsentinel": {
      "command": "slop",
      "args": ["lsp"]
    }
  }
}
```

## Any LSP client

Any editor that supports stdio LSP can use:

- Command: `slop`
- Args: `["lsp"]`

## pre-commit

For quick feedback on staged changes, a common pattern is:

```yaml
repos:
  - repo: local
    hooks:
      - id: slopsentinel
        name: SlopSentinel
        entry: slopsentinel diff --staged
        language: system
        pass_filenames: false
```
