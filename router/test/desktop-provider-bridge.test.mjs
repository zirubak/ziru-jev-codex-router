import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import test from 'node:test';
import { DesktopProviderBridge, JevBridgeError } from '../src/desktop-provider-bridge.mjs';

const provider = { name: 'Jev', base_url: 'http://127.0.0.1:4202/v1', wire_api: 'responses', requires_openai_auth: false };
function fixture() {
  const calls = [];
  const thread = { id: 'fixture', model: 'gpt-6.1-sol', modelProvider: 'openai', reasoningEffort: 'high', status: { type: 'idle' }, path: '/fixture/rollout.jsonl', ephemeral: false, turns: [] };
  let loaded = true;
  let rejectRebind = false;
  const native = async (method, params) => {
    calls.push({ method, params: structuredClone(params) });
    if (method === 'thread/read') return { thread: structuredClone(thread) };
    if (method === 'thread/unsubscribe') { loaded = false; return { status: 'unsubscribed' }; }
    if (method === 'thread/resume' || method === 'thread/start' || method === 'thread/fork') {
      if (rejectRebind && params.modelProvider === 'jev-router') throw new JevBridgeError(-32000, 'fixture rejection');
      if (!loaded || method !== 'thread/resume') {
        thread.model = params.model ?? thread.model;
        thread.modelProvider = params.modelProvider ?? thread.modelProvider;
        thread.reasoningEffort = params.config?.model_reasoning_effort ?? thread.reasoningEffort;
      }
      loaded = true;
      return { model: thread.model, modelProvider: thread.modelProvider, reasoningEffort: thread.reasoningEffort, cwd: '/fixture', approvalPolicy: 'never', sandbox: { type: 'dangerFullAccess' }, activePermissionProfile: { id: ':danger-full-access' }, thread: structuredClone(thread) };
    }
    if (method === 'thread/settings/update') {
      thread.model = params.model ?? thread.model;
      thread.reasoningEffort = params.effort ?? thread.reasoningEffort;
      return {};
    }
    if (method === 'turn/start') return { turn: { id: 'turn', status: 'inProgress' } };
    if (method === 'model/list') return { data: [{ id: 'native', model: 'gpt-6.1-sol', unknownNativeField: true }], nextCursor: null };
    if (method === 'config/batchWrite') {
      if (params.expectedVersion === 'stale') throw new JevBridgeError(-32000, 'version mismatch');
      return { status: 'ok', version: 'native-version', filePath: '/fixture/config.toml' };
    }
    return { untouched: params };
  };
  const bridge = new DesktopProviderBridge({ request: native, provider });
  return { bridge, calls, thread, reject() { rejectRebind = true; } };
}

test('native model list is preserved and two Jev entries have exact effort contracts', async () => {
  const { bridge } = fixture();
  const result = await bridge.handle('model/list', {});
  assert.deepEqual(result.data[0], { id: 'native', model: 'gpt-6.1-sol', unknownNativeField: true });
  assert.deepEqual(result.data.slice(1).map((m) => [m.model, m.supportedReasoningEfforts.map((v) => v.reasoningEffort)]), [
    ['jev/auto', ['low', 'medium', 'high', 'xhigh', 'max']], ['jev/manual', ['low', 'medium', 'high', 'xhigh', 'max']],
  ]);
});

test('official to Auto to Manual to official rebinds provider and preserves same thread', async () => {
  const { bridge, calls, thread } = fixture();
  await bridge.handle('thread/settings/update', { threadId: 'fixture', model: 'jev/auto', effort: 'high' });
  assert.equal(thread.modelProvider, 'jev-router');
  assert.equal(thread.reasoningEffort, 'high');
  const unsubscriptions = calls.filter((c) => c.method === 'thread/unsubscribe').length;
  await bridge.handle('thread/settings/update', { threadId: 'fixture', model: 'jev/manual', effort: 'max' });
  assert.equal(thread.reasoningEffort, 'max');
  assert.equal(calls.filter((c) => c.method === 'thread/unsubscribe').length, unsubscriptions);
  await bridge.handle('thread/settings/update', { threadId: 'fixture', model: 'gpt-6.1-sol', effort: 'high' });
  assert.equal(thread.modelProvider, 'openai');
  assert.equal(thread.model, 'gpt-6.1-sol');
  assert.equal(thread.id, 'fixture');
});

