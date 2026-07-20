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
const TRUSTED_FLAG = "--trusted";
const FULL_TOOLSET = [
  TOOL,
  "system.authorize_candidate_discovery",
  "system.list_profiles",
  "system.open_local_settings",
  "system.revoke_grant",
  "system.validate_profile",
  "system.request_operation_confirmation",
  "system.request_source_grant",
  "system.request_output_grant",
  "system.request_network_grant",
  "study.create_project",
  "study.update_learning_contract",
  "study.list_projects",
  "study.get_project",
  "study.register_inputs",
  "study.start_source_inspection",
  "study.get_source_inspection",
  "study.start_discovery",
  "study.list_candidates",
  "study.get_candidate",
  "study.preview_evidence",
  "study.set_selection",
  "study.plan_cards",
  "study.list_card_plans",
  "study.edit_card_plan",
  "study.validate_card_plans",
  "cards.generate",
  "cards.list",
  "cards.export_apkg",
  "study.get_task",
  "study.cancel_task",
  "study.list_recoverable_tasks",
  "study.resume_task",
  "anki.prepare_import",
  "anki.request_import_confirmation",
  "anki.import_and_verify",
  "study.get_artifact",
  "study.get_audit",
];
const DEVELOPMENT_REQUEST_TIMEOUT_MS = 30_000;
const PACKAGED_REQUEST_TIMEOUT_MS = 120_000;
const TRACE_ENABLED = process.env.ANKI_STUDY_PROBE_TRACE === "1";
const cliArguments = new Set(process.argv.slice(2));
if ([...cliArguments].some((value) => value !== TRUSTED_FLAG)) {
  throw new Error(`Unknown MCP host probe argument: ${[...cliArguments].join(" ")}`);
}
const TRUSTED_DEVELOPMENT = cliArguments.has(TRUSTED_FLAG);


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
  const requestedLauncher = process.env.ANKI_STUDY_PLUGIN_LAUNCHER?.trim();
  if (Boolean(requestedRuntime) !== Boolean(requestedTrust)) {
    throw new Error("Packaged MCP probe requires both runtime package and trust policy paths.");
  }
  if (requestedLauncher && (requestedRuntime || requestedTrust)) {
    throw new Error("Launcher probe cannot also receive direct runtime package inputs.");
  }
  const launcherMode = Boolean(requestedLauncher);
  const packaged = launcherMode || Boolean(requestedRuntime && requestedTrust);
  const fullToolProbe = packaged || TRUSTED_DEVELOPMENT;
  trace(launcherMode ? "mode=launcher" : packaged ? "mode=packaged" : "mode=development");
  const requestTimeoutMs = requestTimeout(packaged);
  const runtimePackage = requestedRuntime ? path.resolve(requestedRuntime) : null;
  const trustPolicy = requestedTrust ? path.resolve(requestedTrust) : null;
  const launcher = launcherMode ? path.resolve(requestedLauncher) : null;
  const python = packaged && !launcherMode
    ? path.join(runtimePackage, "python", process.platform === "win32" ? "python.exe" : "python")
    : resolvePython();
  const serverCommand = launcher || python;
  const serverCwd = launcherMode
    ? path.resolve(path.dirname(launcher), "..", "..")
    : packaged
      ? runtimePackage
      : ROOT;
  for (const required of [
    serverCommand,
    serverCwd,
    ...(packaged && !launcherMode ? [runtimePackage, trustPolicy] : []),
  ]) {
    if (!existsSync(required)) {
      throw new Error(`Packaged MCP probe input is unavailable: ${required}`);
    }
  }
  mkdirSync(PROBE_ROOT, { recursive: true });
  const runRoot = mkdtempSync(
    path.join(PROBE_ROOT, packaged ? "packaged-run-" : "development-run-"),
  );
  const codeHome = path.join(runRoot, "codex-home");
  const stateDir = path.join(runRoot, "card-service-state");
  const localAppData = path.join(runRoot, "local-app-data");
  mkdirSync(codeHome, { recursive: true });
  mkdirSync(stateDir, { recursive: true });
  mkdirSync(localAppData, { recursive: true });
  trace("probe directories ready");

  const serverArgs = launcherMode
    ? ["--stdio"]
    : packaged
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
        ...(TRUSTED_DEVELOPMENT ? ["--development-trusted-mcp-session"] : []),
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
    `mcp_servers.${SERVER}.command=${tomlString(serverCommand)}`,
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
      ...(launcherMode ? { LOCALAPPDATA: localAppData } : {}),
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
      cwd: runRoot,
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
    const registeredTools = Object.keys(registered.tools);
    const expectedTools = fullToolProbe ? FULL_TOOLSET : [TOOL];
    if (
      registeredTools.length !== expectedTools.length ||
      expectedTools.some((name) => !registeredTools.includes(name))
    ) {
      throw new Error(
        `Codex registered an unexpected MCP toolset. Expected ${expectedTools.join(", ")}; ` +
          `received ${registeredTools.join(", ")}.`,
      );
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

    let project = null;
    if (fullToolProbe) {
      const created = await call("mcpServer/tool/call", {
        threadId,
        server: SERVER,
        tool: "study.create_project",
        arguments: {
          context: {
            idempotencyKey: "codex-host-probe-project-v1",
            locale: "zh-CN",
          },
          title: "Codex host probe",
          learningContract: {
            purpose: "Verify the trusted Codex Study tool surface.",
            targetBehavior: "Create one isolated local study project without reading a source.",
            maxNewCards: 1,
            evidencePolicy: "automatic",
          },
        },
      });
      const createdProject = created?.structuredContent;
      if (
        created?.isError === true ||
        typeof createdProject?.projectId !== "string" ||
        createdProject?.projectRevision !== 1 ||
        createdProject?.workflow?.artifactStage !== "empty"
      ) {
        throw new Error("Trusted Codex host could not create an isolated Study project.");
      }
      const updated = await call("mcpServer/tool/call", {
        threadId,
        server: SERVER,
        tool: "study.update_learning_contract",
        arguments: {
          projectId: createdProject.projectId,
          expectedProjectRevision: createdProject.projectRevision,
          expectedContractRevision: createdProject.contractRevision,
          operationId: "codex-host-probe-contract-v1",
          operations: [{ op: "set_learner_level", learnerLevel: "probe" }],
        },
      });
      const updatedProject = updated?.structuredContent;
      if (
        updated?.isError === true ||
        updatedProject?.projectId !== createdProject.projectId ||
        updatedProject?.projectRevision !== 2 ||
        updatedProject?.contractRevision !== 2 ||
        updatedProject?.learningContractRef !== createdProject.learningContractRef ||
        updatedProject?.invalidatedStages?.[0] !== "discovery" ||
        !Array.isArray(updatedProject?.preservedArtifacts)
      ) {
        throw new Error("Trusted Codex host could not update a Learning Contract safely.");
      }
      project = {
        projectId: createdProject.projectId,
        projectRevision: updatedProject.projectRevision,
        contractRevision: updatedProject.contractRevision,
        artifactStage: createdProject.workflow.artifactStage,
      };
      const listed = await call("mcpServer/tool/call", {
        threadId,
        server: SERVER,
        tool: "study.list_projects",
        arguments: { limit: 1 },
      });
      const listedProjects = listed?.structuredContent;
      if (
        listed?.isError === true ||
        listedProjects?.totalProjects !== 1 ||
        listedProjects?.returnedProjects !== 1 ||
        listedProjects?.items?.[0]?.projectId !== project.projectId
      ) {
        throw new Error("Trusted Codex host could not list the isolated Study project.");
      }
      const loaded = await call("mcpServer/tool/call", {
        threadId,
        server: SERVER,
        tool: "study.get_project",
        arguments: { projectId: project.projectId },
      });
      const loadedProject = loaded?.structuredContent;
      if (
        loaded?.isError === true ||
        loadedProject?.projectId !== project.projectId ||
        loadedProject?.projectRevision !== project.projectRevision ||
        loadedProject?.learningContract?.contractRevision !== project.contractRevision ||
        loadedProject?.workflow?.artifactStage !== "empty" ||
        loadedProject?.currentTask !== null ||
        !Array.isArray(loadedProject?.latestArtifacts)
      ) {
        throw new Error("Trusted Codex host could not reload the Study workflow snapshot.");
      }
      trace("trusted Study project created and Learning Contract updated");
    }

    process.stdout.write(
      `${JSON.stringify(
        {
          ok: true,
          mode: launcherMode
            ? "pinned-launcher-packaged-runtime"
            : packaged
              ? "signed-packaged-runtime"
              : TRUSTED_DEVELOPMENT
                ? "development-trusted-session"
                : "development-unpackaged-runtime",
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
            tools: registeredTools,
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
          project,
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
