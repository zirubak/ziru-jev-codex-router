import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { childOutput, waitForListeners } from "./listener-readiness.mjs";
import { openPort } from "./port-pool.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const CALLER_KEY = "synthetic-gateway-caller-with-sufficient-length";
const INTERNAL_KEY = "synthetic-gateway-internal-with-sufficient-length";
const MODEL = "opencode-go/glm-5.3";
const OVERRIDES = {
  api_base: "https://synthetic-unreachable.invalid/v1",
  base_url: "https://synthetic-unreachable.invalid/v1",
  api_key: "synthetic-client-credential",
  api_version: "synthetic-version",
  custom_llm_provider: "openai",
  api_type: "azure",
  organization: "synthetic-organization",
  project: "synthetic-project",
  deployment_id: "synthetic-deployment",
  credential_name: "synthetic-credential",
  litellm_credential_name: "synthetic-credential",
  azure_ad_token: "synthetic-client-credential",
  aws_access_key_id: "synthetic-client-credential",
  aws_secret_access_key: "synthetic-client-credential",
  aws_session_token: "synthetic-client-credential",
  aws_web_identity_token: "synthetic-client-credential",
  aws_role_name: "synthetic-role",
  aws_sts_endpoint: "https://synthetic-unreachable.invalid/",
  aws_bedrock_runtime_endpoint: "https://synthetic-unreachable.invalid/",
  s3_endpoint_url: "https://synthetic-unreachable.invalid/",
  sagemaker_base_url: "https://synthetic-unreachable.invalid/",
  deployment_url: "https://synthetic-unreachable.invalid/",
  vertex_credentials: "synthetic-client-credential",
  vertex_ai_credentials: "synthetic-client-credential",
  vertex_project: "synthetic-project",
  vertex_location: "synthetic-location",
  user_config: { api_base: "https://synthetic-unreachable.invalid/v1" },
  model_list: [{ model_name: "synthetic", litellm_params: { api_base: "https://synthetic-unreachable.invalid/v1" } }],
  fallbacks: [{ synthetic: ["synthetic-other"] }],
  context_window_fallbacks: [{ synthetic: ["synthetic-other"] }],
  content_policy_fallbacks: [{ synthetic: ["synthetic-other"] }],
  router_settings_override: { fallbacks: ["synthetic-other"] },
  litellm_params: { api_key: "synthetic-client-credential" },
  litellm_embedding_config: { api_base: "https://synthetic-unreachable.invalid/v1" },
  litellm_settings: { api_base: "https://synthetic-unreachable.invalid/v1" },
  headers: { Authorization: "Bearer synthetic-client-credential" },
  extra_headers: { Authorization: "Bearer synthetic-client-credential" },
  extra_query: { api_key: "synthetic-client-credential" },
};

function isolatedEnvironment(home) {
  return {
    PATH: process.env.PATH,
    HOME: home,
    CODEX_HOME: path.join(home, "codex"),
    CODEX_ROUTER_STATE_DIR: path.join(home, "state"),
    CODEX_ROUTER_NO_DISCOVERY: "1",
    CODEX_ROUTER_CALLER_KEY: CALLER_KEY,
    CODEX_ROUTER_INTERNAL_KEY: INTERNAL_KEY,
    CODEX_ROUTER_SHOW_ALL_MODELS: "1",
    CODEX_ROUTER_QUIET: "1",
    CODEX_ROUTER_NATIVE_SESSION_FALLBACK: "0",
  };
}

