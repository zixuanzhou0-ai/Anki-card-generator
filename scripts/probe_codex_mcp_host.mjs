import { existsSync, mkdirSync, mkdtempSync } from "node:fs";
import { spawn, spawnSync } from "node:child_process";
import path from "node:path";
import process from "node:process";
import readline from "node:readline";
import { clearTimeout, setTimeout } from "node:timers";


const ROOT = path.resolve(import.meta.dirname, "..");
const PROBE_ROOT = path.join(ROOT, ".tmp", "codex-mcp-host-probe");
const WORKER = path.join(ROOT, "tests", "fixtures", "card_service", "fake_worker.py");
const SERVER = "anki-study-m1";
const TOOL = "system.get_capabilities";
const DEVELOPMENT_REQUEST_TIMEOUT_MS = 30_000;
const PACKAGED_REQUEST_TIMEOUT_MS = 120_000;
const TRACE_ENABLED = process.env.ANKI_STUDY_PROBE_TRACE === "1";


function trace(message) {
  if (TRACE_ENABLED) {
    process.stderr.write(`[mcp-host-probe] ${message}\n`);
  }
}


function requestTimeout(packaged) {
  const configured = process.env.ANKI_STUDY_PROBE_TIMEOUT_MS?.trim();
  if (configured) {
    const value = Number(configured);
    if (!Number.isInteger(value) || value < 5_000 || value > PACKAGED_REQUEST_TIMEOUT_MS) {
      throw new Error("Probe timeout override must be an integer between 5000 and 120000 ms.");
    }
    return value;
  }
  return packaged ? PACKAGED_REQUEST_TIMEOUT_MS : DEVELOPMENT_REQUEST_TIMEOUT_MS;
}


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
    let settled = false;
    const finish = (code) => {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timer);
      resolve(code);
    };
    if (child.exitCode !== null) {
      resolve(child.exitCode);
      return;
    }
    const timer = setTimeout(() => {
      if (process.platform === "win32" && Number.isInteger(child.pid)) {
        spawnSync("taskkill.exe", ["/PID", String(child.pid), "/T", "/F"], {
          windowsHide: true,
          stdio: "ignore",
          timeout: 5_000,
        });
      } else {
        child.kill("SIGKILL");
      }
      finish(child.exitCode);
    }, timeoutMs);
    child.once("exit", finish);
  });
}


