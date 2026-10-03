import assert from 'node:assert/strict';
import test from 'node:test';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { probeDesktopContract } from '../src/desktop-contract-probe.mjs';

const carrier = {
  slug: 'gpt-6.1-sol', max_context_window: 872000,
  supported_reasoning_levels: ['low', 'medium', 'high', 'xhigh', 'max'].map((effort) => ({ effort })),
};

async function fakeNative(t, behavior, models = [carrier]) {
  const directory = await mkdtemp(join(tmpdir(), 'jev-contract-test-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const binary = join(directory, 'native');
  const report = join(directory, 'environment.jsonl');
  await writeFile(binary, `#!${process.execPath}\n
import { appendFileSync } from 'node:fs';
appendFileSync(${JSON.stringify(report)}, JSON.stringify({ argv: process.argv.slice(2), env: process.env, cwd: process.cwd(), pid: process.pid }) + '\\n');
if (process.argv[2] === '--version') console.log('codex-cli 1.0.0-probe');
else if (process.argv[2] === 'debug') console.log(${JSON.stringify(JSON.stringify({ models }))});
else { ${behavior} }
`, { mode: 0o700 });
  return { binary, report };
}

test('probe refuses malformed native protocol and never inherits caller credentials or configuration', async (t) => {
  const native = await fakeNative(t, "process.stdin.once('data', () => console.log('invalid protocol')); ");
  const previous = process.env.JEV_PROBE_PRIVATE_SENTINEL;
  process.env.JEV_PROBE_PRIVATE_SENTINEL = 'must-not-reach-native';
  t.after(() => {
    if (previous === undefined) delete process.env.JEV_PROBE_PRIVATE_SENTINEL;
    else process.env.JEV_PROBE_PRIVATE_SENTINEL = previous;
  });
  await assert.rejects(probeDesktopContract(native.binary), /Jev Desktop compatibility:.*protocol/);
  const records = (await readFile(native.report, 'utf8')).trim().split('\n').map((line) => JSON.parse(line));
  assert.equal(records.length, 3);
  for (const record of records) {
    assert.equal(record.env.JEV_PROBE_PRIVATE_SENTINEL, undefined);
    assert.notEqual(record.env.HOME, process.env.HOME);
    assert.notEqual(record.env.CODEX_HOME, process.env.CODEX_HOME);
    assert.equal(record.cwd, record.env.HOME);
    // macOS may add its own CoreFoundation encoding field while launching Node.
    assert.deepEqual(Object.keys(record.env).filter((key) => key !== '__CF_USER_TEXT_ENCODING').sort(), ['CODEX_HOME', 'HOME', 'LANG', 'LC_ALL', 'PATH', 'TMPDIR']);
    await assert.rejects(readFile(join(record.env.HOME, 'config.toml')), { code: 'ENOENT' });
    assert.throws(() => process.kill(record.pid, 0), { code: 'ESRCH' });
  }
});

test('probe refuses carrier metadata that cannot preserve every supported Manual effort', async (t) => {
  const native = await fakeNative(t, 'process.exit(99);', [{ ...carrier, supported_reasoning_levels: [{ effort: 'high' }] }]);
  await assert.rejects(probeDesktopContract(native.binary), /carrier metadata/);
  const records = (await readFile(native.report, 'utf8')).trim().split('\n');
  assert.equal(records.length, 2, 'an incompatible catalog must be refused before app-server starts');
});

test('probe refuses native tool callbacks without executing or granting them', async (t) => {
  const native = await fakeNative(t, `process.stdin.once('data', () => console.log(JSON.stringify({ id: 7, method: 'item/commandExecution/requestApproval', params: { command: 'do-not-run' } })));`);
  await assert.rejects(probeDesktopContract(native.binary), /unexpected native callback/);
});

test('probe reports native exit without exposing native output', async (t) => {
  const native = await fakeNative(t, "console.error('PRIVATE-NATIVE-ERROR'); process.exit(42);");
  await assert.rejects(probeDesktopContract(native.binary), (error) => {
    assert.match(error.message, /native process exited/);
    assert.doesNotMatch(error.message, /PRIVATE-NATIVE-ERROR/);
    return true;
  });
});

test('macOS native children cannot open a non-loopback network connection', { skip: process.platform !== 'darwin' }, async (t) => {
  const native = await fakeNative(t, `
const { connect } = await import('node:net');
const socket = connect({ host: '192.0.2.1', port: 9 });
socket.once('error', (error) => {
  appendFileSync(${JSON.stringify('PLACEHOLDER')}, error.code);
  console.log('invalid protocol');
});
`);
  const script = (await readFile(native.binary, 'utf8')).replace(JSON.stringify('PLACEHOLDER'), JSON.stringify(`${native.report}.network`));
  await writeFile(native.binary, script, { mode: 0o700 });
  await assert.rejects(probeDesktopContract(native.binary), /protocol/);
  assert.equal(await readFile(`${native.report}.network`, 'utf8'), 'EPERM');
});

test('probe terminates a surviving native descendant before removing its private home', { skip: process.platform === 'win32' }, async (t) => {
  const native = await fakeNative(t, `
const { spawn } = await import('node:child_process');
const descendantCode = \
  "const fs = require('node:fs'); process.on('SIGTERM', () => {}); " +
  "fs.writeFileSync('DESCENDANT_REPORT', JSON.stringify({ pid: process.pid, home: process.env.HOME })); " +
  "setInterval(() => { fs.mkdirSync(process.env.HOME + '/descendant', {recursive:true}); fs.writeFileSync(process.env.HOME + '/descendant/activity', 'active'); }, 1); " +
  "process.send('ready');";
const descendant = spawn(process.execPath, ['-e', descendantCode], { stdio: ['ignore', 'ignore', 'ignore', 'ipc'] });
descendant.once('message', () => { console.log('invalid protocol'); process.exit(0); });
`);
  const report = `${native.report}.descendant`;
  await writeFile(native.binary, (await readFile(native.binary, 'utf8')).replace('DESCENDANT_REPORT', report), { mode: 0o700 });
  await assert.rejects(probeDesktopContract(native.binary), /protocol|native process exited/);
  const descendant = JSON.parse(await readFile(report, 'utf8'));
  assert.throws(() => process.kill(descendant.pid, 0), { code: 'ESRCH' });
  await assert.rejects(readFile(join(descendant.home, 'descendant/activity')), { code: 'ENOENT' });
});

test('probe times out and terminates an unresponsive native process', { timeout: 15000 }, async (t) => {
  const native = await fakeNative(t, "process.on('SIGTERM', () => {}); setInterval(() => {}, 1000); process.stdin.resume();");
  await assert.rejects(probeDesktopContract(native.binary), /native initialize request timed out/);
  const records = (await readFile(native.report, 'utf8')).trim().split('\n').map((line) => JSON.parse(line));
  assert.throws(() => process.kill(records.at(-1).pid, 0), { code: 'ESRCH' });
});

test('real native qualification covers synthetic routing, settings, context pressure, and persisted resume', {
  skip: !process.env.JEV_DESKTOP_NATIVE_BINARY, timeout: 60000,
}, async () => {
  const evidence = await probeDesktopContract(process.env.JEV_DESKTOP_NATIVE_BINARY);
  assert.match(evidence.nativeVersion, /^codex-cli /);
  assert.ok(evidence.checks.includes('manual-efforts'));
  assert.ok(evidence.checks.includes('nested-settings'));
  assert.ok(evidence.checks.includes('restart-resume'));
  assert.ok(evidence.checks.includes('bare-native-recovery-resume'));
  assert.ok(evidence.checks.includes('bare-native-recovery-http-guard'));
  assert.ok(evidence.checks.includes('recovery-registry-native-deep-merge'));
  assert.ok(evidence.checks.includes('official-provider-restored'));
  assert.ok(evidence.minimumContextWindow >= 740000);
  assert.ok(evidence.httpRequests >= 8);
  assert.equal(evidence.compactions, 0);
  assert.ok(evidence.recoveryDeniedRequests >= 2);
  assert.equal(evidence.recoveryModelOutputs, 0);
});