test('busy and non-persisted threads are rejected before unsubscribe', async () => {
  for (const change of [{ status: { type: 'active' } }, { path: null }]) {
    const { bridge, calls, thread } = fixture();
    Object.assign(thread, change);
    await assert.rejects(bridge.handle('thread/settings/update', { threadId: 'fixture', model: 'jev/manual', effort: 'high' }), /idle|persisted/i);
    assert.equal(calls.some((c) => c.method === 'thread/unsubscribe'), false);
  }
});

test('failed cross-provider resume restores original provider and reports failure', async () => {
  const { bridge, thread, reject, calls } = fixture();
  reject();
  await assert.rejects(bridge.handle('thread/settings/update', { threadId: 'fixture', model: 'jev/manual', effort: 'max' }), /switch|rebind/i);
  assert.equal(thread.modelProvider, 'openai');
  assert.equal(calls.at(-1).params.modelProvider, 'openai');
});

test('new Jev thread gets only thread-scoped provider config', async () => {
  const { bridge, calls } = fixture();
  const result = await bridge.handle('thread/start', { model: 'jev/manual', config: { user_setting: true } });
  assert.equal(result.modelProvider, 'jev-router');
  assert.deepEqual(calls[0].params.config, { user_setting: true, model_reasoning_effort: 'medium', model_providers: { 'jev-router': provider } });
});

test('Jev model default writes never reach native disk and keep expectedVersion validation', async () => {
  const { bridge, calls } = fixture();
  const params = { expectedVersion: 'v1', edits: [
    { keyPath: 'model', value: 'jev/auto', mergeStrategy: 'replace' },
    { keyPath: 'model_reasoning_effort', value: 'auto', mergeStrategy: 'replace' },
    { keyPath: 'theme', value: 'light', mergeStrategy: 'replace' },
  ] };
  const result = await bridge.handle('config/batchWrite', params);
  assert.equal(result.status, 'okOverridden');
  assert.deepEqual(calls[0].params, { expectedVersion: 'v1', edits: [params.edits[2]] });
  await assert.rejects(bridge.handle('config/batchWrite', { ...params, expectedVersion: 'stale' }), /version mismatch/);
});

test('collaboration-mode model overrides route before turn and preserve manual effort', async () => {
  const { bridge, calls, thread } = fixture();
  await bridge.handle('turn/start', { threadId: 'fixture', input: [{ type: 'text', text: 'private fixture' }], collaborationMode: { mode: 'plan', settings: { model: 'jev/manual', reasoning_effort: 'xhigh' } } });
  assert.equal(thread.modelProvider, 'jev-router');
  assert.equal(calls.at(-1).method, 'turn/start');
  assert.equal(calls.at(-1).params.collaborationMode.settings.reasoning_effort, 'xhigh');
});

test('unknown methods and official compact requests pass through unchanged', async () => {
  const { bridge, calls } = fixture();
  for (const method of ['account/read', 'thread/compact/start', 'future/method']) {
    const params = { opaque: ['data'], threadId: 'fixture' };
    assert.deepEqual(await bridge.handle(method, params), { untouched: params });
    assert.deepEqual(calls.at(-1), { method, params });
  }
});

test('a remaining subscriber cannot produce a false successful provider switch', async () => {
  const { bridge, calls, thread } = fixture();
  const native = bridge.request;
  bridge.request = (method, params) => method === 'thread/unsubscribe'
    ? Promise.resolve({ status: 'unsubscribed' }) : native(method, params);
  await assert.rejects(bridge.handle('thread/settings/update', { threadId: 'fixture', model: 'jev/auto', effort: 'high' }), /rebind failed/);
  assert.equal(thread.modelProvider, 'openai');
  assert.equal(calls.some((c) => c.method === 'thread/settings/update'), false);
});

test('historical resume without threadId preserves native history semantics', async () => {
  const { bridge } = fixture();
  const native = bridge.request;
  bridge.request = (method, params) => {
    assert.notEqual(method, 'thread/read');
    return native(method, params);
  };
  const result = await bridge.handle('thread/resume', { history: [], model: 'gpt-6.1-sol' });
  assert.equal(result.modelProvider, 'openai');
});

