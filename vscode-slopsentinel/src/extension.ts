import * as vscode from "vscode";
import { spawn } from "child_process";

import { LspClientHandle, startLsp } from "./lspClient";

let lsp: LspClientHandle | undefined;

function getConfig(): vscode.WorkspaceConfiguration {
  return vscode.workspace.getConfiguration("slopsentinel");
}

function resolveExecutablePath(): string {
  const cfg = getConfig();
  const raw = cfg.get<string>("executablePath") ?? "slopsentinel";
  return raw.trim() || "slopsentinel";
}

function resolveThreshold(): number {
  const cfg = getConfig();
  const raw = cfg.get<number>("threshold") ?? 60;
  if (Number.isFinite(raw)) {
    return Math.max(0, Math.min(100, raw));
  }
  return 60;
}

async function runCommandInWorkspace(args: string[], output: vscode.OutputChannel): Promise<void> {
  const folders = vscode.workspace.workspaceFolders;
  if (!folders || folders.length === 0) {
    vscode.window.showErrorMessage("SlopSentinel: open a workspace folder to scan.");
    return;
  }

  const cwd = folders[0].uri.fsPath;
  const cmd = resolveExecutablePath();

  output.show(true);
  output.appendLine(`$ ${cmd} ${args.join(" ")}`);

  const exitCode = await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: "SlopSentinel", cancellable: false },
    async () => {
      return await new Promise<number>((resolve) => {
        const child = spawn(cmd, args, {
          cwd,
          shell: process.platform === "win32"
        });

        child.stdout.on("data", (chunk) => output.append(chunk.toString()));
        child.stderr.on("data", (chunk) => output.append(chunk.toString()));

        child.on("error", (err) => {
          output.appendLine(String(err));
          resolve(2);
        });

        child.on("close", (code) => resolve(code ?? 0));
      });
    }
  );

  if (exitCode !== 0) {
    vscode.window.showWarningMessage(
      `SlopSentinel finished with exit code ${exitCode}. See Output → SlopSentinel.`
    );
  }
}

export function activate(context: vscode.ExtensionContext): void {
  const output = vscode.window.createOutputChannel("SlopSentinel");
  context.subscriptions.push(output);

  const cfg = getConfig();
  const lspEnabled = cfg.get<boolean>("lspEnabled") ?? true;
  if (lspEnabled) {
    try {
      lsp = startLsp(output);
    } catch (err) {
      output.appendLine(String(err));
      vscode.window.showWarningMessage("SlopSentinel: failed to start LSP. Is `slopsentinel` installed on PATH?");
    }
  }

  context.subscriptions.push(
    vscode.commands.registerCommand("slopsentinel.scan", async () => {
      const threshold = resolveThreshold();
      await runCommandInWorkspace(["scan", ".", "--format", "json", "--threshold", String(threshold)], output);
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("slopsentinel.fix", async () => {
      const editor = vscode.window.activeTextEditor;
      if (!editor) {
        vscode.window.showErrorMessage("SlopSentinel: no active editor.");
        return;
      }
      const path = editor.document.uri.fsPath;
      await runCommandInWorkspace(["fix", path, "--dry-run"], output);
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("slopsentinel.showTrend", async () => {
      await runCommandInWorkspace(["trend", ".", "--format", "json", "--last", "20"], output);
    })
  );
}

export async function deactivate(): Promise<void> {
  if (lsp) {
    await lsp.stop();
    lsp = undefined;
  }
}
