import assert from "node:assert/strict";
import { execFile, execFileSync } from "node:child_process";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const binary = process.env.CODEX_ISOLATION_TEST_BIN;
const execute = promisify(execFile);

async function edge(t) {
  const calls = [];
  const server = http.createServer((request, response) => {
    let body = "";
    request.on("data", (chunk) => { body += chunk; });
    request.on("end", () => {
      if (request.method !== "POST") {
        if (request.url.endsWith("/responses")) calls.push({ url: request.url, websocket: true });
        response.writeHead(400);
        response.end("fixture terminal response");
        return;
      }
      calls.push({ url: request.url, model: JSON.parse(body).model,
        authenticated: request.headers.authorization === "Bearer synthetic-isolation-caller-key-long-enough" });
      response.writeHead(400, { "Content-Type": "application/json" });
      response.end('{"error":{"message":"fixture terminal response","type":"invalid_request_error"}}');
    });
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  t.after(() => new Promise((resolve) => server.close(resolve)));
  return { calls, port: server.address().port };
}

test("real Codex HTTP selects the router only with the Jev profile", { skip: !binary }, async (t) => {
  const normal = await edge(t);
  const router = await edge(t);
  const home = mkdtempSync(path.join(os.tmpdir(), "jev-http-isolation-"));
  t.after(() => rmSync(home, { recursive: true, force: true }));
  const state = path.join(home, "codex-router");
  mkdirSync(state);
  writeFileSync(path.join(state, "caller-secret"), "synthetic-isolation-caller-key-long-enough\n", { mode: 0o600 });
  writeFileSync(path.join(home, "config.toml"), `model = "gpt-6.1-sol"\nopenai_base_url = "http://127.0.0.1:${normal.port}/v1"\n`);
  writeFileSync(path.join(state, "merged-models.json"), execFileSync(binary, ["debug", "models", "--bundled"], { encoding: "utf8" }));
  const env = { ...process.env, CODEX_HOME: home, CODEX_ROUTER_STATE_DIR: state,
    CODEX_ROUTER_ISOLATED: "1", CODEX_ROUTER_PORT: String(router.port),
    OPENAI_API_KEY: "synthetic-fixture-api-key", OPENAI_BASE_URL: `http://127.0.0.1:${normal.port}/v1` };
  execFileSync(process.execPath, [path.join(root, "src/config-manager.mjs"), "enable"], { env });
  const invoke = async (args) => {
    try {
      const pending = execute(binary, [...args, "--no-daemon", "exec", "--skip-git-repo-check",
        "-C", home, "--sandbox", "read-only", "Reply only OK; do not use tools."],
      { env, timeout: 30000 });
      pending.child.stdin.end();
      await pending;
      assert.fail("the fixture must return a terminal HTTP error");
    } catch (error) {
      assert.equal(error.killed, false, `Codex must terminate without a timeout: ${error.stderr}`);
      assert.match(error.stderr, /fixture terminal response/);
    }
  };
  await invoke([]);
  assert.ok(normal.calls.length >= 1, "default provider must reach the normal endpoint");
  const normalCount = normal.calls.length;
  assert.equal(router.calls.length, 0, "default provider must never reach the router");
  assert.ok(normal.calls.every((call) => call.url.endsWith("/responses")));
  await invoke(["-p", "jev"]);
  assert.equal(normal.calls.length, normalCount);
  assert.equal(router.calls.length, 1);
  assert.equal(router.calls[0].model, "jev/auto");
  assert.equal(router.calls[0].authenticated, true);
});
