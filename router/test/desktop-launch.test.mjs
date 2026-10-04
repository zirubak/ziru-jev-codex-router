import assert from 'node:assert/strict';
import test from 'node:test';
import { DesktopContractMismatch } from '../src/desktop-compatibility.mjs';
import { launchDesktop, planDesktopLaunch, planQualifiedDesktopLaunch } from '../src/desktop-launch.mjs';

const manifest = {
  version: 1, nativeBinary: '/app/codex', appExecutable: '/app/ChatGPT',
  appAsar: '/app/app.asar', bridgeBinary: '/router/jev-desktop-codex',
  expectedAppSha256: 'a'.repeat(64), expectedNativeSha256: 'b'.repeat(64),
};
const observed = { appSha256: 'a'.repeat(64), nativeSha256: 'b'.repeat(64), contractVerified: true };
const originalEnv = { HOME: '/home', CODEX_HOME: '/home/.codex', PATH: '/bin',
  CODEX_CLI_PATH: '/old', CODEX_APP_SERVER_USE_LOCAL_DAEMON: '1' };

test('compatible app selects launch-scoped bridge without changing normal home', () => {
  const result = planDesktopLaunch(manifest, '/private/manifest.json', originalEnv, observed);
  assert.equal(result.env.CODEX_CLI_PATH, manifest.bridgeBinary);
  assert.equal(result.env.JEV_DESKTOP_CONFIG, '/private/manifest.json');
  assert.equal(result.env.HOME, originalEnv.HOME);
  assert.equal(result.env.CODEX_HOME, originalEnv.CODEX_HOME);
  assert.equal(result.env.CODEX_APP_SERVER_USE_LOCAL_DAEMON, undefined);
  assert.equal(result.mode, 'jev');
  assert.equal(originalEnv.CODEX_CLI_PATH, '/old');
  assert.deepEqual(result.args, []);
});

test('missing current qualification disables bridge and preserves recovery launch', () => {
  for (const changed of [{ appSha256: 'c'.repeat(64) }, { nativeSha256: 'c'.repeat(64) }]) {
    const result = planDesktopLaunch(manifest, '/private/manifest.json', originalEnv, { ...observed, ...changed, contractVerified: false });
    assert.equal(result.mode, 'native');
    assert.equal(result.env.CODEX_CLI_PATH, undefined);
    assert.equal(result.env.JEV_DESKTOP_CONFIG, undefined);
    assert.equal(result.executable, manifest.appExecutable);
    assert.match(result.warning, /remain readable/);
  }
});

test('invalid manifest does not launch any command', () => {
  assert.throws(() => planDesktopLaunch({ ...manifest, version: 2 }, '/p', {}, observed), /manifest/);
  assert.throws(() => planDesktopLaunch({ ...manifest, appExecutable: 'relative' }, '/p', {}, observed), /absolute/);
});

test('native contract incompatibility selects the native recovery launch', async () => {
  const result = await planQualifiedDesktopLaunch(manifest, '/private/manifest.json', originalEnv, '/private/cache',
    async () => { throw new DesktopContractMismatch('native contract changed'); });
  assert.equal(result.plan.mode, 'native');
  assert.equal(result.plan.env.CODEX_CLI_PATH, undefined);
  assert.equal(result.plan.env.JEV_DESKTOP_CONFIG, undefined);
  assert.match(result.plan.warning, /remain readable/);
  assert.match(result.compatibilityError.message, /native contract changed/);
});

test('qualification safety errors and invalid manifests remain hard stops', async () => {
  const unsafeQualification = async () => { throw new Error('Unsafe Desktop qualification receipt'); };
  await assert.rejects(planQualifiedDesktopLaunch(manifest, '/private/manifest.json', originalEnv, '/private/cache', unsafeQualification),
    /Unsafe Desktop qualification receipt/);
  let qualified = false;
  await assert.rejects(planQualifiedDesktopLaunch({ ...manifest, appExecutable: 'relative' }, '/p', {}, '/cache',
    async () => { qualified = true; }), /absolute/);
  assert.equal(qualified, false);
});

test('incompatible contract skips session activation and launches native with overrides removed', async () => {
  let activated = false;
  let launched;
  const env = { ...originalEnv, JEV_DESKTOP_CONFIG: '/old/config', CODEX_APP_SERVER_USE_LOCAL_DAEMON: '1' };
  await launchDesktop({
    platform: 'darwin',
    manifestPath: '/private/manifest.json',
    environment: env,
    readManifest: () => ({ ...manifest, app: '/app', session: { python: '/python', script: '/session.py' } }),
    listProcesses: () => '',
    qualify: async () => { throw new DesktopContractMismatch('native contract changed'); },
    activateSession: () => { activated = true; },
    spawnProcess: (...args) => { launched = args; return { once() {}, unref() {} }; },
    writeStderr() {},
  });
  assert.equal(activated, false);
  assert.equal(launched[0], manifest.appExecutable);
  assert.deepEqual(launched[1], []);
  assert.equal(launched[2].env.CODEX_CLI_PATH, undefined);
  assert.equal(launched[2].env.JEV_DESKTOP_CONFIG, undefined);
  assert.equal(launched[2].env.CODEX_APP_SERVER_USE_LOCAL_DAEMON, undefined);
});

test('orchestration does not turn unsafe manifests or operational qualification failures into recovery', async () => {
  for (const stage of ['manifest', 'qualification']) {
    let spawned = false;
    let activated = false;
    const failure = new Error(`${stage} failed`);
    await assert.rejects(launchDesktop({
      platform: 'darwin',
      manifestPath: '/private/manifest.json',
      environment: originalEnv,
      readManifest: () => {
        if (stage === 'manifest') throw failure;
        return { ...manifest, app: '/app', session: { python: '/python', script: '/session.py' } };
      },
      listProcesses: () => '',
      qualify: async () => { if (stage === 'qualification') throw failure; },
      activateSession: () => { activated = true; },
      spawnProcess: () => { spawned = true; return { once() {}, unref() {} }; },
      writeStderr() {},
    }), (error) => error === failure);
    assert.equal(spawned, false);
    assert.equal(activated, false);
  }
});

test('stable qualification activates the session and selects the bridge', async () => {
  let activated = false;
  let launched;
  await launchDesktop({
    platform: 'darwin',
    manifestPath: '/private/manifest.json',
    environment: originalEnv,
    readManifest: () => ({ ...manifest, app: '/app', session: { python: '/python', script: '/session.py' } }),
    listProcesses: () => '',
    qualify: async () => {},
    activateSession: () => { activated = true; },
    spawnProcess: (...args) => { launched = args; return { once() {}, unref() {} }; },
    writeStderr() {},
  });
  assert.equal(activated, true);
  assert.equal(launched[0], manifest.appExecutable);
  assert.equal(launched[2].env.CODEX_CLI_PATH, manifest.bridgeBinary);
  assert.equal(launched[2].env.JEV_DESKTOP_CONFIG, '/private/manifest.json');
});

test('a signed update that passes the current native contract keeps the bridge enabled', () => {
  const result = planDesktopLaunch(manifest, '/private/manifest.json', originalEnv, {
    appSha256: 'c'.repeat(64), nativeSha256: 'd'.repeat(64), contractVerified: true,
  });
  assert.equal(result.mode, 'jev');
  assert.equal(result.env.CODEX_CLI_PATH, manifest.bridgeBinary);
  assert.equal(result.warning, null);
});
