import { createHash } from 'node:crypto';
import { execFileSync, spawn } from 'node:child_process';
import { constants, closeSync, fstatSync, openSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

/** Build a process-only override. Unknown app builds retain native operation. */
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
  const compatible = /^[a-f0-9]{64}$/.test(manifest.expectedAppSha256 ?? '')
    && /^[a-f0-9]{64}$/.test(manifest.expectedNativeSha256 ?? '')
    && observed.appSha256 === manifest.expectedAppSha256
    && observed.nativeSha256 === manifest.expectedNativeSha256;
  if (compatible) {
    env.CODEX_CLI_PATH = manifest.bridgeBinary;
    env.JEV_DESKTOP_CONFIG = manifestPath;
    env.PATH = `${path.dirname(process.execPath)}${path.delimiter}${env.PATH ?? '/usr/bin:/bin'}`;
  }
  return { executable: manifest.appExecutable, args: [], env,
    mode: compatible ? 'jev' : 'native',
    warning: compatible ? null : 'Desktop updated: Jev is disabled until compatibility is verified. Opening ordinary Codex.' };
}

function readManifest(filename) {
  const fd = openSync(filename, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    const info = fstatSync(fd);
    if (!info.isFile() || info.uid !== process.getuid() || (info.mode & 0o077)) {
      throw new Error('Desktop manifest must be an owner-only regular file');
    }
    return JSON.parse(readFileSync(fd, 'utf8'));
  } finally { closeSync(fd); }
}

async function main() {
  if (process.platform !== 'darwin') throw new Error('Desktop integration requires macOS');
  const manifestPath = process.argv[2];
  if (!manifestPath || !path.isAbsolute(manifestPath)) throw new Error('An absolute Desktop manifest path is required');
  const manifest = readManifest(manifestPath);
  // Validate paths before passing them to system utilities or reading artifacts.
  planDesktopLaunch(manifest, manifestPath, process.env, {});
  const commands = execFileSync('/bin/ps', ['-axo', 'comm='], { encoding: 'utf8' });
  if (commands.split('\n').some((line) => line.trim() === manifest.appExecutable)) {
    throw new Error('Codex is already running. Quit it yourself, then open this launcher. No process was stopped.');
  }
  const appBundle = path.resolve(manifest.appExecutable, '../../..');
  execFileSync('/usr/bin/codesign', ['--verify', '--deep', '--strict', appBundle], { stdio: 'pipe' });
  const digest = (file) => createHash('sha256').update(readFileSync(file)).digest('hex');
  const plan = planDesktopLaunch(manifest, manifestPath, process.env, {
    appSha256: digest(manifest.appAsar), nativeSha256: digest(manifest.nativeBinary),
  });
  if (plan.warning) process.stderr.write(`${plan.warning}\n`);
  // The caller explicitly starts the app. Installation never invokes this path.
  const child = spawn(plan.executable, plan.args, { env: plan.env, detached: true, windowsHide: true, stdio: 'ignore' });
  child.once('error', (error) => { process.stderr.write(`${error.message}\n`); process.exitCode = 1; });
  child.unref();
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  main().catch((error) => { process.stderr.write(`${error.message}\n`); process.exitCode = 1; });
}