test('manual effort omitted when changing from Auto becomes medium, never an Auto sentinel', async () => {
  const { bridge, thread } = fixture();
  await bridge.handle('thread/start', { model: 'jev/auto' });
  await bridge.handle('thread/settings/update', { threadId: 'fixture', model: 'jev/manual' });
  assert.equal(thread.reasoningEffort, 'medium');
});

import { PassThrough } from 'node:stream';
import { EventEmitter } from 'node:events';
import { createInterface } from 'node:readline';
import { spawn } from 'node:child_process';
import { mkdtemp, writeFile, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { connectDesktopBridge } from '../src/desktop-provider-bridge.mjs';

function rpcClient(input, output) {
  let counter = 0;
  const pending = new Map();
  const callbacks = [];
  const reader = createInterface({ input: output });
  reader.on('line', (line) => {
    const message = JSON.parse(line);
    if (message.method && message.id != null) {
      callbacks.push(message);
      input.write(`${JSON.stringify({ id: message.id, result: { decision: 'accept' } })}\n`);
    } else if (pending.has(message.id)) {
      const { resolve, reject } = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) reject(new JevBridgeError(message.error.code, message.error.message));
      else resolve(message.result);
    }
  });
  return {
    callbacks,
    notify(method, params = {}) { input.write(`${JSON.stringify({ method, params })}\n`); },
    call(method, params = {}, id = ++counter) {
      return new Promise((resolve, reject) => {
        pending.set(id, { resolve, reject });
        input.write(`${JSON.stringify({ id, method, params })}\n`);
      });
    },
    close() { reader.close(); },
  };
}

test('native callbacks with colliding IDs bypass thread queues and preserve auth decisions', async () => {
  const input = new PassThrough();
  const output = new PassThrough();
  const child = new EventEmitter();
  child.stdin = new PassThrough();
  child.stdout = new PassThrough();
  const native = createInterface({ input: child.stdin });
  let outer;
  native.on('line', (line) => {
    const message = JSON.parse(line);
    if (message.method) {
      outer = message.id;
      child.stdout.write(`${JSON.stringify({ id: 1, method: 'item/commandExecution/requestApproval', params: { threadId: 'fixture' } })}\n`);
    } else {
      assert.equal(message.id, 1);
      assert.deepEqual(message.result, { decision: 'accept' });
      child.stdout.write(`${JSON.stringify({ id: outer, result: { accepted: true } })}\n`);
    }
  });
  connectDesktopBridge({ input, output, child, provider });
  const client = rpcClient(input, output);
  assert.deepEqual(await client.call('future/queuedMutation', { threadId: 'fixture' }, 1), { accepted: true });
  assert.notEqual(client.callbacks[0].id, 1);
  client.close();
  native.close();
  input.end();
  child.emit('exit', 0);
});

