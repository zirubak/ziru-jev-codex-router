import { constants, closeSync, fstatSync, openSync, readFileSync, realpathSync } from 'node:fs';
import path from 'node:path';
import { desktopArtifacts } from './desktop-compatibility.mjs';

const valueOptions = new Set(['-c', '--config', '-p', '--profile', '--enable', '--disable']);

/** Only the actual stdio service is a bridge; CLI commands retain native I/O. */
export function isStdioAppServer(args) {
  let index = 0;
  while (valueOptions.has(args[index]) && args[index + 1] !== undefined) index += 2;
  if (args[index++] !== 'app-server') return false;
  while (index < args.length) {
    const argument = args[index++];
    if (argument === '--analytics-default-enabled') continue;
    if (valueOptions.has(argument) && args[index] !== undefined) { index += 1; continue; }
    if (argument === '--listen' && args[index++] === 'stdio://') continue;
    if (argument === '--listen=stdio://') continue;
    return false;
  }
  return true;
}

export function readDesktopManifest(file, currentHome) {
  if (!file || !path.isAbsolute(file)) throw new Error('A private Desktop manifest is required');
  const descriptor = openSync(file, constants.O_RDONLY | constants.O_NOFOLLOW);
  let manifest;
  try {
    const info = fstatSync(descriptor);
    if (!info.isFile() || info.uid !== process.getuid() || (info.mode & 0o077) || info.size > 32768) {
      throw new Error('Unsafe Desktop manifest');
    }
    manifest = JSON.parse(readFileSync(descriptor, 'utf8'));
  } finally { closeSync(descriptor); }
  if (manifest.version !== 1 || !path.isAbsolute(manifest.codexHome ?? '')
      || realpathSync(currentHome) !== realpathSync(manifest.codexHome)) {
    throw new Error('This Codex home has not enabled the Desktop bridge');
  }
  for (const key of ['nativeBinary', 'appExecutable', 'appAsar', 'bridgeBinary', 'routeStateDirectory']) {
    if (!path.isAbsolute(manifest[key] ?? '')) throw new Error('Invalid Desktop manifest paths');
  }
  const app = path.resolve(manifest.appExecutable, '../../..');
  const artifacts = desktopArtifacts(app);
  if (manifest.nativeBinary !== artifacts.nativeBinary || manifest.appAsar !== artifacts.appAsar
      || manifest.appExecutable !== path.join(app, 'Contents/MacOS/ChatGPT')) {
    throw new Error('Desktop executable paths do not identify one application');
  }
  if (!['http://127.0.0.1:4202/v1', 'http://localhost:4202/v1'].includes(manifest.provider?.base_url)
      || manifest.provider?.wire_api !== 'responses' || manifest.provider?.requires_openai_auth !== false) {
    throw new Error('Invalid isolated Jev provider');
  }
  return { ...manifest, app };
}