async function fixture(t) {
  const home = mkdtempSync(path.join(os.tmpdir(), "router-gateway-boundary-"));
  t.after(() => rmSync(home, { recursive: true, force: true }));
  const captured = [];
  const upstream = http.createServer(async (request, response) => {
    const chunks = [];
    for await (const chunk of request) chunks.push(chunk);
    if (request.method === "POST") captured.push({
      path: request.url,
      body: JSON.parse(Buffer.concat(chunks).toString("utf8")),
      authorization: request.headers.authorization,
      nativeLite: request.headers["x-openai-internal-codex-responses-lite"],
    });
    response.writeHead(200, { "Content-Type": "application/json" });
    response.end(JSON.stringify({
      id: "resp_synthetic", object: "response", status: "completed", model: "opencode-go-glm-5-3",
      output: [{ type: "message", role: "assistant", content: [{ type: "output_text", text: "Synthetic response." }] }],
    }));
  });
  upstream.listen(0, "127.0.0.1");
  await once(upstream, "listening");
  t.after(() => new Promise((resolve) => upstream.close(resolve)));
  const base = `http://127.0.0.1:${upstream.address().port}`;
  mkdirSync(path.join(home, "state"));
  const providersPath = path.join(home, "generic-providers.json");
  const modelsPath = path.join(home, "user-models.json");
  writeFileSync(providersPath, JSON.stringify({ version: 1, providers: [{
    id: "jev", displayName: "Synthetic Jev", baseUrl: `${base}/api`,
    adapter: "openai-responses", headers: {}, allowPrivate: true, enabled: true,
  }] }));
  writeFileSync(modelsPath, JSON.stringify({ version: 1, models: [{
    slug: "jev/auto", gatewayModel: "jev-auto", upstreamModel: "auto", provider: "jev",
    listed: true, displayName: "Synthetic Jev", description: "Isolated test.", priority: 95,
    defaultEffort: "medium", reasoningLevels: [{ effort: "medium", description: "Balanced" }],
    contextWindow: 258400, autoCompact: 219640, inputModalities: ["text", "image"], compHash: "synthetic-jev",
  }] }));
  const port = await openPort();
  const output = childOutput();
  const child = output.capture("router", spawn(process.execPath, [path.join(ROOT, "src/router.mjs")], {
    cwd: ROOT,
    env: {
      ...isolatedEnvironment(home),
      MODEL_ROUTER_GENERIC_PROVIDERS: providersPath,
      MODEL_ROUTER_USER_MODELS: modelsPath,
      CODEX_ROUTER_PORT: String(port),
      CODEX_ROUTER_GATEWAY_BASE_URL: `${base}/gateway`,
      CODEX_ROUTER_API_BASE_URL: `${base}/api`,
      CODEX_NATIVE_BASE_URL: `${base}/native`,
      CODEX_ROUTER_OAUTH_HEALTH_URL: `${base}/health`,
      CODEX_ROUTER_API_HEALTH_URL: `${base}/health`,
      CODEX_ROUTER_GATEWAY_HEALTH_URL: `${base}/health`,
      CODEX_ROUTER_GROK_OAUTH_HEALTH_URL: `${base}/health`,
    },
    stdio: ["ignore", "ignore", "pipe"],
  }));
  t.after(async () => {
    if (child.exitCode !== null || child.signalCode !== null) return;
    const exited = once(child, "exit");
    child.kill("SIGTERM");
    await exited;
  });
  const routerBase = `http://127.0.0.1:${port}/_codex-router/${CALLER_KEY}/v1`;
  await waitForListeners([{ name: "isolated router", url: `${routerBase}/models` }], { children: [child], output });
  return {
    captured,
    request: (body, { endpoint = "responses", headers = {} } = {}) => fetch(`${routerBase}/${endpoint}`, {
      method: "POST", headers: { "Content-Type": "application/json", ...headers },
      body: JSON.stringify({ model: MODEL, input: [], tools: [], stream: false, ...body }),
      signal: AbortSignal.timeout(10_000),
    }),
  };
}

