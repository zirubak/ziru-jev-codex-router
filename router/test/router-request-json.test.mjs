import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { callerBaseUrl } from "../src/caller-auth.mjs";
import { openPort } from "./port-pool.mjs";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const CALLER_KEY = "synthetic-json-caller-capability-123456789";

async function routerFixture(t) {
  const directory = await mkdtemp(join(tmpdir(), "router-request-json-"));
  const codexHome = join(directory, "codex");
  const state = join(directory, "state");
  await mkdir(codexHome, { mode: 0o700 });
  await mkdir(state, { mode: 0o700 });
  await writeFile(join(state, "enabled-providers.json"), JSON.stringify({ version: 1, providers: [] }));
  const port = await openPort();
  const child = spawn(process.execPath, [join(root, "src/router.mjs")], {
    cwd: root,
    env: {
      PATH: process.env.PATH,
      HOME: directory,
      TMPDIR: directory,
      CODEX_HOME: codexHome,
      MODEL_ROUTER_STATE_DIR: state,
      CODEX_ROUTER_CALLER_KEY: CALLER_KEY,
      CODEX_ROUTER_INTERNAL_KEY: "synthetic-json-internal-key-123456789",
      CODEX_ROUTER_PORT: String(port),
      CODEX_ROUTER_QUIET: "1",
      CODEX_ROUTER_NO_DISCOVERY: "1",
    },
    stdio: ["ignore", "ignore", "pipe"],
  });
  let stderr = "";
  child.stderr.setEncoding("utf8");
  const ready = new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`Router startup timed out: ${stderr}`)), 5_000);
    timer.unref();
    child.once("error", reject);
    child.once("exit", (code) => reject(new Error(`Router exited ${code}: ${stderr}`)));
    child.stderr.on("data", (chunk) => {
      stderr += chunk;
      if (stderr.includes("[codex-router] listening")) {
        clearTimeout(timer);
        resolve();
      }
    });
  });
  t.after(async () => {
    if (child.exitCode === null && child.signalCode === null) {
      const exited = once(child, "exit");
      child.kill("SIGTERM");
      await exited;
    }
    await rm(directory, { recursive: true, force: true });
  });
  await ready;
  const waitForFailure = (offset) => new Promise((resolve, reject) => {
    let timer;
    const check = () => {
      if (!stderr.slice(offset).includes("[codex-router] request failed:")) return;
      clearTimeout(timer);
      child.stderr.off("data", check);
      resolve();
    };
    timer = setTimeout(() => {
      child.stderr.off("data", check);
      reject(new Error("Router did not record the failed request."));
    }, 5_000);
    timer.unref();
    child.stderr.on("data", check);
    check();
  });
  return { url: `${callerBaseUrl(port, CALLER_KEY)}/responses`, errors: () => stderr, waitForFailure };
}

test("invalid JSON requests return safe diagnostics without copying private input", async (t) => {
  const router = await routerFixture(t);
  const cases = [
    ["invalid first token", "SYNTHETIC_PRIVATE_START"],
    ["invalid object value", '{"input":"valid","tail":SYNTHETIC_PRIVATE_VALUE}'],
    ["unterminated string", '{"input":"SYNTHETIC_PRIVATE_UNTERMINATED'],
    ["trailing token", '{"input":"valid"}SYNTHETIC_PRIVATE_TRAILING'],
    ["non-object scalar", '"SYNTHETIC_PRIVATE_SCALAR"'],
    ["non-object array", '["SYNTHETIC_PRIVATE_ARRAY"]'],
    ["null", "null"],
  ];
  for (const [name, body] of cases) {
    await t.test(name, async () => {
      const offset = router.errors().length;
      const response = await fetch(router.url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
      });
      const text = await response.text();
      await router.waitForFailure(offset);
      const errors = router.errors().slice(offset);
      assert.equal(response.status, 400);
      assert.doesNotMatch(text, /SYNTHETIC|SyntaxError|Unexpected token/);
      assert.doesNotMatch(errors, /SYNTHETIC|SyntaxError|Unexpected token/);
      assert.deepEqual(JSON.parse(text).error, {
        type: "local_router_error",
        code: "invalid_request_json",
        message: "Request body must contain a valid JSON object.",
      });
      assert.match(errors, /Invalid JSON request.*invalid_request_json/);
    });
  }
});
