import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { request } from 'node:http';
import test from 'node:test';
import { access, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { DesktopContractMismatch } from '../src/desktop-compatibility.mjs';
import { probeDesktopContract, startQualificationResponderForTests } from '../src/desktop-contract-probe.mjs';
import { planQualifiedDesktopLaunch } from '../src/desktop-launch.mjs';

const carrier = {
  slug: 'gpt-6.1-sol', max_context_window: 872000,
  supported_reasoning_levels: ['low', 'medium', 'high', 'xhigh', 'max'].map((effort) => ({ effort })),
};

async function fakeNative(t, behavior, models = [carrier], metadataBehavior = '', versionBehavior = '') {
  const directory = await mkdtemp(join(tmpdir(), 'jev-contract-test-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const binary = join(directory, 'native');
  const report = join(directory, 'environment.jsonl');
  await writeFile(binary, `#!${process.execPath}\n
import { appendFileSync } from 'node:fs';
appendFileSync(${JSON.stringify(report)}, JSON.stringify({ argv: process.argv.slice(2), env: process.env, cwd: process.cwd(), pid: process.pid }) + '\\n');
if (process.argv[2] === '--version') { console.log('codex-cli 1.0.0-probe'); ${versionBehavior} }
else if (process.argv[2] === 'debug') { console.log(${JSON.stringify(JSON.stringify({ models }))}); ${metadataBehavior} }
else { ${behavior} }
`, { mode: 0o700 });
  return { binary, report };
}

async function waitForProcessGroupRetirement(processGroup) {
  const deadline = Date.now() + 3000;
  do {
    const processes = execFileSync('/bin/ps', ['-axo', 'pgid=,stat='], { encoding: 'utf8' });
    const active = processes.split('\n').some((line) => {
      const [group, state] = line.trim().split(/\s+/);
      return group === String(processGroup) && state && !/^[ZX]/.test(state);
    });
    if (!active) return;
    await new Promise((resolve) => setTimeout(resolve, 25));
  } while (Date.now() < deadline);
  assert.fail(`process group ${processGroup} still has a live member`);
}

async function waitForProcessRetirement(pid) {
  const deadline = Date.now() + 3000;
  do {
    let state = '';
    try { state = execFileSync('/bin/ps', ['-o', 'stat=', '-p', String(pid)], { encoding: 'utf8' }).trim(); }
    catch (error) { if (error.status !== 1) throw error; }
    if (!state || /^[ZX]/.test(state)) return;
    await new Promise((resolve) => setTimeout(resolve, 25));
  } while (Date.now() < deadline);
  assert.fail(`process ${pid} is still running`);
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

test('probe marks malformed bundled catalog entries as incompatibility', async (t) => {
  const native = await fakeNative(t, 'process.exit(99);', [null]);
  await assert.rejects(probeDesktopContract(native.binary), (error) => {
    assert.equal(error.code, 'DESKTOP_INCOMPATIBLE');
    assert.match(error.message, /bundled native catalog protocol changed/);
    return true;
  });
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

test('probe hard-stops on an unsolicited HTTP request before any qualification turn', async (t) => {
  const native = await fakeNative(t, `
const { readFile } = await import('node:fs/promises');
const config = await readFile(process.env.CODEX_HOME + '/config.toml', 'utf8');
const baseUrl = config.match(/base_url = "([^"]+)"/)[1];
await fetch(baseUrl + '/unexpected', { method: 'POST', body: 'not-json' });
process.stdin.resume();
`);
  await assert.rejects(probeDesktopContract(native.binary), (error) => {
    assert.notEqual(error.code, 'DESKTOP_INCOMPATIBLE');
    assert.match(error.message, /outside an expected qualification turn/);
    return true;
  });
  const records = (await readFile(native.report, 'utf8')).trim().split('\n').map((line) => JSON.parse(line));
  await assert.rejects(access(records[0].env.HOME), { code: 'ENOENT' });
});

test('probe preserves app-server spawn errors and removes its private home', async (t) => {
  const native = await fakeNative(t, '');
  await assert.rejects(probeDesktopContract(native.binary, {
    nativeCommand: (binary, args) => args[0] === 'app-server'
      ? { file: `${binary}.missing`, args: [] }
      : { file: binary, args },
  }), (error) => {
    assert.equal(error.code, 'ENOENT');
    assert.notEqual(error.code, 'DESKTOP_INCOMPATIBLE');
    return true;
  });
  const records = (await readFile(native.report, 'utf8')).trim().split('\n').map((line) => JSON.parse(line));
  assert.equal(records.length, 2, 'the injected app-server path must not execute');
  await assert.rejects(access(records[0].env.HOME), { code: 'ENOENT' });
});

test('probe creates private route state before spawning the native app-server', async (t) => {
  const native = await fakeNative(t, "process.stdin.once('data', () => { console.log('invalid protocol'); });");
  const routeStateError = new Error('private route state could not be initialized');
  await assert.rejects(probeDesktopContract(native.binary, {
    createPrivateRouteState: () => { throw routeStateError; },
  }), (error) => error === routeStateError);
  const records = (await readFile(native.report, 'utf8')).trim().split('\n').map((line) => JSON.parse(line));
  assert.equal(records.length, 2, 'route-state initialization failure must occur before app-server spawn');
  await assert.rejects(access(records[0].env.HOME), { code: 'ENOENT' });
});

test('probe distinguishes direct spawn errors from sandbox child failures and removes its private home', async (t) => {
  const sandboxRunner = `const { spawnSync } = await import('node:child_process');\n` +
    `const child = spawnSync(process.argv[1], process.argv.slice(2), { encoding: 'utf8' });\n` +
    `if (child.error) { process.stderr.write(child.error.code); process.exit(127); }\n` +
    `process.stdout.write(child.stdout); process.stderr.write(child.stderr); process.exit(child.status ?? 127);`;
  for (const path of ['direct-spawn', 'sandbox-child']) {
    await t.test(path, async (subtest) => {
      const native = await fakeNative(subtest, '', [carrier], '', 'await import("node:fs/promises").then(({ unlink }) => unlink(process.argv[1]));');
      const dependencies = path === 'direct-spawn'
        ? { nativeCommand: (binary, args) => ({ file: binary, args }) }
        : { nativeCommand: (binary, args) => ({ file: process.execPath, args: ['-e', sandboxRunner, binary, ...args] }) };
      await assert.rejects(probeDesktopContract(native.binary, dependencies), (error) => {
        assert.notEqual(error.code, 'DESKTOP_INCOMPATIBLE');
        if (path === 'direct-spawn') assert.equal(error.code, 'ENOENT');
        else {
          assert.equal(error.code, 127);
          assert.match(error.stderr, /ENOENT/);
        }
        return true;
      });
      const records = (await readFile(native.report, 'utf8')).trim().split('\n').map((line) => JSON.parse(line));
      await assert.rejects(access(records[0].env.HOME), { code: 'ENOENT' });
    });
  }
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
  await waitForProcessRetirement(descendant.pid);
  await assert.rejects(readFile(join(descendant.home, 'descendant/activity')), { code: 'ENOENT' });
});

test('probe propagates process-group cleanup failures and retains the private home until retirement', { skip: process.platform === 'win32' }, async (t) => {
  const native = await fakeNative(t, "process.stdin.once('data', () => { console.log('invalid protocol'); setInterval(() => {}, 1000); });");
  const originalKill = process.kill;
  const terminationError = Object.assign(new Error('native process group could not be terminated'), { code: 'EPERM' });
  process.kill = (pid, signal) => {
    if (pid < 0) throw terminationError;
    return originalKill(pid, signal);
  };
  let appServer;
  try {
    await assert.rejects(probeDesktopContract(native.binary), (error) => error === terminationError);
  } finally {
    process.kill = originalKill;
    try {
      const records = (await readFile(native.report, 'utf8')).trim().split('\n').map((line) => JSON.parse(line));
      appServer = records.at(-1);
      originalKill(-appServer.pid, 'SIGKILL');
      await waitForProcessGroupRetirement(appServer.pid);
    } catch (error) { if (error.code !== 'ESRCH' && error.code !== 'ENOENT') throw error; }
  }
  await access(join(appServer.env.HOME, 'config.toml'));
  await rm(appServer.env.HOME, { recursive: true, force: true });
});

test('probe times out and terminates an unresponsive native process', { timeout: 15000 }, async (t) => {
  const native = await fakeNative(t, "process.on('SIGTERM', () => {}); setInterval(() => {}, 1000); process.stdin.resume();");
  await assert.rejects(probeDesktopContract(native.binary), /native initialize request timed out/);
  const records = (await readFile(native.report, 'utf8')).trim().split('\n').map((line) => JSON.parse(line));
  assert.throws(() => process.kill(records.at(-1).pid, 0), { code: 'ESRCH' });
});

const launchManifest = {
  version: 1, nativeBinary: '/app/codex', appExecutable: '/app/ChatGPT',
  appAsar: '/app/app.asar', bridgeBinary: '/router/jev-desktop-codex',
};
const expectedTurn = () => ({ mode: 'auto', effort: 'high', markers: ['JEV_CONTRACT_INPUT_1'], collaborationMarker: null, received: false });
const turnBody = JSON.stringify({ model: 'gpt-6.1-sol', reasoning: { effort: 'high' },
  input: [{ type: 'message', role: 'user', content: [{ type: 'input_text', text: 'JEV_CONTRACT_INPUT_1' }] }],
  tools: [{ type: 'function', name: 'synthetic' }] });
const bridgedHeaders = { 'content-type': 'application/json', 'x-jev-selection-mode': 'auto',
  'x-jev-desktop-recovery': 'bridge-active', 'x-openai-internal-codex-responses-lite': 'true' };

async function responder(t, state = {}) {
  const directory = await mkdtemp(join(tmpdir(), 'jev-responder-test-'));
  const errors = [];
  const context = { directory, config: '', httpRequests: 0, expected: null, recovery: null,
    recoveryDeniedRequests: 0, recoveryCompactRequests: 0, ...state };
  context.fail = (error) => { errors.push(error); context.error ??= error; };
  await startQualificationResponderForTests(context);
  let seen = 0;
  const waiters = [];
  context.server.on('request', () => { seen += 1; for (const waiter of waiters.splice(0)) waiter(); });
  t.after(async () => {
    context.server.closeAllConnections();
    await new Promise((resolve) => context.server.close(resolve));
    await rm(directory, { recursive: true, force: true });
  });
  const url = new URL(context.provider.base_url);
  const open = (path, headers = bridgedHeaders) => {
    const pending = request({ host: url.hostname, port: url.port, path, method: 'POST', headers });
    const response = new Promise((resolve) => {
      pending.on('response', (res) => {
        const chunks = [];
        res.on('data', (chunk) => chunks.push(chunk));
        res.on('end', () => resolve({ status: res.statusCode, body: Buffer.concat(chunks).toString('utf8') }));
      });
      pending.on('error', (error) => resolve({ status: null, error: error.code }));
    });
    pending.flushHeaders();
    return { pending, response };
  };
  const received = async (count) => { while (seen < count) await new Promise((resolve) => waiters.push(resolve)); };
  return { context, errors, open, received };
}

async function assertHardStop(error, pattern) {
  assert.ok(error, 'qualification recorded no failure');
  assert.ok(!(error instanceof DesktopContractMismatch));
  assert.notEqual(error.code, 'DESKTOP_INCOMPATIBLE');
  assert.match(error.message, pattern);
  await assert.rejects(planQualifiedDesktopLaunch(launchManifest, '/private/manifest.json', {}, '/private/cache',
    async () => { throw error; }), (rejected) => rejected === error);
}

test('responder serves one ordinary supported request for an expected turn', async (t) => {
  const { context, errors, open } = await responder(t, { expected: expectedTurn() });
  const first = open('/v1/responses');
  first.pending.end(turnBody);
  const result = await first.response;
  assert.equal(result.status, 200);
  assert.match(result.body, /response\.completed/);
  assert.deepEqual(errors, []);
  assert.equal(context.httpRequests, 1);
  assert.equal(context.expected.received, true);
});

test('responder hard-stops overlapping requests that reserve one expected turn before their bodies arrive', async (t) => {
  const { context, errors, open, received } = await responder(t, { expected: expectedTurn() });
  const first = open('/v1/responses');
  const second = open('/v1/responses');
  await received(2);
  first.pending.end(turnBody);
  const firstResult = await first.response;
  second.pending.end(turnBody);
  const secondResult = await second.response;
  assert.notEqual(secondResult.status, 200);
  assert.ok(context.httpRequests <= 1, `served ${context.httpRequests} requests for one turn`);
  assert.ok([firstResult, secondResult].filter((result) => result.status === 200).length <= 1);
  await assertHardStop(errors[0], /more than one HTTP request|outside an expected qualification turn/);
});

test('responder hard-stops a request whose expected turn changed before its body arrived', async (t) => {
  const { context, errors, open, received } = await responder(t, { expected: expectedTurn() });
  const stale = open('/v1/responses');
  await received(1);
  context.expected = expectedTurn();
  stale.pending.end(turnBody);
  const result = await stale.response;
  assert.notEqual(result.status, 200);
  assert.equal(context.httpRequests, 0);
  await assertHardStop(errors[0], /outside an expected qualification turn/);
});

test('responder treats automatic compaction during an expected turn as a safety failure', async (t) => {
  const { context, errors, open } = await responder(t, { expected: expectedTurn() });
  const compact = open('/v1/responses/compact');
  compact.pending.end(turnBody);
  const result = await compact.response;
  assert.notEqual(result.status, 200);
  assert.equal(context.httpRequests, 0);
  await assertHardStop(errors[0], /automatic compaction/);
});

test('responder keeps the intentional recovery refusal for bare native compaction', async (t) => {
  const { context, errors, open } = await responder(t, { recovery: { threadId: 'thread', mode: 'auto', requests: 0 } });
  const compact = open('/v1/responses/compact', { ...bridgedHeaders, 'x-jev-desktop-recovery': 'required' });
  compact.pending.end(turnBody);
  const result = await compact.response;
  assert.equal(result.status, 400);
  assert.equal(JSON.parse(result.body).error.code, 'jev_desktop_recovery_required');
  assert.deepEqual(errors, []);
  assert.equal(context.recoveryDeniedRequests, 1);
  assert.equal(context.recoveryCompactRequests, 1);
  assert.equal(context.httpRequests, 0);
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
