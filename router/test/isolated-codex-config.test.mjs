import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { isolatedCodexHealthy } from "../src/isolated-codex-config.mjs";

const root = fileURLToPath(new URL("../", import.meta.url));
const manager = path.join(root, "src/config-manager.mjs");

function fixture(t) {
  const home = mkdtempSync(path.join(os.tmpdir(), "jev-isolation-"));
  t.after(() => rmSync(home, { recursive: true, force: true }));
  const state = path.join(home, "codex-router");
  mkdirSync(state);
  writeFileSync(path.join(state, "caller-secret"), "synthetic-isolation-caller-key-long-enough\n", { mode: 0o600 });
  const env = { ...process.env, CODEX_HOME: home, CODEX_ROUTER_STATE_DIR: state,
    CODEX_ROUTER_ISOLATED: "1", CODEX_ROUTER_PORT: "4202" };
  return { home, state, env, run: (command, extraEnv = {}) => execFileSync(process.execPath,
    [manager, command], { env: { ...env, ...extraEnv }, encoding: "utf8" }) };
}

test("isolated enable preserves default settings and is byte-idempotent", (t) => {
  const f = fixture(t);
  const original = 'model = "gpt-6.1-sol"\nmodel_reasoning_effort = "high"\n[desktop]\nfollowUpQueueMode = "queue"\n';
  const config = path.join(f.home, "config.toml");
  writeFileSync(config, original);
  f.run("enable");
  assert.equal(readFileSync(config, "utf8"), original);
  const profile = readFileSync(path.join(f.home, "jev.config.toml"), "utf8");
  assert.match(profile, /model_provider = "jev-router"/);
  assert.match(profile, /requires_openai_auth = false/);
  assert.doesNotMatch(profile, /openai_base_url/);
  assert.match(profile, /caller-key-auth-command.mjs/);
  f.run("enable");
  assert.equal(readFileSync(path.join(f.home, "jev.config.toml"), "utf8"), profile);
  assert.equal(readFileSync(config, "utf8"), original);
  f.run("enable", { CODEX_ROUTER_ISOLATED: "" });
  assert.equal(readFileSync(config, "utf8"), original);
  assert.throws(() => f.run("signed-enable"), /isolated/);
  assert.throws(() => f.run("login-free-enable"), /isolated/);
  assert.throws(() => f.run("router-default-set"), /isolated/);
});

test("legacy managed settings are removed without dropping foreign tables", (t) => {
  const f = fixture(t);
  const config = path.join(f.home, "config.toml");
  writeFileSync(config, `model = "gpt-6.1-sol"
# BEGIN codex-router-managed
openai_base_url = "http://127.0.0.1:4202/v1"
model_catalog_json = "${f.state}/merged-models.json"
# END codex-router-managed
# BEGIN codex-router-provider-managed
[model_providers.codex-router]
name = "Codex Router (external models)"
base_url = "http://127.0.0.1:4202/v1"
wire_api = "responses"
[desktop]
browser-show-full-url = true
# END codex-router-provider-managed
`);
  f.run("enable");
  const result = readFileSync(config, "utf8");
  assert.doesNotMatch(result, /openai_base_url|model_catalog_json|model_providers/);
  assert.match(result, /browser-show-full-url = true/);
  assert.match(result, /model = "gpt-6.1-sol"/);
});

test("user profile conflicts abort before changing either configuration", (t) => {
  const f = fixture(t);
  const config = path.join(f.home, "config.toml");
  const profile = path.join(f.home, "jev.config.toml");
  writeFileSync(config, 'model = "gpt-6.1-sol"\n');
  writeFileSync(profile, 'model = "user-owned"\n');
  assert.throws(() => f.run("enable"), /user-owned/);
  assert.equal(readFileSync(profile, "utf8"), 'model = "user-owned"\n');
  assert.equal(readFileSync(config, "utf8"), 'model = "gpt-6.1-sol"\n');
});

test("a built-in provider table cannot retain a router endpoint", (t) => {
  const f = fixture(t);
  const config = path.join(f.home, "config.toml");
  const original = 'model = "gpt-6.1-sol"\n[model_providers.openai]\nbase_url = "http://localhost:4202/v1"\n';
  writeFileSync(config, original);
  assert.throws(() => f.run("enable"), /global router/);
  assert.equal(readFileSync(config, "utf8"), original);
});

test("doctor's isolation verdict rejects default drift and a missing profile", (t) => {
  const f = fixture(t);
  const config = path.join(f.home, "config.toml");
  writeFileSync(config, 'model = "gpt-6.1-sol"\n');
  f.run("enable");
  assert.equal(isolatedCodexHealthy(JSON.parse(f.run("status"))), true);
  writeFileSync(config, 'model = "jev/auto"\n');
  assert.equal(isolatedCodexHealthy(JSON.parse(f.run("status"))), false);
  writeFileSync(config, 'model = "gpt-6.1-sol"\n');
  rmSync(path.join(f.home, "jev.config.toml"));
  assert.equal(isolatedCodexHealthy(JSON.parse(f.run("status"))), false);
});