test("gateway rejects caller transport and credential controls before any upstream call", async (t) => {
  const { captured, request } = await fixture(t);
  for (const endpoint of ["responses", "responses/compact"]) {
    for (const [field, value] of Object.entries(OVERRIDES)) {
      for (const nested of [false, true]) {
        await t.test(`${endpoint} rejects ${nested ? "extra_body." : ""}${field}`, async () => {
          captured.length = 0;
          const response = await request(nested ? { extra_body: { [field]: value } } : { [field]: value }, { endpoint });
          const body = await response.json();
          assert.equal(response.status, 400);
          assert.equal(body.error.code, "gateway_request_override");
          assert.equal(captured.length, 0);
          assert.equal(JSON.stringify(body).includes("synthetic-client-credential"), false);
        });
      }
    }
    for (const extraBody of [
      { model: "unregistered-model" },
      { extra_body: { api_key: "synthetic-client-credential" } },
      JSON.stringify({ api_base: "https://synthetic-unreachable.invalid/v1" }),
      [{ api_key: "synthetic-client-credential" }],
    ]) {
      await t.test(`${endpoint} rejects nested or malformed gateway overrides`, async () => {
        captured.length = 0;
        const response = await request({ extra_body: extraBody }, { endpoint });
        assert.equal(response.status, 400);
        assert.equal((await response.json()).error.code, "gateway_request_override");
        assert.equal(captured.length, 0);
      });
    }
  }
});

test("gateway keeps inference options, tool schemas and conversation data intact", async (t) => {
  const { captured, request } = await fixture(t);
  const tool = { type: "function", name: "inspect_config", description: "Inspect configuration data.", parameters: {
    type: "object", properties: { api_base: { type: "string" }, api_key: { type: "string" } }, required: ["api_base"],
  } };
  const input = [{ role: "user", content: "Describe api_base and api_key without changing transport." }];
  const metadata = { api_key: "a-field-label" };
  const extraBody = { thinking: { type: "enabled", budget_tokens: 1024 }, service_tier: "priority" };
  const response = await request({ tools: [tool], input, metadata, extra_body: extraBody, temperature: 0.4 });
  assert.equal(response.status, 200);
  await response.arrayBuffer();
  assert.equal(captured.length, 1);
  assert.equal(captured[0].path, "/gateway/responses");
  assert.equal(captured[0].authorization, `Bearer ${INTERNAL_KEY}`);
  assert.deepEqual(captured[0].body.tools.find(({ name }) => name === tool.name), tool);
  assert.deepEqual(captured[0].body.input, input);
  assert.deepEqual(captured[0].body.metadata, metadata);
  assert.deepEqual(captured[0].body.extra_body, extraBody);
  assert.equal(captured[0].body.temperature, 0.4);
});

test("native Jev replay bypasses only the gateway admission policy", async (t) => {
  const { captured, request } = await fixture(t);
  const input = [{ type: "additional_tools", role: "developer", tools: [{ type: "function", name: "probe", parameters: { type: "object" } }] }];
  const response = await request({ model: "jev/auto", input, extra_body: { api_base: "canonical-data" } }, {
    headers: { "x-openai-internal-codex-responses-lite": "true" },
  });
  assert.equal(response.status, 200);
  await response.arrayBuffer();
  assert.equal(captured.length, 1);
  assert.equal(captured[0].path, "/api/responses");
  assert.equal(captured[0].nativeLite, "true");
  assert.deepEqual(captured[0].body.input, input);
  assert.deepEqual(captured[0].body.extra_body, { api_base: "canonical-data" });
});

test("generated gateway config disables client credentials while retaining operator deployments", async (t) => {
  const home = mkdtempSync(path.join(os.tmpdir(), "gateway-config-boundary-"));
  t.after(() => rmSync(home, { recursive: true, force: true }));
  const child = spawn(process.execPath, ["--input-type=module", "-e",
    "import { renderLiteLlmConfig } from './src/litellm-config.mjs'; process.stdout.write(renderLiteLlmConfig());"], {
    cwd: ROOT, env: isolatedEnvironment(home), stdio: ["ignore", "pipe", "pipe"],
  });
  let rendered = "";
  child.stdout.on("data", (chunk) => { rendered += chunk; });
  const [code] = await once(child, "exit");
  assert.equal(code, 0);
  assert.match(rendered, /general_settings:\n(?:  [^\n]*\n)*  allow_client_side_credentials: false\n/);
  assert.match(rendered, /api_base: "os.environ\/CODEX_ROUTER_API_FORWARD_BASE_URL"/);
  assert.match(rendered, /api_key: "os.environ\/CODEX_ROUTER_INTERNAL_KEY"/);
});
