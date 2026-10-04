import assert from 'node:assert/strict';
import test from 'node:test';
import { chmod, mkdir, mkdtemp, readFile, readdir, rm, stat, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { DesktopContractMismatch, desktopArtifacts, qualifyDesktop } from '../src/desktop-compatibility.mjs';
import { planQualifiedDesktopLaunch } from '../src/desktop-launch.mjs';

function archive(script = 'process.env.CODEX_CLI_PATH', entryOverrides = {}) {
  const payload = Buffer.from(script);
  const entry = { size: payload.length, offset: '0', ...entryOverrides };
  const tree = { files: { '.vite': { files: { build: { files: { 'startup.js': entry } } } } } };
  const header = Buffer.from(JSON.stringify(tree));
  const aligned = Math.ceil(header.length / 4) * 4;
  const prefix = Buffer.alloc(16);
  prefix.writeUInt32LE(4, 0);
  prefix.writeUInt32LE(8 + aligned, 4);
  prefix.writeUInt32LE(4 + aligned, 8);
  prefix.writeUInt32LE(header.length, 12);
  return Buffer.concat([prefix, header, Buffer.alloc(aligned - header.length), payload]);
}

async function fixture(t) {
  const directory = await mkdtemp(join(tmpdir(), 'jev-qualification-test-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const app = join(directory, 'Desktop.app');
  const files = desktopArtifacts(app);
  await mkdir(dirname(files.nativeBinary), { recursive: true });
  await writeFile(files.appAsar, archive());
  await writeFile(files.nativeBinary, 'synthetic signed native build one');
  const options = { app, cacheDirectory: join(directory, 'receipts') };
  const calls = [];
  const dependencies = {
    verifySignature: async () => { calls.push('signature'); },
    contractDigest: async () => 'a'.repeat(64),
    probe: async (binary) => {
      assert.equal(binary, files.nativeBinary);
      calls.push('probe');
      return { nativeVersion: 'codex-cli 9.9.9-new-build', checks: ['synthetic-http-contract'] };
    },
  };
  return { directory, files, options, dependencies, calls };
}

test('signed compatible builds qualify without a version allowlist and cache by artifacts and adapter', async (t) => {
  const context = await fixture(t);
  const { options, dependencies, files, calls } = context;
  const first = await qualifyDesktop(options, dependencies);
  assert.equal(first.nativeVersion, 'codex-cli 9.9.9-new-build');
  assert.equal(first.qualified, true);
  assert.deepEqual(await qualifyDesktop(options, dependencies), first);
  assert.deepEqual(calls, ['signature', 'probe', 'signature']);

  await writeFile(files.appAsar, archive('process.env.CODEX_CLI_PATH; /* new app */'));
  const changedApp = await qualifyDesktop(options, dependencies);
  assert.notEqual(changedApp.expectedAppSha256, first.expectedAppSha256);
  await writeFile(files.nativeBinary, 'synthetic signed native build two');
  const changedNative = await qualifyDesktop(options, dependencies);
  assert.notEqual(changedNative.expectedNativeSha256, first.expectedNativeSha256);
  dependencies.contractDigest = async () => 'b'.repeat(64);
  const changedAdapter = await qualifyDesktop(options, dependencies);
  assert.equal(changedAdapter.contractDigest, 'b'.repeat(64));
  assert.equal(calls.filter((call) => call === 'probe').length, 4);
  const receipts = await readdir(options.cacheDirectory);
  assert.equal(receipts.length, 4);
  for (const name of receipts) assert.equal((await stat(join(options.cacheDirectory, name))).mode & 0o777, 0o600);
});

test('unsigned applications are rejected before probing or creating a receipt cache', async (t) => {
  const { options, dependencies, calls } = await fixture(t);
  dependencies.verifySignature = async () => { calls.push('signature'); throw new Error('Invalid OpenAI signature'); };
  await assert.rejects(qualifyDesktop(options, dependencies), /Invalid OpenAI signature/);
  assert.deepEqual(calls, ['signature']);
  await assert.rejects(stat(options.cacheDirectory), { code: 'ENOENT' });
});

test('an artifact replacement during signature verification is rejected before qualification', async (t) => {
  const { options, dependencies, files, calls } = await fixture(t);
  dependencies.verifySignature = async () => {
    calls.push('signature');
    await writeFile(files.appAsar, 'replacement after signature check');
  };
  await assert.rejects(qualifyDesktop(options, dependencies), /changed during signature verification/);
  assert.deepEqual(calls, ['signature']);
  await assert.rejects(stat(options.cacheDirectory), { code: 'ENOENT' });
});

test('failed qualification never publishes a success receipt', async (t) => {
  for (const result of ['rejected', 'missing-version']) {
    await t.test(result, async (subtest) => {
      const { options, dependencies } = await fixture(subtest);
      dependencies.probe = async () => {
        if (result === 'rejected') throw new Error('Native contract failed');
        return { checks: [] };
      };
      await assert.rejects(qualifyDesktop(options, dependencies), /Native contract/);
      assert.deepEqual(await readdir(options.cacheDirectory), []);
    });
  }
});

test('failed qualification remains a hard stop when artifacts or adapter change', async (t) => {
  for (const failure of ['hook', 'probe', 'missing-version']) {
    for (const change of ['app', 'native', 'adapter']) {
      await t.test(`${failure} failure with ${change} change`, async (subtest) => {
        const { options, dependencies, files } = await fixture(subtest);
        let codeDigest = 'a'.repeat(64);
        dependencies.contractDigest = async () => codeDigest;
        const mutate = async () => {
          if (change === 'app') await writeFile(files.appAsar, 'changed app artifact');
          else if (change === 'native') await writeFile(files.nativeBinary, 'changed native artifact');
          else codeDigest = 'c'.repeat(64);
        };
        if (failure === 'hook') {
          dependencies.verifyLaunchHook = async () => {
            await mutate();
            throw new DesktopContractMismatch('Native launch hook changed');
          };
        } else {
          dependencies.probe = async () => {
            await mutate();
            if (failure === 'missing-version') return { checks: [] };
            throw new DesktopContractMismatch('Native contract changed');
          };
        }
        const manifest = {
          version: 1, app: options.app, nativeBinary: files.nativeBinary,
          appExecutable: join(options.app, 'Contents/MacOS/ChatGPT'), appAsar: files.appAsar,
          bridgeBinary: '/router/bin/jev-desktop-codex',
        };
        await assert.rejects(planQualifiedDesktopLaunch(manifest, '/private/manifest.json', {},
          options.cacheDirectory, () => qualifyDesktop(options, dependencies)), /changed during qualification/);
        assert.deepEqual(await readdir(options.cacheDirectory), []);
      });
    }
  }
});

test('unchanged incompatible signed builds select native recovery for each contract failure', async (t) => {
  for (const failure of ['hook', 'probe', 'missing-version']) {
    await t.test(failure, async (subtest) => {
      const { options, dependencies, files } = await fixture(subtest);
      if (failure === 'hook') dependencies.verifyLaunchHook = async () => { throw new DesktopContractMismatch('Unsupported launch hook'); };
      else dependencies.probe = async () => failure === 'probe'
        ? Promise.reject(new DesktopContractMismatch('Unsupported native contract'))
        : { checks: [] };
      const manifest = {
        version: 1, app: options.app, nativeBinary: files.nativeBinary,
        appExecutable: join(options.app, 'Contents/MacOS/ChatGPT'), appAsar: files.appAsar,
        bridgeBinary: '/router/bin/jev-desktop-codex',
      };
      const result = await planQualifiedDesktopLaunch(manifest, '/private/manifest.json', {},
        options.cacheDirectory, () => qualifyDesktop(options, dependencies));
      assert.equal(result.plan.mode, 'native');
      assert.equal(result.compatibilityError.code, 'DESKTOP_INCOMPATIBLE');
      assert.deepEqual(await readdir(options.cacheDirectory), []);
    });
  }
});

test('operational and cleanup failures propagate without enabling native recovery', async (t) => {
  for (const stage of ['hook', 'probe']) {
    await t.test(stage, async (subtest) => {
      const { options, dependencies, files } = await fixture(subtest);
      const failure = Object.assign(new Error(`${stage} cleanup failed`), { code: 'EIO' });
      if (stage === 'hook') dependencies.verifyLaunchHook = async () => { throw failure; };
      else dependencies.probe = async () => { throw failure; };
      const manifest = {
        version: 1, app: options.app, nativeBinary: files.nativeBinary,
        appExecutable: join(options.app, 'Contents/MacOS/ChatGPT'), appAsar: files.appAsar,
        bridgeBinary: '/router/bin/jev-desktop-codex',
      };
      await assert.rejects(planQualifiedDesktopLaunch(manifest, '/private/manifest.json', {},
        options.cacheDirectory, () => qualifyDesktop(options, dependencies)), (error) => error === failure);
      assert.deepEqual(await readdir(options.cacheDirectory), []);
    });
  }
});

test('artifact or adapter replacement during a probe cannot publish a receipt', async (t) => {
  for (const change of ['app', 'native', 'adapter']) {
    await t.test(change, async (subtest) => {
      const { options, dependencies, files } = await fixture(subtest);
      const probe = dependencies.probe;
      let codeDigest = 'a'.repeat(64);
      dependencies.contractDigest = async () => codeDigest;
      dependencies.probe = async (binary) => {
        const result = await probe(binary);
        if (change === 'adapter') codeDigest = 'c'.repeat(64);
        else await writeFile(change === 'app' ? files.appAsar : files.nativeBinary, 'replaced during qualification');
        return result;
      };
      await assert.rejects(qualifyDesktop(options, dependencies), /changed during qualification/);
      assert.deepEqual(await readdir(options.cacheDirectory), []);
    });
  }
});

test('launch hook qualification reads actual ASAR entries and refuses missing or unsafe entries', async (t) => {
  const cases = [
    ['missing-hook', archive('process.env.UNRELATED')],
    ['unpacked-entry', archive(undefined, { unpacked: true })],
    ['linked-entry', archive(undefined, { link: '../other.js' })],
    ['out-of-bounds-entry', archive(undefined, { offset: '999999' })],
    ['truncated-header', Buffer.from('bad')],
  ];
  for (const [name, contents] of cases) {
    await t.test(name, async (subtest) => {
      const { options, dependencies, files, calls } = await fixture(subtest);
      await writeFile(files.appAsar, contents);
      await assert.rejects(qualifyDesktop(options, dependencies), /Desktop/);
      assert.deepEqual(calls, ['signature']);
      assert.deepEqual(await readdir(options.cacheDirectory), []);
    });
  }
});

test('qualification refuses shared or linked cache directories', async (t) => {
  for (const kind of ['shared', 'linked']) {
    await t.test(kind, async (subtest) => {
      const { options, dependencies, directory, calls } = await fixture(subtest);
      if (kind === 'shared') {
        await mkdir(options.cacheDirectory, { mode: 0o755 });
        await chmod(options.cacheDirectory, 0o755);
      } else {
        const target = join(directory, 'linked-target');
        await mkdir(target, { mode: 0o700 });
        await symlink(target, options.cacheDirectory);
      }
      await assert.rejects(qualifyDesktop(options, dependencies), /private and owner-only/);
      assert.deepEqual(calls, ['signature']);
    });
  }
});

test('cached receipts cannot bypass permission or symlink checks', async (t) => {
  const { options, dependencies, calls, directory } = await fixture(t);
  await qualifyDesktop(options, dependencies);
  const [name] = await readdir(options.cacheDirectory);
  const receipt = join(options.cacheDirectory, name);
  const original = await readFile(receipt);
  await chmod(receipt, 0o644);
  await assert.rejects(qualifyDesktop(options, dependencies), /Unsafe Desktop qualification receipt/);
  await rm(receipt);
  const target = join(directory, 'external-receipt.json');
  await writeFile(target, original, { mode: 0o600 });
  await symlink(target, receipt);
  await assert.rejects(qualifyDesktop(options, dependencies), { code: 'ELOOP' });
  assert.equal(calls.filter((call) => call === 'probe').length, 1);
  assert.deepEqual(await readFile(target), original);
});

test('corrupt private receipts are requalified instead of becoming permanent recovery failures', async (t) => {
  const { options, dependencies, calls } = await fixture(t);
  await qualifyDesktop(options, dependencies);
  const [name] = await readdir(options.cacheDirectory);
  for (const content of ['{truncated', 'null']) {
    await writeFile(join(options.cacheDirectory, name), content);
    const result = await qualifyDesktop(options, dependencies);
    assert.equal(result.qualified, true);
    assert.equal(JSON.parse(await readFile(join(options.cacheDirectory, name))).qualified, true);
  }
  assert.equal(calls.filter((call) => call === 'probe').length, 3);
});
