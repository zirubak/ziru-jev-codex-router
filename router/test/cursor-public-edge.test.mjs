import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { mkdtempSync, rmSync } from "node:fs";
import http from "node:http";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  createCursorPublicServer,
  cursorPublicBasePath,
  redactCursorPublicUrl,
} from "../src/cursor-public-edge.mjs";
import { cursorModelId } from "../src/cursor-model-id.mjs";

const SECRET = "cursor-public-test-secret-with-sufficient-length";

function listen(server) {
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => resolve(server.address().port));
  });
}

function close(server) {
  return new Promise((resolve) => server.close(resolve));
}

test("Cursor public edge exposes only the secret-bearing app surface", async () => {
  const upstream = http.createServer((_request, response) => {
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify({ output: [] }));
  });
  const upstreamPort = await listen(upstream);
  const edge = createCursorPublicServer({
    publicSecret: SECRET,
    responsesUrl: `http://127.0.0.1:${upstreamPort}/responses`,
    routedModels: () => ({ models: [{ slug: "provider/model" }] }),
  });
  const port = await listen(edge);
  try {
    const prefix = cursorPublicBasePath(SECRET);
    const catalog = await fetch(`http://127.0.0.1:${port}${prefix}/models`);
    assert.equal(catalog.status, 200);
    assert.deepEqual((await catalog.json()).data.map((model) => model.id), [cursorModelId("provider/model")]);
    assert.equal((await fetch(`http://127.0.0.1:${port}/v1/models`)).status, 404);
    assert.equal((await fetch(`http://127.0.0.1:${port}${prefix}/responses`)).status, 404);
    assert.equal(
      redactCursorPublicUrl(`https://edge.example${prefix}`),
      "https://edge.example/_codex-router-cursor/[REDACTED]/v1",
    );
  } finally {
    await Promise.all([close(edge), close(upstream)]);
  }
});

test("malformed unauthenticated Host and URL return 400 without stopping the edge", async (t) => {
  const home = mkdtempSync(path.join(os.tmpdir(), "cursor-edge-malformed-"));
  t.after(() => rmSync(home, { recursive: true, force: true }));
  const moduleUrl = new URL("../src/cursor-public-edge.mjs", import.meta.url).href;
  const source = `import { createCursorPublicServer } from ${JSON.stringify(moduleUrl)};
    const server = createCursorPublicServer({ publicSecret: ${JSON.stringify(SECRET)},
      responsesUrl: 'http://127.0.0.1:1/unused', routedModels: () => ({ models: [] }) });
    server.listen(0, '127.0.0.1', () => console.log(server.address().port));`;
  const child = spawn(process.execPath, ["--input-type=module", "-e", source], {
    env: { PATH: process.env.PATH, HOME: home, CODEX_HOME: path.join(home, "codex"), CODEX_ROUTER_STATE_DIR: path.join(home, "state") },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let errors = "";
  child.stderr.on("data", (chunk) => { errors += chunk; });
  t.after(async () => {
    if (child.exitCode !== null || child.signalCode !== null) return;
    const exited = once(child, "exit");
    child.kill("SIGTERM");
    await exited;
  });
  const ready = await Promise.race([
    once(child.stdout, "data").then(([data]) => Number(String(data).trim())),
    once(child, "exit").then(([code]) => { throw new Error(`Cursor edge exited ${code}: ${errors}`); }),
  ]);
  for (const [target, host] of [["/health", "["], ["http://[", "127.0.0.1"]]) {
    const raw = await new Promise((resolve, reject) => {
      const socket = net.connect(ready, "127.0.0.1", () => {
        socket.write(`GET ${target} HTTP/1.1\r\nHost: ${host}\r\nConnection: close\r\n\r\n`);
      });
      let received = "";
      socket.setEncoding("utf8");
      socket.setTimeout(5_000, () => socket.destroy(new Error("Cursor edge did not answer malformed request")));
      socket.on("data", (chunk) => { received += chunk; });
      socket.once("error", reject);
      socket.once("end", () => resolve(received));
    });
    assert.match(raw, /^HTTP\/1\.1 400 /, errors);
    const health = await fetch(`http://127.0.0.1:${ready}/health`, { signal: AbortSignal.timeout(5_000) });
    assert.equal(health.status, 200);
    assert.equal((await health.json()).ok, true);
    assert.equal(child.exitCode, null);
  }
});