async function main() {
  trace("starting");
  const requestedRuntime = process.env.ANKI_STUDY_RUNTIME_PACKAGE?.trim();
  const requestedTrust = process.env.ANKI_STUDY_RUNTIME_TRUST_POLICY?.trim();
  if (Boolean(requestedRuntime) !== Boolean(requestedTrust)) {
    throw new Error("Packaged MCP probe requires both runtime package and trust policy paths.");
  }
  const packaged = Boolean(requestedRuntime && requestedTrust);
  trace(packaged ? "mode=packaged" : "mode=development");
  const requestTimeoutMs = requestTimeout(packaged);
  const runtimePackage = packaged ? path.resolve(requestedRuntime) : null;
  const trustPolicy = packaged ? path.resolve(requestedTrust) : null;
  const python = packaged
    ? path.join(runtimePackage, "python", process.platform === "win32" ? "python.exe" : "python")
    : resolvePython();
  const serverCwd = packaged ? runtimePackage : ROOT;
  for (const required of [python, serverCwd, ...(packaged ? [runtimePackage, trustPolicy] : [])]) {
    if (!existsSync(required)) {
      throw new Error(`Packaged MCP probe input is unavailable: ${required}`);
    }
  }
  mkdirSync(PROBE_ROOT, { recursive: true });
  const runRoot = packaged ? mkdtempSync(path.join(PROBE_ROOT, "packaged-run-")) : PROBE_ROOT;
  const codeHome = path.join(PROBE_ROOT, "codex-home");
  const stateDir = path.join(runRoot, "card-service-state");
  mkdirSync(codeHome, { recursive: true });
  mkdirSync(stateDir, { recursive: true });
  trace("probe directories ready");

  const serverArgs = packaged
    ? [
        "-E",
        "-s",
        "-B",
        "-m",
        "card_service.mcp_stdio",
        "--state-dir",
        stateDir,
        "--runtime-package",
        runtimePackage,
        "--runtime-trust-policy",
        trustPolicy,
      ]
    : [
        "-m",
        "card_service.mcp_stdio",
        "--state-dir",
        stateDir,
        "--development-unpackaged-runtime",
        "--worker",
        WORKER,
        "--python",
        python,
      ];
  const codex = resolveCodex();
  trace("Codex command resolved");
  const codexArgs = [
    ...codex.argsPrefix,
    "app-server",
    "--disable",
    "plugins",
    "--disable",
    "remote_plugin",
    "--stdio",
    "-c",
    `mcp_servers.${SERVER}.command=${tomlString(python)}`,
    "-c",
    `mcp_servers.${SERVER}.args=${tomlArray(serverArgs)}`,
    "-c",
    `mcp_servers.${SERVER}.cwd=${tomlString(serverCwd)}`,
    "-c",
    `mcp_servers.${SERVER}.startup_timeout_sec=${packaged ? 120 : 30}`,
    "-c",
    `mcp_servers.${SERVER}.tool_timeout_sec=30`,
  ];

  const child = spawn(codex.command, codexArgs, {
    cwd: serverCwd,
    env: {
      ...process.env,
      CODEX_HOME: codeHome,
    },
    stdio: ["pipe", "pipe", "pipe"],
    windowsHide: true,
  });
  trace("Codex app-server spawned");
  child.stdin.setDefaultEncoding("utf8");
  child.stdout.setEncoding("utf8");
  child.stderr.setEncoding("utf8");

  let nextId = 1;
  let stderr = "";
  let childFailure = null;
  const pending = new Map();
  const lines = readline.createInterface({ input: child.stdout, crlfDelay: Infinity });
  child.stderr.on("data", (chunk) => {
    stderr += chunk;
  });
  const failPending = (error) => {
    childFailure = error;
    for (const entry of pending.values()) {
      clearTimeout(entry.timer);
      entry.reject(error);
    }
    pending.clear();
  };
  child.once("error", (error) => {
    trace("Codex app-server emitted an error");
    failPending(new Error(`Codex app-server could not start: ${error.message}`));
  });
  child.once("exit", (code, signal) => {
    trace(`Codex app-server exited code=${code} signal=${signal}`);
    failPending(
      new Error(`Codex app-server exited before probe completion (code=${code}, signal=${signal}).`),
    );
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
      if (childFailure || child.exitCode !== null) {
        reject(childFailure || new Error("Codex app-server is not running."));
        return;
      }
      const timer = setTimeout(() => {
        pending.delete(id);
        reject(new Error(`${method}: timed out after ${requestTimeoutMs}ms`));
      }, requestTimeoutMs);
      pending.set(id, { method, resolve, reject, timer });
      child.stdin.write(`${JSON.stringify({ id, method, params })}\n`);
    });
  }

  try {
    trace("calling initialize");
    const initialized = await call("initialize", {
      clientInfo: {
        name: "anki_study_mcp_host_probe",
        title: "Anki Study MCP Host Probe",
        version: "0.1.0",
      },
    });
    trace("initialize completed");
    notify("initialized");

    const started = await call("thread/start", {
      cwd: ROOT,
      ephemeral: true,
      approvalPolicy: "never",
      sandbox: "read-only",
    });
    trace("ephemeral thread started");
    const threadId = started?.thread?.id;
    if (typeof threadId !== "string" || !threadId) {
      throw new Error("Codex app-server did not return an ephemeral thread id.");
    }

    let registered;
    const deadline = Date.now() + requestTimeoutMs;
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
    trace("MCP tool registered");
    if (Object.keys(registered.tools).some((name) => name !== TOOL)) {
      throw new Error("Codex registered an MCP tool outside the M1 read-only allowlist.");
    }

    const called = await call("mcpServer/tool/call", {
      threadId,
      server: SERVER,
      tool: TOOL,
      arguments: {},
    });
    trace("MCP tool call completed");
    const structured = called?.structuredContent;
    if (
      called?.isError === true ||
      structured?.mcpBridge?.transport !== "stdio" ||
      structured?.cardService?.genericShell !== false ||
      structured?.cardService?.secretBearingRequests !== false
    ) {
      throw new Error("Codex tool call returned an invalid or unsafe capability snapshot.");
    }
    if (
      packaged &&
      (structured?.cardService?.runtimePackage?.signatureVerified !== true ||
        structured?.cardService?.processIsolation?.runtimePackageDacl !== true)
    ) {
      throw new Error("Packaged Codex host did not verify the signed runtime and exact DACL.");
    }

    process.stdout.write(
      `${JSON.stringify(
        {
          ok: true,
          mode: packaged ? "signed-packaged-runtime" : "development-unpackaged-runtime",
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
            runtimeSignatureVerified:
              structured.cardService.runtimePackage?.signatureVerified ?? false,
            runtimePackageDacl:
              structured.cardService.processIsolation?.runtimePackageDacl ?? false,
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
