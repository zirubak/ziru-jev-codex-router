import { execFileSync, spawn } from 'node:child_process';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { DesktopContractMismatch, qualifyDesktop } from './desktop-compatibility.mjs';
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

export async function planQualifiedDesktopLaunch(manifest, manifestPath, environment, cacheDirectory, qualify = qualifyDesktop) {
  planDesktopLaunch(manifest, manifestPath, environment, {});
  let observed = { contractVerified: false };
  let compatibilityError = null;
  try {
    await qualify({ app: manifest.app, cacheDirectory });
    observed = { contractVerified: true };
  } catch (error) {
    if (!(error instanceof DesktopContractMismatch)) throw error;
    compatibilityError = error;
  }
  return { plan: planDesktopLaunch(manifest, manifestPath, environment, observed), compatibilityError };
}

export async function observeDesktopCompatibility(manifest, manifestPath, qualify = qualifyDesktop) {
  try {
    await qualify({ app: manifest.app, cacheDirectory: path.join(path.dirname(manifestPath), 'qualifications') });
    return { contractVerified: true };
  } catch (error) {
    if (!(error instanceof DesktopContractMismatch)) throw error;
    return { contractVerified: false, reason: error.message };
  }
}

export async function launchDesktop({
  platform = process.platform,
  manifestPath = process.argv[2],
  environment = process.env,
  home = os.homedir(),
  readManifest = readDesktopManifest,
  listProcesses = () => execFileSync('/bin/ps', ['-axo', 'comm='], { encoding: 'utf8' }),
  qualify = qualifyDesktop,
  activateSession = (session, desktopManifestPath) => execFileSync(
    session.python, [session.script, 'activate', desktopManifestPath], { stdio: 'pipe' },
  ),
  spawnProcess = spawn,
  writeStderr = (message) => process.stderr.write(message),
} = {}) {
  if (platform !== 'darwin') throw new Error('Desktop integration requires macOS');
  if (!manifestPath || !path.isAbsolute(manifestPath)) throw new Error('An absolute Desktop manifest path is required');
  const manifest = readManifest(manifestPath, environment.CODEX_HOME ?? path.join(home, '.codex'));
  // Validate paths before passing them to system utilities or reading artifacts.
  planDesktopLaunch(manifest, manifestPath, environment, {});
  const commands = listProcesses();
  if (commands.split('\n').some((line) => line.trim() === manifest.appExecutable)) {
    throw new Error('Codex is already running. Quit it yourself, then open this launcher. No process was stopped.');
  }
  const observed = await observeDesktopCompatibility(manifest, manifestPath, qualify);
  if (observed.contractVerified && manifest.session) {
    activateSession(manifest.session, manifestPath);
  }
  const plan = planDesktopLaunch(manifest, manifestPath, environment, observed);
  if (observed.reason) writeStderr(`Desktop compatibility: ${observed.reason}\n`);
  if (plan.warning) writeStderr(`${plan.warning}\n`);
  // The caller explicitly starts the app. Installation never invokes this path.
  const child = spawnProcess(plan.executable, plan.args, { env: plan.env, detached: true, windowsHide: true, stdio: 'ignore' });
  child.once('error', (error) => { writeStderr(`${error.message}\n`); process.exitCode = 1; });
  child.unref();
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  launchDesktop().catch((error) => { process.stderr.write(`${error.message}\n`); process.exitCode = 1; });
}
