import { existsSync, mkdirSync } from "node:fs";
import { spawn, spawnSync } from "node:child_process";
import path from "node:path";
import process from "node:process";
import readline from "node:readline";
import { clearTimeout, setTimeout } from "node:timers";


const ROOT = path.resolve(import.meta.dirname, "..");
const PROBE_ROOT = path.join(ROOT, ".tmp", "codex-mcp-host-probe");
const CODEX_HOME = path.join(PROBE_ROOT, "codex-home");
const STATE_DIR = path.join(PROBE_ROOT, "card-service-state");
const WORKER = path.join(ROOT, "tests", "fixtures", "card_service", "fake_worker.py");
const SERVER = "anki-study-m1";
const TOOL = "system.get_capabilities";
const REQUEST_TIMEOUT_MS = 30_000;


function resolvePython() {
  const requested = process.env.ANKI_STUDY_PYTHON?.trim();
  if (requested) {
    return path.resolve(requested);
  }
  const command = process.platform === "win32" ? "python.exe" : "python3";
  const result = spawnSync(command, ["-c", "import sys; print(sys.executable)"], {
    cwd: ROOT,
    encoding: "utf8",
    windowsHide: true,
  });
  if (result.status !== 0 || !result.stdout.trim()) {
    throw new Error("Unable to resolve an absolute Python executable for the MCP host probe.");
  }
  return path.resolve(result.stdout.trim());
}


function resolveCodex() {
  const requested = process.env.ANKI_STUDY_CODEX?.trim();
  if (requested) {
    return { command: path.resolve(requested), argsPrefix: [] };
  }
  if (process.platform !== "win32") {
    return { command: "codex", argsPrefix: [] };
  }
  const npmEntrypoint = path.join(
    process.env.APPDATA || "",
    "npm",
    "node_modules",
    "@openai",
    "codex",
    "bin",
    "codex.js",
  );
  if (existsSync(npmEntrypoint)) {
    return { command: process.execPath, argsPrefix: [npmEntrypoint] };
  }
  const result = spawnSync("where.exe", ["codex.exe"], {
    cwd: ROOT,
    encoding: "utf8",
    windowsHide: true,
  });
  const executable = result.stdout
    ?.split(/\r?\n/)
    .map((value) => value.trim())
    .find((value) => value.toLowerCase().endsWith("\\codex.exe"));
  if (result.status !== 0 || !executable) {
    throw new Error("Unable to resolve the native Codex executable for the MCP host probe.");
  }
  return { command: path.resolve(executable), argsPrefix: [] };
}


function tomlString(value) {
  return JSON.stringify(value);
}


function tomlArray(values) {
  return `[${values.map(tomlString).join(",")}]`;
}


function waitForExit(child, timeoutMs) {
  return new Promise((resolve) => {
    if (child.exitCode !== null) {
      resolve(child.exitCode);
      return;
    }
    const timer = setTimeout(() => {
      child.kill();
    }, timeoutMs);
    child.once("exit", (code) => {
      clearTimeout(timer);
      resolve(code);
    });
  });
}


