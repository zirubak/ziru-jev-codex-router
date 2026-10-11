// Idempotently declare all four Jev routes in the protected user-model
// overlay. Existing user-curated routes are preserved.
import {
  readUserModels,
  writeUserModels,
} from "../router/src/user-models.mjs";

export const JEV_MODEL = Object.freeze({
  slug: "jev/auto",
  gatewayModel: "jev-auto",
  compHash: "jev-auto-user-v2",
  upstreamModel: "auto",
  provider: "jev",
  listed: true,
  displayName: "Jev Codex Router by Auto",
  description:
    "Jev selects GPT-6 Luna, GPT-6.1 Sol or GPT-6 Astra and the reasoning effort.",
  priority: 95,
  defaultEffort: "auto",
  reasoningLevels: [{ effort: "auto", description: "Auto" }],
  contextWindow: 258400,
  autoCompact: 219640,
  searchTool: { mode: "hosted" },
  supportsSearchHistory: true,
  inputModalities: ["text", "image"],
});

export const JEV_MANUAL_MODEL = Object.freeze({
  ...JEV_MODEL,
  slug: "jev/manual",
  gatewayModel: "jev-manual",
  upstreamModel: "manual",
  compHash: "jev-manual-user-v1",
  displayName: "Jev Codex Router",
  description: "Jev selects the model while preserving your selected reasoning effort.",
  priority: 96,
  defaultEffort: "medium",
  reasoningLevels: [
    { effort: "low", description: "Light" },
    { effort: "medium", description: "Balanced reasoning" },
    { effort: "high", description: "Deep reasoning" },
    { effort: "xhigh", description: "Extended reasoning" },
    { effort: "max", description: "Maximum reasoning" },
  ],
});

export const JEV_SOL_MODEL = Object.freeze({
  ...JEV_MANUAL_MODEL,
  slug: "jev/sol",
  gatewayModel: "jev-sol",
  upstreamModel: "sol",
  compHash: "jev-sol-user-v1",
  displayName: "Jev Sol Router",
  description: "GPT-6.1 Sol with Jev-selected reasoning effort; the selected effort is ignored.",
  priority: 97,
  defaultEffort: "high",
});

export const JEV_ASTRA_MODEL = Object.freeze({
  ...JEV_SOL_MODEL,
  slug: "jev/astra",
  gatewayModel: "jev-astra",
  upstreamModel: "astra",
  compHash: "jev-astra-user-v1",
  displayName: "Jev Astra Router",
  description: "GPT-6 Astra with Jev-selected reasoning effort; the selected effort is ignored.",
  priority: 98,
});

const declared = [JEV_MODEL, JEV_MANUAL_MODEL, JEV_SOL_MODEL, JEV_ASTRA_MODEL];
const existing = readUserModels();
const preserved = existing.filter((model) =>
  !declared.some((entry) => entry.slug === model?.slug));
writeUserModels([...preserved, ...declared]);
process.stdout.write(`${JSON.stringify({
  configured: declared.map((model) => model.slug),
  preservedModels: preserved.length,
})}\n`);
