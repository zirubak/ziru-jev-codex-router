// The official provider and catalog remain client-owned. Jev is an explicit
// profile so selecting a custom model cannot retain the ChatGPT provider.
import { existsSync, lstatSync, mkdirSync, readFileSync, renameSync, unlinkSync, writeFileSync } from "node:fs";
import path from "node:path";
import { assertCallerSecret, redactCallerUrl } from "./caller-auth.mjs";
import { CALLER_SECRET_PATH, CODEX_HOME, CONFIG_PATH, MERGED_CATALOG_PATH, PORTS, SOURCE_ROOT, STATE_DIR, loopback } from "./paths.mjs";
import { scanTomlDocument, tomlStringValue } from "./toml-structure.mjs";

export const ISOLATED_POLICY_PATH = path.join(STATE_DIR, "isolated-codex.json");
export const JEV_PROFILE_PATH = path.join(CODEX_HOME, "jev.config.toml");
const marker = "# Jev managed isolated profile v1";

export function isolatedCodexConfigured() {
  if (existsSync(ISOLATED_POLICY_PATH)) {
    const policy = JSON.parse(readFileSync(ISOLATED_POLICY_PATH, "utf8"));
    if (policy.version !== 1 || policy.mode !== "isolated") {
      throw new Error("Invalid isolated Codex policy; refusing global routing.");
    }
    return true;
  }
  return process.env.CODEX_ROUTER_ISOLATED === "1";
}

function assertRegular(file) {
  try {
    if (!lstatSync(file).isFile()) throw new Error(`Refusing non-regular configuration: ${file}`);
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
}

function atomicWrite(file, text) {
  assertRegular(file);
  if (existsSync(file) && readFileSync(file, "utf8") === text) return;
  mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  const temporary = `${file}.tmp.${process.pid}`;
  let created = false;
  try {
    writeFileSync(temporary, text, { encoding: "utf8", mode: 0o600, flag: "wx" });
    created = true;
    renameSync(temporary, file);
  } finally {
    if (created && existsSync(temporary)) unlinkSync(temporary);
  }
}

export function isolatedCodexHealthy(status) {
  return status.mode === "isolated" && status.profile_present && status.isolation_valid;
}

function routerEndpoint(value) {
  if (!value) return false;
  const url = new URL(value);
  return ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) &&
    [String(PORTS.router), "4202", "4102"].includes(url.port);
}

export function assertDefaultIsSafe(contents) {
  const doc = scanTomlDocument(contents);
  const provider = tomlStringValue(doc, [], "model_provider");
  const model = tomlStringValue(doc, [], "model");
  if (["codex-router", "codex-router-signed", "jev-router"].includes(provider) || model?.startsWith("jev/")) {
    throw new Error("Default selects a routed model/provider; select an official default before isolated install.");
  }
  const base = tomlStringValue(doc, [], "openai_base_url");
  const builtinBase = tomlStringValue(doc, ["model_providers", "openai"], "base_url");
  const selectedBase = tomlStringValue(doc, ["model_providers", provider || "openai"], "base_url");
  if ([base, builtinBase, selectedBase].some(routerEndpoint)) {
    throw new Error("Unowned global router URL; remove it explicitly before isolated install.");
  }
  if (tomlStringValue(doc, [], "model_catalog_json") === MERGED_CATALOG_PATH) {
    throw new Error("Unowned global router catalog; remove it explicitly before isolated install.");
  }
}

function profileContents() {
  assertCallerSecret(readFileSync(CALLER_SECRET_PATH, "utf8").trim());
  return `${marker}
model = "jev/auto"
model_provider = "jev-router"
model_catalog_json = ${JSON.stringify(MERGED_CATALOG_PATH)}

[model_providers.jev-router]
name = "Jev Router"
base_url = ${JSON.stringify(loopback(PORTS.router, "/v1"))}
wire_api = "responses"
requires_openai_auth = false
supports_standalone_web_search = true

[model_providers.jev-router.auth]
command = ${JSON.stringify(process.execPath)}
args = [${JSON.stringify(path.join(SOURCE_ROOT, "src/caller-key-auth-command.mjs"))}, ${JSON.stringify(CALLER_SECRET_PATH)}]
timeout_ms = 5000
refresh_interval_ms = 0
`;
}

export function manageIsolatedCodex(command, current, cleaned) {
  if (!["status", "enable", "disable", "caller-capability-refresh"].includes(command)) {
    throw new Error(`Global provider/default changes are prohibited in isolated mode (${command}); use codex -p jev.`);
  }
  if (command !== "status") {
    assertRegular(CONFIG_PATH);
    assertRegular(JEV_PROFILE_PATH);
    assertDefaultIsSafe(cleaned);
    if (existsSync(JEV_PROFILE_PATH) && !readFileSync(JEV_PROFILE_PATH, "utf8").startsWith(`${marker}\n`)) {
      throw new Error("Refusing to replace user-owned jev.config.toml.");
    }
    // Persist isolation before any client mutation. Repair and refresh commands
    // cannot subsequently fall back to the legacy global writer.
    const profile = command === "disable" ? undefined : profileContents();
    atomicWrite(ISOLATED_POLICY_PATH, '{"version":1,"mode":"isolated"}\n');
    if (current !== cleaned) atomicWrite(CONFIG_PATH, cleaned);
    if (profile) atomicWrite(JEV_PROFILE_PATH, profile);
    else if (existsSync(JEV_PROFILE_PATH)) unlinkSync(JEV_PROFILE_PATH);
  }
  const doc = scanTomlDocument(command === "status" ? current : cleaned);
  const base = tomlStringValue(doc, [], "openai_base_url");
  let isolationValid = true;
  try { assertDefaultIsSafe(command === "status" ? current : cleaned); }
  catch { isolationValid = false; }
  return { mode: "isolated", isolation_valid: isolationValid,
    model_provider: tomlStringValue(doc, [], "model_provider") || "openai",
    openai_base_url: base ? redactCallerUrl(base) : null,
    model_catalog_json: tomlStringValue(doc, [], "model_catalog_json") || null,
    profile: JEV_PROFILE_PATH, profile_present: existsSync(JEV_PROFILE_PATH),
    signed_routing: false, login_free: false };
}