test('native app-server preserves official config and confirms round-trip provider switches', {
  skip: !process.env.JEV_DESKTOP_NATIVE_BINARY,
  timeout: 90000,
}, async () => {
  const directory = await mkdtemp(join(tmpdir(), 'jev-desktop-bridge-'));
  const config = 'model = "gpt-6.1-sol"\nmodel_reasoning_effort = "high"\n';
  await writeFile(join(directory, 'config.toml'), config, { mode: 0o600 });
  const manifest = join(directory, 'bridge.json');
  const appAsar = join(directory, 'app.asar');
  await writeFile(appAsar, 'isolated application fixture');
  await writeFile(manifest, JSON.stringify({
    version: 1, nativeBinary: process.env.JEV_DESKTOP_NATIVE_BINARY, provider, appAsar,
    expectedAppSha256: createHash('sha256').update(await readFile(appAsar)).digest('hex'),
    expectedNativeSha256: createHash('sha256').update(await readFile(process.env.JEV_DESKTOP_NATIVE_BINARY)).digest('hex'),
  }), { mode: 0o600 });
  const env = { ...process.env, CODEX_HOME: directory, HOME: directory, JEV_DESKTOP_CONFIG: manifest };
  delete env.OPENAI_API_KEY;
  delete env.OPENAI_BASE_URL;
  const launch = () => spawn(process.execPath, [fileURLToPath(new URL('../bin/jev-desktop-codex', import.meta.url)), 'app-server'], { env, stdio: ['pipe', 'pipe', 'ignore'] });
  let child = launch();
  let client = rpcClient(child.stdin, child.stdout);
  try {
    await client.call('initialize', { clientInfo: { name: 'jev_bridge_test', version: '1' }, capabilities: { experimentalApi: true } });
    client.notify('initialized');
    const models = await client.call('model/list');
    assert.deepEqual(models.data.filter((m) => m.model.startsWith('jev/')).map((m) => m.model), ['jev/auto', 'jev/manual']);
    const started = await client.call('thread/start', { model: 'gpt-6.1-sol', cwd: directory, approvalPolicy: 'never', permissions: ':read-only' });
    assert.equal(started.modelProvider, 'openai');
    assert.equal(started.sandbox.type, 'readOnly', JSON.stringify({ sandbox: started.sandbox, profile: started.activePermissionProfile }));
    const threadId = started.thread.id;
    await client.call('thread/inject_items', { threadId, items: [{ type: 'message', role: 'user', content: [{ type: 'input_text', text: 'Synthetic provider routing fixture. No inference requested.' }] }] });
    for (const [model, effort, expected] of [['jev/auto', 'high', 'jev-router'], ['jev/manual', 'max', 'jev-router'], ['gpt-6.1-sol', 'high', 'openai']]) {
      await client.call('thread/settings/update', { threadId, model, effort });
      const resumed = await client.call('thread/resume', { threadId });
      assert.equal(resumed.model, model);
      assert.equal(resumed.modelProvider, expected);
      assert.equal(resumed.reasoningEffort, effort);
      assert.equal(resumed.sandbox.type, 'readOnly');
    }
    const written = await client.call('config/batchWrite', { edits: [
      { keyPath: 'model', value: 'jev/manual', mergeStrategy: 'replace' },
      { keyPath: 'model_reasoning_effort', value: 'max', mergeStrategy: 'replace' },
    ] });
    assert.equal(written.status, 'okOverridden');
    assert.equal(await readFile(join(directory, 'config.toml'), 'utf8'), config);
    await client.call('thread/settings/update', { threadId, model: 'jev/manual', effort: 'max' });
    await client.call('thread/inject_items', { threadId, items: [{ type: 'message', role: 'user', content: [{ type: 'input_text', text: 'Second synthetic fixture item.' }] }] });
    client.close();
    child.kill('SIGTERM');
    await new Promise((resolve) => child.once('exit', resolve));
    child = launch();
    client = rpcClient(child.stdin, child.stdout);
    await client.call('initialize', { clientInfo: { name: 'jev_bridge_test', version: '1' }, capabilities: { experimentalApi: true } });
    client.notify('initialized');
    const reopened = await client.call('thread/resume', { threadId });
    assert.equal(reopened.model, 'jev/manual');
    assert.equal(reopened.modelProvider, 'jev-router');
    assert.equal(reopened.reasoningEffort, 'max');
    assert.equal(reopened.sandbox.type, 'readOnly');
    assert.equal(await readFile(join(directory, 'config.toml'), 'utf8'), config);
  } finally {
    client.close();
    child.kill('SIGTERM');
    await new Promise((resolve) => child.once('exit', resolve));
    await rm(directory, { recursive: true, force: true });
  }
});

test('provider crossing refuses missing permission provenance before unloading', async () => {
  const { bridge, calls } = fixture();
  const native = bridge.request;
  bridge.request = async (method, params) => {
    const result = await native(method, params);
    delete result.activePermissionProfile;
    return result;
  };
  await assert.rejects(bridge.handle('thread/settings/update', { threadId: 'fixture', model: 'jev/manual', effort: 'high' }), /permission/i);
  assert.equal(calls.some((call) => call.method === 'thread/unsubscribe'), false);
});

test('known official turns retain exact native RPC and do not add thread reads', async () => {
  const { bridge, calls } = fixture();
  await bridge.handle('thread/start', { model: 'gpt-6.1-sol' });
  calls.length = 0;
  const params = { threadId: 'fixture', model: 'gpt-6.1-sol', effort: 'high', input: [] };
  await bridge.handle('turn/start', params);
  assert.deepEqual(calls, [{ method: 'turn/start', params }]);
});

