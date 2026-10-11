import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

process.env.CODEX_ROUTER_STATE_DIR = mkdtempSync(
  path.join(os.tmpdir(), "jev-fallback-test-"),
);

const { jevFallbackCandidates } = await import("../src/jev-fallback.mjs");

const cloud = {
  slug: "deepseek/deepseek-v4.1-flash",
  provider: "deepseek",
  upstreamModel: "deepseek-v4.1-flash",
  contextWindow: 1_000_000,
  priority: 20,
  inputModalities: ["text", "image"],
  multiAgentVersion: "v2",
};
const jev = {
  slug: "jev/auto",
  provider: "jev",
  upstreamModel: "auto",
  contextWindow: 258_400,
  priority: 1,
};
const local = {
  slug: "local/qwen3:8b",
  provider: "local",
  upstreamModel: "qwen3:8b",
  contextWindow: 32_768,
  priority: 900,
  inputModalities: ["text"],
};
const lmstudio = {
  slug: "lmstudio/qwen3-coder",
  provider: "lmstudio",
  upstreamModel: "qwen3-coder",
  contextWindow: 32_768,
  priority: 950,
  inputModalities: ["text"],
};
const cloudSibling = {
  ...cloud,
  slug: "deepseek/deepseek-v4.1-flash-alias",
  upstreamModel: "deepseek-v4.1-flash-alias",
  priority: 21,
};
const secondCloud = {
  ...cloud,
  slug: "zai-api/glm-5.2",
  provider: "zai-api",
  upstreamModel: "glm-5.2",
  priority: 22,
};

function candidates(overrides = {}) {
  return jevFallbackCandidates({
    models: [jev, cloud, local, lmstudio],
    hidden: new Set(),
    settings: { enabled: true, chain: [] },
    agentChecks: { "qwen3:8b": { agentCapable: true } },
    localRuntime: { running: true },
    limit: 3,
    ...overrides,
  });
}

test("fallback candidates exclude jev and admit only a live qualified local model", () => {
  assert.deepEqual(
    candidates().map((entry) => entry.slug),
    ["local/qwen3:8b", "deepseek/deepseek-v4.1-flash"],
  );
  assert.equal(candidates()[0].local, true);
});

test("an offline or unqualified local model is never selected automatically", () => {
  assert.deepEqual(
    candidates({ localRuntime: { running: false } }).map((entry) => entry.slug),
    ["deepseek/deepseek-v4.1-flash"],
  );
  assert.deepEqual(
    candidates({ agentChecks: { "qwen3:8b": { agentCapable: false } } })
      .map((entry) => entry.slug),
    ["deepseek/deepseek-v4.1-flash"],
  );
});

test("LM Studio needs both its own live inventory and a real agent qualification", () => {
  assert.deepEqual(
    candidates({
      agentChecks: {
        "qwen3:8b": { agentCapable: true },
        "lmstudio/qwen3-coder": { agentCapable: true },
      },
      lmstudioRuntime: { reachable: true, models: ["qwen3-coder"] },
    }).map((entry) => entry.slug),
    [
      "local/qwen3:8b",
      "lmstudio/qwen3-coder",
      "deepseek/deepseek-v4.1-flash",
    ],
  );
  assert.ok(!candidates({
    agentChecks: { "lmstudio/qwen3-coder": { agentCapable: true } },
    lmstudioRuntime: { reachable: false, models: [] },
  }).some((entry) => entry.slug === "lmstudio/qwen3-coder"));
});

test("an explicit chain cannot reintroduce jev recursion or an unqualified local route", () => {
  assert.deepEqual(
    candidates({
      settings: {
        enabled: true,
        chain: ["jev/auto", "local/qwen3:8b", "deepseek/deepseek-v4.1-flash"],
      },
      agentChecks: {},
    }).map((entry) => entry.slug),
    ["deepseek/deepseek-v4.1-flash"],
  );
});

test("all Jev slugs and provider aliases are excluded from fallback", () => {
  const manual = { ...cloud, slug: "jev/manual", provider: "deepseek" };
  const fixed = ["sol", "astra"].map(mode => ({ ...cloud, slug: `jev/${mode}`, provider: "deepseek" }));
  const alias = { ...cloud, slug: "custom/jev", provider: "jev" };
  assert.deepEqual(
    candidates({
      models: [jev, manual, ...fixed, alias, cloud],
      settings: { enabled: true, chain: [manual.slug, ...fixed.map(model => model.slug), alias.slug, cloud.slug] },
    }).map((entry) => entry.slug),
    [cloud.slug],
  );
});

test("manual fallback requires the exact advertised effort before ranking", () => {
  const limited = {
    ...cloud, reasoningLevels: [{ effort: "medium", description: "Balanced" }],
  };
  const supported = {
    ...secondCloud, requestProfile: "glm-thinking",
    reasoningLevels: [
      { effort: "medium", description: "Balanced" },
      { effort: "max", description: "Maximum" },
    ],
  };
  assert.deepEqual(
    candidates({ models: [limited, supported, local], requiredEffort: "max" })
      .map((entry) => entry.slug),
    [secondCloud.slug],
  );
});

test("fallback CLI rejects invalid manual effort rather than ignoring it", () => {
  const result = spawnSync(process.execPath, [
    fileURLToPath(new URL("../src/control.mjs", import.meta.url)),
    "failover", "candidates", "--effort", "ultra",
  ], { env: process.env, encoding: "utf8", timeout: 15_000 });
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /effort/i);
});

test("manual fallback excludes transports that discard an advertised effort", () => {
  const rung = [{ effort: "high", description: "Deep" }];
  assert.deepEqual(candidates({
    requiredEffort: "high",
    models: [
      { ...local, reasoningLevels: rung },
      { ...secondCloud, requestProfile: "glm-thinking", reasoningLevels: rung },
      { ...cloud, requestProfile: "qwen-plan", reasoningLevels: rung },
    ],
  }), []);
});

test("manual fallback excludes xhigh when the chat adapter maps it to max", () => {
  assert.deepEqual(candidates({
    requiredEffort: "xhigh",
    models: [{
      ...secondCloud, requestProfile: "glm-thinking",
      reasoningLevels: [
        { effort: "xhigh", description: "Extended" },
        { effort: "max", description: "Maximum" },
      ],
    }],
  }), []);
});

test("context and capability requirements are applied before the bounded plan", () => {
  assert.deepEqual(
    candidates({ estimatedTokens: 40_000 }).map((entry) => entry.slug),
    ["deepseek/deepseek-v4.1-flash"],
  );
  assert.deepEqual(
    candidates({ needsMultiAgentV2: true }).map((entry) => entry.slug),
    ["deepseek/deepseek-v4.1-flash"],
  );
});

test("the operator's global failover switch disables dynamic Jev candidates", () => {
  assert.deepEqual(
    candidates({ settings: { enabled: false, chain: [] } }),
    [],
  );
});

test("duplicate routes and quota siblings do not consume the bounded fallback plan", () => {
  assert.deepEqual(
    candidates({
      models: [cloud, cloudSibling, secondCloud],
      settings: {
        enabled: true,
        chain: [cloud.slug, cloud.slug, cloudSibling.slug, secondCloud.slug],
      },
      limit: 2,
    }).map((entry) => entry.slug),
    [cloud.slug, secondCloud.slug],
  );
});
