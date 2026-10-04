import { createHash, randomUUID } from 'node:crypto';
import { execFile } from 'node:child_process';
import { constants, closeSync, fstatSync, openSync, readFileSync } from 'node:fs';
import { lstat, mkdir, readFile, rename, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { promisify } from 'node:util';

const execute = promisify(execFile);
const source = path.dirname(fileURLToPath(import.meta.url));
export const CONTRACT_VERSION = 1;
const signingRequirement = 'anchor apple generic and identifier "com.openai.codex" and certificate leaf[subject.OU] = "2DC432GLL2"';
const digest = (value) => createHash('sha256').update(value).digest('hex');

export class DesktopContractMismatch extends Error {
  constructor(message) {
    super(`Jev Desktop compatibility: ${message}`);
    this.name = 'DesktopContractMismatch';
    this.code = 'DESKTOP_INCOMPATIBLE';
  }
}

function contractMismatch(reason) {
  return new DesktopContractMismatch(reason);
}

export function desktopArtifacts(app) {
  if (!path.isAbsolute(app)) throw new Error('Desktop application path must be absolute');
  return {
    appAsar: path.join(app, 'Contents/Resources/app.asar'),
    nativeBinary: path.join(app, 'Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex'),
  };
}

async function identity(app) {
  const files = desktopArtifacts(app);
  const [archive, native] = await Promise.all([readFile(files.appAsar), readFile(files.nativeBinary)]);
  return { expectedAppSha256: digest(archive), expectedNativeSha256: digest(native) };
}

async function contractDigest() {
  const files = ['desktop-compatibility.mjs', 'desktop-contract-probe.mjs',
    'desktop-provider-bridge.mjs', 'desktop-provider-state.mjs', 'desktop-runtime.mjs',
    'desktop-launch.mjs', '../bin/jev-desktop-codex'];
  const data = await Promise.all(files.map((file) => readFile(path.join(source, file))));
  return digest(Buffer.concat([Buffer.from(`${CONTRACT_VERSION}:${process.version}`), ...data]));
}

async function verifySignature(app) {
  try {
    await execute('/usr/bin/codesign', ['--verify', '--deep', '--strict', '-R', `=${signingRequirement}`, app],
      // Desktop's initial policy read has a 30s deadline. Reserve the remaining
      // budget for the bounded native probe, cleanup and normal initialization.
      { timeout: 5000, maxBuffer: 16384, env: { PATH: '/usr/bin:/bin' } });
  } catch {
    throw new Error('Desktop must have a valid OpenAI signature; no adapter was enabled');
  }
}

function readArchiveEntry(file, entry, offset) {
  if (!Number.isSafeInteger(entry.size) || entry.size < 0 || entry.size > 16 * 1024 * 1024
      || !/^\d+$/.test(entry.offset ?? '')) throw contractMismatch('Unsupported Desktop archive layout');
  const start = offset + Number(entry.offset);
  if (!Number.isSafeInteger(start) || start + entry.size > file.length) throw contractMismatch('Incomplete Desktop archive');
  return file.subarray(start, start + entry.size).toString('utf8');
}

async function verifyLaunchHook(app) {
  const file = await readFile(desktopArtifacts(app).appAsar);
  if (file.length < 16) throw contractMismatch('Incomplete Desktop archive');
  const length = file.readUInt32LE(12);
  const offset = 8 + file.readUInt32LE(4);
  if (length > 32 * 1024 * 1024 || offset < 16 + length || offset > file.length) {
    throw contractMismatch('Unsupported Desktop archive header');
  }
  let header;
  try { header = JSON.parse(file.subarray(16, 16 + length)); }
  catch (error) {
    if (error instanceof SyntaxError) throw contractMismatch('Unsupported Desktop archive header');
    throw error;
  }
  if (!header || typeof header !== 'object') throw contractMismatch('Unsupported Desktop archive header');
  const build = header.files?.['.vite']?.files?.build?.files;
  if (!build || Object.keys(build).length > 10000) throw contractMismatch('Unsupported Desktop startup layout');
  const hook = Object.entries(build).some(([name, entry]) => name.endsWith('.js')
    && entry && typeof entry === 'object' && !entry.unpacked && !entry.link
    && readArchiveEntry(file, entry, offset).includes('CODEX_CLI_PATH'));
  if (!hook) throw contractMismatch('Desktop no longer exposes the required CLI launch hook');
}

async function privateDirectory(directory) {
  await mkdir(directory, { recursive: true, mode: 0o700 });
  const info = await lstat(directory);
  if (!info.isDirectory() || info.isSymbolicLink() || info.uid !== process.getuid() || (info.mode & 0o077)) {
    throw new Error('Desktop qualification cache must be private and owner-only');
  }
}

function readReceipt(file, expected) {
  let descriptor;
  try { descriptor = openSync(file, constants.O_RDONLY | constants.O_NOFOLLOW); }
  catch (error) { if (error.code === 'ENOENT') return null; throw error; }
  try {
    const info = fstatSync(descriptor);
    if (!info.isFile() || info.uid !== process.getuid() || (info.mode & 0o077) || info.size > 16384) {
      throw new Error('Unsafe Desktop qualification receipt');
    }
    const contents = readFileSync(descriptor, 'utf8');
    let value;
    try { value = JSON.parse(contents); }
    catch (error) { if (error instanceof SyntaxError) return null; throw error; }
    if (!value || typeof value !== 'object'
        || Object.entries(expected).some(([key, entry]) => value[key] !== entry)
        || !/^codex-cli \S+$/.test(value.nativeVersion ?? '') || value.qualified !== true) return null;
    return value;
  } finally { closeSync(descriptor); }
}

async function writeReceipt(file, value) {
  const temporary = `${file}.${randomUUID()}.tmp`;
  try {
    await writeFile(temporary, `${JSON.stringify(value)}\n`, { mode: 0o600, flag: 'wx' });
    await rename(temporary, file);
  } finally { await rm(temporary, { force: true }); }
}

/** Qualify the observed signed artifacts, never an arbitrary version allowlist. */
export async function qualifyDesktop({ app, cacheDirectory }, dependencies = {}) {
  const sign = dependencies.verifySignature ?? verifySignature;
  const hook = dependencies.verifyLaunchHook ?? verifyLaunchHook;
  const fingerprint = dependencies.contractDigest ?? contractDigest;
  const probe = dependencies.probe ?? (async (binary) =>
    (await import('./desktop-contract-probe.mjs')).probeDesktopContract(binary));
  const before = await identity(app);
  await sign(app);
  const afterSignature = await identity(app);
  if (JSON.stringify(before) !== JSON.stringify(afterSignature)) {
    throw new Error('Desktop changed during signature verification; reopen after the update finishes');
  }
  const expected = { ...before, contractVersion: CONTRACT_VERSION, contractDigest: await fingerprint() };
  let receiptFile;
  let receipt;
  if (cacheDirectory) {
    await privateDirectory(cacheDirectory);
    receiptFile = path.join(cacheDirectory, `${digest(JSON.stringify(expected))}.json`);
    receipt = readReceipt(receiptFile, expected);
  }
  let incompatibilityError;
  if (!receipt) {
    try {
      await hook(app);
      const result = await probe(desktopArtifacts(app).nativeBinary);
      if (!/^codex-cli \S+$/.test(result?.nativeVersion ?? '')) {
        throw contractMismatch('Native contract returned no version evidence');
      }
      receipt = { ...expected, qualified: true, nativeVersion: result.nativeVersion,
        checks: result.checks, checkedAt: new Date().toISOString() };
    } catch (error) {
      if (!(error instanceof DesktopContractMismatch)) throw error;
      incompatibilityError = error;
    }
  }
  // An updater can replace the bundle while qualification is running.
  const after = await identity(app);
  if (JSON.stringify(before) !== JSON.stringify(after) || expected.contractDigest !== await fingerprint()) {
    throw new Error('Desktop or adapter changed during qualification; reopen after the update finishes');
  }
  if (incompatibilityError) throw incompatibilityError;
  if (receiptFile) await writeReceipt(receiptFile, receipt);
  return receipt;
}

async function main() {
  const args = process.argv.slice(2);
  if (args.length !== 2 || args[0] !== '--app') throw new Error('Usage: desktop-compatibility.mjs --app /absolute/Application.app');
  const result = await qualifyDesktop({ app: args[1] });
  process.stdout.write(`${JSON.stringify(result)}\n`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  main().catch((error) => { process.stderr.write(`Desktop compatibility: ${error.message}\n`); process.exitCode = 1; });
}