test('a permission-changing resume is rejected and original permissions restored', async () => {
  const { bridge, thread } = fixture();
  const native = bridge.request;
  bridge.request = async (method, params) => {
    const result = await native(method, params);
    if (method === 'thread/resume' && params.modelProvider === 'jev-router') result.sandbox = { type: 'readOnly' };
    return result;
  };
  await assert.rejects(bridge.handle('thread/settings/update', { threadId: 'fixture', model: 'jev/manual', effort: 'max' }), /rebind failed/);
  assert.equal(thread.modelProvider, 'openai');
});

test('an unconfirmed failed restoration blocks subsequent turns', async () => {
  const { bridge } = fixture();
  const native = bridge.request;
  let switched = false;
  bridge.request = async (method, params) => {
    const result = await native(method, params);
    if (method === 'thread/resume' && params.modelProvider === 'jev-router') switched = true;
    if (switched && method === 'thread/resume') result.sandbox = { type: 'readOnly' };
    return result;
  };
  await assert.rejects(bridge.handle('thread/settings/update', { threadId: 'fixture', model: 'jev/manual', effort: 'max' }), /could not be confirmed/);
  await assert.rejects(bridge.handle('turn/start', { threadId: 'fixture', model: 'gpt-6.1-sol', input: [] }), /reopen|unconfirmed/);
});

test('forking a Jev thread with an official model selects the official provider', async () => {
  const { bridge, calls } = fixture();
  await bridge.handle('thread/start', { model: 'jev/manual', config: { model_reasoning_effort: 'max' } });
  const forked = await bridge.handle('thread/fork', { threadId: 'fixture', model: 'gpt-6.1-sol' });
  assert.equal(forked.modelProvider, 'openai');
  assert.equal(calls.at(-1).params.modelProvider, 'openai');
});

test('each native invocation disables Jev for missing or stale application pins', {
  skip: !process.env.JEV_DESKTOP_NATIVE_BINARY,
  timeout: 90000,
}, async () => {
  const directory = await mkdtemp(join(tmpdir(), 'jev-desktop-pins-'));
  const appAsar = join(directory, 'app.asar');
  await writeFile(appAsar, 'isolated application fixture');
  const pins = {
    appAsar,
    expectedAppSha256: createHash('sha256').update(await readFile(appAsar)).digest('hex'),
    expectedNativeSha256: createHash('sha256').update(await readFile(process.env.JEV_DESKTOP_NATIVE_BINARY)).digest('hex'),
  };
  const manifest = join(directory, 'bridge.json');
  const env = { ...process.env, CODEX_HOME: directory, HOME: directory, JEV_DESKTOP_CONFIG: manifest };
  delete env.OPENAI_API_KEY;
  delete env.OPENAI_BASE_URL;
  try {
    for (const change of [
      { expectedAppSha256: undefined },
      { expectedNativeSha256: undefined },
      { expectedAppSha256: '0'.repeat(64) },
      { expectedNativeSha256: '0'.repeat(64) },
    ]) {
      await writeFile(manifest, JSON.stringify({ version: 1, nativeBinary: process.env.JEV_DESKTOP_NATIVE_BINARY, provider, ...pins, ...change }), { mode: 0o600 });
      const child = spawn(process.execPath, [fileURLToPath(new URL('../bin/jev-desktop-codex', import.meta.url)), 'app-server'], { env, stdio: ['pipe', 'pipe', 'ignore'] });
      const client = rpcClient(child.stdin, child.stdout);
      try {
        await client.call('initialize', { clientInfo: { name: 'jev_pin_test', version: '1' }, capabilities: { experimentalApi: true } });
        client.notify('initialized');
        const models = await client.call('model/list');
        assert.equal(models.data.some((model) => model.model.startsWith('jev/')), false, `Jev enabled despite pin mismatch: ${Object.keys(change)[0]}`);
        assert.ok(models.data.length > 0, 'ordinary native model list remains available');
      } finally {
        client.close();
        child.kill('SIGTERM');
        await new Promise((resolve) => child.once('exit', resolve));
      }
    }
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});
