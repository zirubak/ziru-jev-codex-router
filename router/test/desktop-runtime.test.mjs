import assert from 'node:assert/strict';
import test from 'node:test';
import { chmod, mkdir, mkdtemp, rm, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { desktopArtifacts } from '../src/desktop-compatibility.mjs';
import { isStdioAppServer, readDesktopManifest } from '../src/desktop-runtime.mjs';

test('only stdio app-server invocations are eligible for the bridge', () => {
  for (const args of [
    ['app-server'],
    ['-c', 'features.fixture=true', 'app-server'],
    ['--profile', 'fixture', '--enable', 'fixture', 'app-server', '--analytics-default-enabled'],
    ['app-server', '--config', 'features.fixture=true', '--listen', 'stdio://'],
    ['app-server', '--listen=stdio://'],
  ]) assert.equal(isStdioAppServer(args), true, JSON.stringify(args));
});

test('CLI execution, help, generation, daemon and proxy retain native transport', () => {
  for (const args of [
    [], ['--version'], ['exec', 'app-server'], ['exec', '--', 'app-server'],
    ['app-server', '--help'], ['app-server', '-h'], ['help', 'app-server'],
    ['app-server', 'generate-ts'], ['app-server', 'generate-json-schema'],
    ['app-server', 'daemon', 'start'], ['app-server', 'proxy'],
    ['app-server', '--listen', 'ws://127.0.0.1:1234'], ['app-server', '--listen'],
    ['-c'], ['--config', 'app-server'], ['app-server', '--unknown-option'],
  ]) assert.equal(isStdioAppServer(args), false, JSON.stringify(args));
});

async function fixture(t) {
  const directory = await mkdtemp(join(tmpdir(), 'jev-runtime-test-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const home = join(directory, 'codex-home');
  await mkdir(home, { mode: 0o700 });
  const app = join(directory, 'Desktop.app');
  const manifest = {
    version: 1, codexHome: home, ...desktopArtifacts(app),
    appExecutable: join(app, 'Contents/MacOS/ChatGPT'),
    bridgeBinary: join(directory, 'router/bin/jev-desktop-codex'),
    routeStateDirectory: join(home, 'private-routes'),
    provider: { name: 'Jev fixture', base_url: 'http://127.0.0.1:4202/v1', wire_api: 'responses', requires_openai_auth: false },
  };
  const file = join(directory, 'manifest.json');
  const save = async (value = manifest) => writeFile(file, JSON.stringify(value), { mode: 0o600 });
  await save();
  return { directory, home, app, manifest, file, save };
}

test('manifest permits its canonical opted-in home and rejects a different home', async (t) => {
  const { directory, home, app, manifest, file } = await fixture(t);
  assert.deepEqual(readDesktopManifest(file, home), { ...manifest, app });
  const alias = join(directory, 'home-alias');
  await symlink(home, alias);
  assert.equal(readDesktopManifest(file, alias).codexHome, home);
  const other = join(directory, 'unregistered-home');
  await mkdir(other, { mode: 0o700 });
  assert.throws(() => readDesktopManifest(file, other), /has not enabled/);
});

test('manifest rejects executable paths that do not identify one application', async (t) => {
  const { file, home, manifest, save } = await fixture(t);
  for (const changed of [
    { nativeBinary: '/another/Contents/Resources/codex' },
    { appAsar: '/another/Contents/Resources/app.asar' },
    { appExecutable: manifest.appExecutable.replace('/ChatGPT', '/Other') },
    { bridgeBinary: 'relative-bridge' },
    { routeStateDirectory: 'relative-state' },
  ]) {
    await save({ ...manifest, ...changed });
    assert.throws(() => readDesktopManifest(file, home), /manifest paths|one application/);
  }
});

test('manifest cannot select a remote endpoint or the built-in auth path', async (t) => {
  const { file, home, manifest, save } = await fixture(t);
  for (const changed of [
    { base_url: 'https://example.invalid/v1' },
    { base_url: 'http://127.0.0.1:9999/v1' },
    { requires_openai_auth: true },
    { wire_api: 'chat' },
  ]) {
    await save({ ...manifest, provider: { ...manifest.provider, ...changed } });
    assert.throws(() => readDesktopManifest(file, home), /Invalid isolated Jev provider/);
  }
});

test('manifest refuses broad permissions, excessive size, and symbolic links', async (t) => {
  const { directory, file, home, save } = await fixture(t);
  await chmod(file, 0o644);
  assert.throws(() => readDesktopManifest(file, home), /Unsafe Desktop manifest/);
  await chmod(file, 0o600);
  await writeFile(file, ' '.repeat(32769));
  assert.throws(() => readDesktopManifest(file, home), /Unsafe Desktop manifest/);
  await save();
  const alias = join(directory, 'manifest-alias.json');
  await symlink(file, alias);
  assert.throws(() => readDesktopManifest(alias, home), { code: 'ELOOP' });
  assert.throws(() => readDesktopManifest('relative.json', home), /private Desktop manifest/);
});
