import assert from 'node:assert/strict';
import test from 'node:test';
import { chmod, mkdir, mkdtemp, readFile, readdir, rm, stat, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { desktopArtifacts, qualifyDesktop } from '../src/desktop-compatibility.mjs';

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
