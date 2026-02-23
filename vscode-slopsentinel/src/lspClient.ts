import * as vscode from "vscode";
import { LanguageClient, LanguageClientOptions, ServerOptions } from "vscode-languageclient/node";

export type LspClientHandle = {
  client: LanguageClient;
  stop: () => Promise<void>;
};

function getConfig(): vscode.WorkspaceConfiguration {
  return vscode.workspace.getConfiguration("slopsentinel");
}

function resolveExecutablePath(): string {
  const cfg = getConfig();
  const raw = cfg.get<string>("executablePath") ?? "slopsentinel";
  return raw.trim() || "slopsentinel";
}

export function startLsp(output: vscode.OutputChannel): LspClientHandle {
  const command = resolveExecutablePath();

  const serverOptions: ServerOptions = {
    command,
    args: ["lsp"]
  };

  const clientOptions: LanguageClientOptions = {
    documentSelector: [
      { scheme: "file", language: "python" },
      { scheme: "file", language: "javascript" },
      { scheme: "file", language: "typescript" },
      { scheme: "file", language: "go" },
      { scheme: "file", language: "rust" },
      { scheme: "file", language: "java" },
      { scheme: "file", language: "kotlin" },
      { scheme: "file", language: "ruby" },
      { scheme: "file", language: "php" }
    ],
    outputChannel: output
  };

  const client = new LanguageClient("slopsentinel", "SlopSentinel", serverOptions, clientOptions);
  client.start();

  return {
    client,
    stop: async () => {
      await client.stop();
    }
  };
}

