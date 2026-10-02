import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const shellAvailable = spawnSync("sh", ["-c", "exit 0"]).status === 0;
const installerSupported = ["darwin", "linux"].includes(process.platform);

test("embedded reinstall failure preserves an existing isolated profile", { skip: !installerSupported ? "POSIX installer supports Darwin/Linux; Windows uses its own installer" : !shellAvailable ? "sh is unavailable" : false }, (t) => {
  const dir = mkdtempSync(path.join(os.tmpdir(), "jev-install-rollback-"));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  for (const folder of ["repo/bin", "repo/src", "commands", "home/state"]) mkdirSync(path.join(dir, folder), { recursive: true });
  const installer = path.join(dir, "repo/bin/install");
  writeFileSync(installer, readFileSync(path.join(root, "bin/install")), { mode: 0o755 });
  const home = path.join(dir, "home");
  const profile = path.join(home, "jev.config.toml");
  const config = path.join(home, "config.toml");
  writeFileSync(config, 'model = "gpt-6.1-sol"\n');
  writeFileSync(profile, '# Jev managed isolated profile v1\nmodel = "jev/auto"\n');
  writeFileSync(path.join(home, "state/native-models.json"), '{"models":[{"slug":"native"}]}');
  const shim = `#!/bin/sh
if [ "$1" = "-e" ]; then exec ${JSON.stringify(process.execPath)} "$@"; fi
case "$1:$2" in
  src/install-plan.mjs:status) echo skip ;;
  src/config-manager.mjs:status) echo '{"mode":"isolated","profile_present":true}' ;;
  src/config-manager.mjs:disable) rm "$CODEX_HOME/jev.config.toml" ;;
  src/service.mjs:status) echo '{"installed":true}' ;;
  src/service.mjs:install) exit 7 ;;
esac
exit 0
`;
  writeFileSync(path.join(dir, "commands/node"), shim, { mode: 0o755 });
  writeFileSync(path.join(dir, "commands/npm"), "#!/bin/sh\nexit 0\n", { mode: 0o755 });
  const original = readFileSync(profile, "utf8");
  const result = spawnSync("sh", [installer], { encoding: "utf8", env: {
    ...process.env, CODEX_HOME: home, CODEX_ROUTER_STATE_DIR: path.join(home, "state"),
    MODEL_ROUTER_TARGET: "codex", PATH: `${path.join(dir, "commands")}:${process.env.PATH}`,
    CODEX_ROUTER_NODE_BIN: path.join(dir, "commands/node"),
  } });
  assert.equal(result.status, 7, result.stderr);
  assert.equal(readFileSync(profile, "utf8"), original);
  assert.equal(readFileSync(config, "utf8"), 'model = "gpt-6.1-sol"\n');
});