async function main() {
  const python = resolvePython();
  mkdirSync(CODEX_HOME, { recursive: true });
  mkdirSync(STATE_DIR, { recursive: true });

  const serverArgs = [
    "-m",
    "card_service.mcp_stdio",
    "--state-dir",
    STATE_DIR,
    "--development-unpackaged-runtime",
    "--worker",
    WORKER,
    "--python",
    python,
  ];
  const codex = resolveCodex();
  const codexArgs = [
    ...codex.argsPrefix,
    "app-server",
    "--stdio",
    "-c",
    `mcp_servers.${SERVER}.command=${tomlString(python)}`,
    "-c",
    `mcp_servers.${SERVER}.args=${tomlArray(serverArgs)}`,
    "-c",
    `mcp_servers.${SERVER}.cwd=${tomlString(ROOT)}`,
    "-c",
    `mcp_servers.${SERVER}.startup_timeout_sec=30`,
    "-c",
    `mcp_servers.${SERVER}.tool_timeout_sec=30`,
  ];

  const child = spawn(codex.command, codexArgs, {
    cwd: ROOT,
    env: {
      ...process.env,
      CODEX_HOME,
    },
    stdio: ["pipe", "pipe", "pipe"],
    windowsHide: true,
  });
  child.stdin.setDefaultEncoding("utf8");
  child.stdout.setEncoding("utf8");
  child.stderr.setEncoding("utf8");

  let nextId = 1;
  let stderr = "";
  const pending = new Map();
  const lines = readline.createInterface({ input: child.stdout, crlfDelay: Infinity });
  child.stderr.on("data", (chunk) => {
    stderr += chunk;
  });
  lines.on("line", (line) => {
    let message;
    try {
      message = JSON.parse(line);
    } catch {
      return;
    }
    if (message.id === undefined) {
      return;
    }
    const entry = pending.get(message.id);
    if (!entry) {
      return;
    }
    pending.delete(message.id);
    clearTimeout(entry.timer);
    if (message.error) {
      entry.reject(new Error(`${entry.method}: ${message.error.message || "request failed"}`));
    } else {
      entry.resolve(message.result);
    }
  });

  function notify(method, params = {}) {
    child.stdin.write(`${JSON.stringify({ method, params })}\n`);
  }

  function call(method, params = {}) {
    const id = nextId++;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        pending.delete(id);
        reject(new Error(`${method}: timed out after ${REQUEST_TIMEOUT_MS}ms`));
      }, REQUEST_TIMEOUT_MS);
      pending.set(id, { method, resolve, reject, timer });
      child.stdin.write(`${JSON.stringify({ id, method, params })}\n`);
    });
  }

  try {
    const initialized = await call("initialize", {
      clientInfo: {
        name: "anki_study_mcp_host_probe",
        title: "Anki Study MCP Host Probe",
        version: "0.1.0",
      },
    });
    notify("initialized");

    const started = await call("thread/start", {
      cwd: ROOT,
      ephemeral: true,
      approvalPolicy: "never",
      sandbox: "read-only",
    });
    const threadId = started?.thread?.id;
    if (typeof threadId !== "string" || !threadId) {
      throw new Error("Codex app-server did not return an ephemeral thread id.");
    }

    let registered;
    const deadline = Date.now() + REQUEST_TIMEOUT_MS;
    while (Date.now() < deadline) {
      const status = await call("mcpServerStatus/list", {
        threadId,
        detail: "toolsAndAuthOnly",
      });
      registered = status?.data?.find((entry) => entry.name === SERVER);
      if (registered?.tools?.[TOOL]) {
        break;
      }
      await new Promise((resolve) => setTimeout(resolve, 200));
    }
    if (!registered?.tools?.[TOOL]) {
      throw new Error("Codex did not register the read-only Card Service capability tool.");
    }
    if (Object.keys(registered.tools).some((name) => name !== TOOL)) {
      throw new Error("Codex registered an MCP tool outside the M1 read-only allowlist.");
    }

    const called = await call("mcpServer/tool/call", {
      threadId,
      server: SERVER,
      tool: TOOL,
      arguments: {},
    });
    const structured = called?.structuredContent;
    if (
      called?.isError === true ||
      structured?.mcpBridge?.transport !== "stdio" ||
      structured?.cardService?.genericShell !== false ||
      structured?.cardService?.secretBearingRequests !== false
    ) {
      throw new Error("Codex tool call returned an invalid or unsafe capability snapshot.");
    }

    process.stdout.write(
      `${JSON.stringify(
        {
          ok: true,
          codexHost: {
            userAgent: initialized?.userAgent || null,
            platformFamily: initialized?.platformFamily || null,
            platformOs: initialized?.platformOs || null,
          },
          server: {
            configName: registered.name,
            advertisedName: registered.serverInfo?.name || null,
            advertisedVersion: registered.serverInfo?.version || null,
            authStatus: registered.authStatus,
            tools: Object.keys(registered.tools),
          },
          capability: {
            service: structured.cardService.service,
            transport: structured.mcpBridge.transport,
            protocolVersion: structured.mcpBridge.protocolVersion,
            genericShell: structured.cardService.genericShell,
            secretBearingRequests: structured.cardService.secretBearingRequests,
          },
        },
        null,
        2,
      )}\n`,
    );
  } catch (error) {
    const diagnostic = stderr
      .split(/\r?\n/)
      .filter(Boolean)
      .slice(-20)
      .join("\n");
    throw new Error(
      `${error instanceof Error ? error.message : String(error)}${diagnostic ? `\nCodex stderr:\n${diagnostic}` : ""}`,
      { cause: error },
    );
  } finally {
    for (const entry of pending.values()) {
      clearTimeout(entry.timer);
      entry.reject(new Error("Codex app-server closed before the request completed."));
    }
    pending.clear();
    lines.close();
    child.stdin.end();
    await waitForExit(child, 3_000);
  }
}


main().catch((error) => {
  process.stderr.write(`${error instanceof Error ? error.stack || error.message : String(error)}\n`);
  process.exitCode = 1;
});
