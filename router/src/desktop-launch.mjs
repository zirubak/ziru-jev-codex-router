import { execFileSync, spawn } from 'node:child_process';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { DesktopContractError, qualifyDesktop } from './desktop-compatibility.mjs';
import { readDesktopManifest } from './desktop-runtime.mjs';

/** The contract verdict, rather than a release allowlist, selects the adapter. */
export function planDesktopLaunch(manifest, manifestPath, environment, observed) {
  if (manifest?.version !== 1) throw new Error('Unsupported Desktop manifest');
  for (const key of ['nativeBinary', 'appExecutable', 'appAsar', 'bridgeBinary']) {
    if (typeof manifest[key] !== 'string' || !path.isAbsolute(manifest[key])) {
      throw new Error(`Desktop ${key} must be absolute`);
    }
  }
  const env = { ...environment };
  delete env.CODEX_CLI_PATH;
  delete env.JEV_DESKTOP_CONFIG;
  delete env.CODEX_APP_SERVER_USE_LOCAL_DAEMON;
  const compatible = observed.contractVerified === true;
  if (compatible) {
    env.CODEX_CLI_PATH = manifest.bridgeLauncher ?? manifest.bridgeBinary;
    env.JEV_DESKTOP_CONFIG = manifestPath;
    env.PATH = `${path.dirname(process.execPath)}${path.delimiter}${env.PATH ?? '/usr/bin:/bin'}`;
  }
  return { executable: manifest.appExecutable, args: [], env,
    mode: compatible ? 'jev' : 'native',
    warning: compatible ? null : 'Desktop compatibility is unverified. Jev chats remain readable; reconnect before sending a Jev request.' };
}

/** Only a failed adapter contract selects native recovery; other failures stop the launch. */
export async function desktopVerdict(qualify) {
  try {
    await qualify();
    return { contractVerified: true, reason: null };
  } catch (error) {
    if (!(error instanceof DesktopContractError)) throw error;
    return { contractVerified: false, reason: error.message };
  }
}

async function main() {
  if (process.platform !== 'darwin') throw new Error('Desktop integration requires macOS');
  const manifestPath = process.argv[2];
  if (!manifestPath || !path.isAbsolute(manifestPath)) throw new Error('An absolute Desktop manifest path is required');
  const manifest = readDesktopManifest(manifestPath, process.env.CODEX_HOME ?? path.join(os.homedir(), '.codex'));
  // Validate paths before passing them to system utilities or reading artifacts.
  planDesktopLaunch(manifest, manifestPath, process.env, {});
  const commands = execFileSync('/bin/ps', ['-axo', 'comm='], { encoding: 'utf8' });
  if (commands.split('\n').some((line) => line.trim() === manifest.appExecutable)) {
    throw new Error('Codex is already running. Quit it yourself, then open this launcher. No process was stopped.');
  }
  const verdict = await desktopVerdict(() => qualifyDesktop({ app: manifest.app,
    cacheDirectory: path.join(path.dirname(manifestPath), 'qualifications') }));
  if (verdict.contractVerified && manifest.session) {
    execFileSync(manifest.session.python, [manifest.session.script, 'activate', manifestPath], { stdio: 'pipe' });
  }
  const plan = planDesktopLaunch(manifest, manifestPath, process.env, verdict);
  if (verdict.reason) process.stderr.write(`${verdict.reason}\n`);
  if (plan.warning) process.stderr.write(`${plan.warning}\n`);
  // The caller explicitly starts the app. Installation never invokes this path.
  const child = spawn(plan.executable, plan.args, { env: plan.env, detached: true, windowsHide: true, stdio: 'ignore' });
  child.once('error', (error) => { process.stderr.write(`${error.message}\n`); process.exitCode = 1; });
  child.unref();
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  main().catch((error) => { process.stderr.write(`${error.message}\n`); process.exitCode = 1; });
}
