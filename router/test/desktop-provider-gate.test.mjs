import assert from 'node:assert/strict';
import test from 'node:test';
import { DesktopProviderBridge, JevBridgeError } from '../src/desktop-provider-bridge.mjs';
import { MemoryRouteState } from '../src/desktop-provider-state.mjs';

const provider = { name: 'Jev', base_url: 'http://127.0.0.1:4202/v1', wire_api: 'responses', requires_openai_auth: false };

/**
 * Native Codex 0.166 rejects turn/start and thread/resume unless the chat's
 * provider equals the app-server's global model_provider. thread/resume also
 * rejects a requested provider (modelProvider or config.model_provider) that
 * differs from the global, so a resume can never move a chat to another
 * provider. This fake reproduces those guards, the config/batchWrite switch
 * that satisfies them, and load/unload, nothing else.
 * `failWrites` lists the 1-based config/batchWrite calls that should fail.
 * `defined` lists the providers present in the user's config.toml: a native
 * config reload fails when the global provider is not one of them.
 * The global provider has two sources, like native's config layers: the user's
 * config.toml (`native.file`, null when the key is absent; `explicit` writes
 * "openai" into the file) and a launch-time pin (`pin`, native's sessionFlags
 * layer, e.g. `codex -c model_provider=...`) that outranks the file.
 * `hold(method, match)` parks the next matching request inside native until it
 * is released; `events` records when each request started and ended.
 */
const ALL_JEV = ['jev-router-auto', 'jev-router-manual', 'jev-router-sol', 'jev-router-astra'];
function guardedNative({ initial = 'openai', failWrites = [], defined = ALL_JEV, failReads = false, explicit = false, pin = null } = {}) {
  const calls = [];
  const events = [];
  const holds = [];
  const threads = new Map();
  const native = {
    file: initial === 'openai' && !explicit ? null : initial, pin, writes: 0, version: 'sha256:fixture', layerMode: 'ok',
    get provider() { return this.pin ?? this.file ?? 'openai'; },
  };
  const hold = (method, match = () => true) => {
    const entry = { method, match, used: false };
    entry.gate = new Promise((resolve) => { entry.release = resolve; });
    entry.started = new Promise((resolve) => { entry.signal = resolve; });
    holds.push(entry);
    return { release: entry.release, started: entry.started };
  };
  const describe = (id) => {
    const thread = threads.get(id);
    return {
      model: thread.model, modelProvider: thread.provider, reasoningEffort: thread.effort, cwd: '/fixture',
      approvalPolicy: 'never', sandbox: { type: 'dangerFullAccess' }, activePermissionProfile: { id: ':danger-full-access' },
      thread: { id, model: thread.model, modelProvider: thread.provider, status: { type: thread.loaded ? 'idle' : 'notLoaded' }, path: `/fixture/${id}.jsonl`, ephemeral: false, turns: [] },
    };
  };
  const mismatch = (chat) => new JevBridgeError(-32600, `This chat uses ${chat}, but your current provider is ${native.provider}.`,
    { type: 'modelProviderMismatch', modelProvider: chat, currentModelProvider: native.provider });
  const guard = (id, requested) => {
    const { provider: chat } = threads.get(id);
    if (chat !== native.provider) throw mismatch(chat);
    if (requested != null && requested !== native.provider) throw mismatch(requested);
  };
  const perform = async (method, params = {}) => {
    calls.push({ method, params: structuredClone(params) });
    await new Promise((resolve) => setImmediate(resolve));
    const parked = holds.find((entry) => !entry.used && entry.method === method && entry.match(params));
    if (parked) { parked.used = true; parked.signal(); await parked.gate; }
    if (method === 'model/list') return { data: [{ id: 'native', model: 'gpt-6.1-sol' }], nextCursor: null };
    if (method === 'config/read') {
      if (failReads) throw new JevBridgeError(-32000, 'config unreadable');
      const owner = native.pin != null ? { type: 'sessionFlags' } : native.file != null ? { type: 'user', file: '/fixture/config.toml' } : null;
      const user = { name: { type: 'user', file: '/fixture/config.toml' }, version: native.version, config: native.layerMode === 'nullProvider' ? { model_provider: null } : native.file != null ? { model_provider: native.file } : {} };
      const layers = [
        ...(native.pin != null ? [{ name: { type: 'sessionFlags' }, version: 'sha256:fixture', config: { model_provider: native.pin } }] : []),
        // `layerMode` models an incomplete config/read: no layer list, no user layer, or a user layer without its config.
        ...(native.layerMode === 'noUser' ? [] : [native.layerMode === 'noConfig' ? { name: user.name, version: user.version } : user]),
        { name: { type: 'system', file: '/etc/codex/config.toml' }, version: 'sha256:fixture', config: {} },
      ];
      return {
        config: {
          model: 'gpt-6.1-sol', ...(native.provider === 'openai' && owner == null ? {} : { model_provider: native.provider }),
          model_providers: Object.fromEntries(defined.map((id) => [id, { name: id }])),
        },
        origins: owner ? { model_provider: { name: owner, version: 'sha256:fixture' } } : {},
        ...(params.includeLayers ? { layers: native.layerMode === 'null' ? null : layers } : {}),
      };
    }
    if (method === 'config/batchWrite' || method === 'config/value/write') {
      native.writes += 1;
      if (failWrites.includes(native.writes)) throw new JevBridgeError(-32000, 'disk is full');
      const edits = method === 'config/value/write' ? [params] : params.edits;
      // Native parses key paths like TOML keys, so a quoted "model_provider" is the same key.
      const edit = edits.find((entry) => String(entry.keyPath).replace(/^"(.*)"$/, '$1') === 'model_provider');
      if (params.expectedVersion != null && params.expectedVersion !== native.version) throw new JevBridgeError(-32000, 'version mismatch');
      if (edit) native.file = edit.value;
      native.version = `version-${native.writes}`;
      return { status: 'ok', version: native.version, filePath: '/fixture/config.toml' };
    }
    if (method === 'thread/start') {
      const id = `thread-${threads.size + 1}`;
      threads.set(id, { model: params.model, provider: params.modelProvider ?? native.provider, effort: params.config?.model_reasoning_effort ?? 'high', loaded: true });
      return describe(id);
    }
    if (method === 'thread/read') return { thread: describe(params.threadId).thread };
    if (method === 'thread/unsubscribe') { threads.get(params.threadId).loaded = false; return { status: 'unsubscribed' }; }
    if (method === 'thread/resume') {
      guard(params.threadId, params.modelProvider ?? params.config?.model_provider);
      threads.get(params.threadId).loaded = true;
      return describe(params.threadId);
    }
    if (method === 'turn/start') { guard(params.threadId); return { turn: { id: `turn-${calls.length}`, status: 'inProgress' } }; }
    return {};
  };
  const request = async (method, params = {}) => {
    const key = params.edits?.[0]?.keyPath;
    events.push({ phase: 'start', method, key });
    try { return await perform(method, params); }
    finally { events.push({ phase: 'end', method, key }); }
  };
  const unload = (id) => { threads.get(id).loaded = false; };
  return { request, calls, native, threads, unload, hold, events };
}

function setup(options, bridgeOptions = {}) {
  const fake = guardedNative(options);
  const warnings = [];
  const state = new MemoryRouteState();
  const open = () => new DesktopProviderBridge({ request: fake.request, provider, state, warn: (text) => warnings.push(text), ...bridgeOptions });
  // `restart` models Desktop reopening: fresh in-memory routes, same private route state.
  return { ...fake, bridge: open(), restart: open, state, warnings };
}

const writes = (calls) => calls.filter((call) => call.method === 'config/batchWrite');
const written = (calls) => writes(calls).map((call) => call.params.edits[0].value);
const turnInput = (threadId) => ({ threadId, input: [{ type: 'text', text: 'synthetic' }] });
const jevThread = async (bridge, model = 'jev/manual') => (await bridge.handle('thread/start', { model })).thread.id;
const officialThread = async (bridge) => (await bridge.handle('thread/start', { model: 'gpt-6.1-sol' })).thread.id;
const official = (threadId) => ({ ...turnInput(threadId), model: 'gpt-6.1-sol' });

test('a Jev turn switches the native provider only after the mismatch, retries once, and restores', async () => {
  const { bridge, calls, native } = setup();
  const threadId = await jevThread(bridge);
  calls.length = 0;
  const result = await bridge.handle('turn/start', turnInput(threadId));
  assert.equal(result.turn.status, 'inProgress');
  assert.deepEqual(calls.map((call) => call.method).filter((method) => ['turn/start', 'config/batchWrite'].includes(method)),
    ['turn/start', 'config/batchWrite', 'turn/start', 'config/batchWrite']);
  assert.deepEqual(writes(calls)[0].params, {
    expectedVersion: 'sha256:fixture',
    edits: [{ keyPath: 'model_provider', value: 'jev-router-manual', mergeStrategy: 'replace' }], reloadUserConfig: true,
  });
  assert.deepEqual(written(calls), ['jev-router-manual', null]);
  assert.deepEqual(writes(calls).map((call) => call.params.expectedVersion), ['sha256:fixture', 'version-1']);
  assert.equal(native.provider, 'openai');
});

test('a concurrent provider edit is not overwritten by restoration or stranded repair', async () => {
  const { bridge, calls, native } = setup();
  const threadId = await jevThread(bridge);
  let release;
  let started;
  const parked = new Promise((resolve) => { started = resolve; });
  const pending = new Promise((resolve) => { release = resolve; });
  const request = bridge.request;
  let turns = 0;
  bridge.request = async (method, params) => {
    if (method === 'turn/start' && ++turns === 2) {
      const result = await request(method, params);
      started();
      await pending;
      return result;
    }
    const result = await request(method, params);
    return result;
  };
  const turn = bridge.handle('turn/start', turnInput(threadId));
  await parked;
  native.file = 'azure';
  native.version = 'external-version';
  release();
  assert.equal((await turn).turn.status, 'inProgress');
  assert.equal(native.file, 'azure');
  assert.deepEqual(writes(calls).at(-1).params.expectedVersion, 'version-1');
  await bridge.settle();
  assert.equal(native.file, 'azure');
  assert.equal(bridge.stranded, null);
  assert.equal(writes(calls).length, 2);
});

test('no configuration is written when the native provider already matches', async () => {
  const jev = setup({ initial: 'jev-router-sol' });
  await jev.bridge.handle('turn/start', turnInput(await jevThread(jev.bridge, 'jev/sol')));
  assert.equal(writes(jev.calls).length, 0);

  const plain = setup();
  const id = await officialThread(plain.bridge);
  plain.calls.length = 0;
  await plain.bridge.handle('turn/start', official(id));
  assert.deepEqual(plain.calls.map((call) => call.method), ['turn/start']);
});

test('an official turn after a Jev turn needs no configuration change', async () => {
  const { bridge, calls, native } = setup();
  const jevId = await jevThread(bridge);
  const officialId = await officialThread(bridge);
  await bridge.handle('turn/start', turnInput(jevId));
  const before = writes(calls).length;
  await bridge.handle('turn/start', official(officialId));
  assert.equal(writes(calls).length, before);
  assert.equal(native.provider, 'openai');
});

test('a mismatch that involves no Jev provider reaches Desktop unchanged', async () => {
  const { bridge, calls, native } = setup({ initial: 'azure' });
  const id = (await bridge.handle('thread/start', { model: 'gpt-6.1-sol', modelProvider: 'openai' })).thread.id;
  await assert.rejects(bridge.handle('turn/start', official(id)),
    (error) => error.code === -32600 && error.data?.type === 'modelProviderMismatch');
  assert.equal(writes(calls).length, 0);
  assert.equal(native.provider, 'azure');
});

test('an Azure chat resume preserves its native mismatch when no provider switch was requested', async () => {
  const { bridge, threads } = setup();
  threads.set('azure-thread', { model: 'gpt-6.1-sol', provider: 'azure', effort: 'high', loaded: true });
  const mismatch = new JevBridgeError(-32600, 'native mismatch', {
    type: 'modelProviderMismatch', modelProvider: 'azure', currentModelProvider: 'openai',
  });
  const request = bridge.request;
  bridge.request = async (method, params) => {
    if (method === 'thread/resume') throw mismatch;
    return request(method, params);
  };
  bridge.routes.set('azure-thread', {
    id: 'azure-thread', model: 'gpt-6.1-sol', modelProvider: 'azure', reasoningEffort: 'high',
    status: { type: 'idle' }, path: '/fixture/azure-thread.jsonl', ephemeral: false, turns: [],
  });
  await assert.rejects(bridge.handle('thread/resume', { threadId: 'azure-thread' }), (error) => error === mismatch);
});

test('resuming a persisted Jev chat switches for the resume and restores afterwards', async () => {
  const { bridge, calls, native } = setup();
  const threadId = await jevThread(bridge, 'jev/sol');
  const resumed = await bridge.handle('thread/resume', { threadId });
  assert.equal(resumed.modelProvider, 'jev-router-sol');
  assert.deepEqual(written(calls), ['jev-router-sol', null]);
  assert.equal(native.provider, 'openai');
});

test('a non-default original provider is restored exactly', async () => {
  const { bridge, calls, native } = setup({ initial: 'azure' });
  await bridge.handle('turn/start', turnInput(await jevThread(bridge)));
  assert.deepEqual(written(calls), ['jev-router-manual', 'azure']);
  assert.equal(native.provider, 'azure');
});

test('a stale Jev default left by an earlier crash is cleared for an official chat', async () => {
  const { bridge, calls, native } = setup({ initial: 'jev-router-astra' });
  const id = (await bridge.handle('thread/start', { model: 'gpt-6.1-sol', modelProvider: 'openai' })).thread.id;
  await bridge.handle('turn/start', official(id));
  assert.deepEqual(written(calls), [null]);
  assert.equal(native.provider, 'openai');
});

test('concurrent turns on chats with different Jev providers never overlap their switches', async () => {
  const { bridge, calls, native } = setup();
  const ids = [await jevThread(bridge, 'jev/manual'), await jevThread(bridge, 'jev/astra'), await jevThread(bridge, 'jev/sol')];
  const results = await Promise.all(ids.map((id) => bridge.handle('turn/start', turnInput(id))));
  assert.ok(results.every((result) => result.turn.status === 'inProgress'));
  const values = written(calls);
  assert.equal(values.length, 6);
  assert.deepEqual(values.filter((_, index) => index % 2 === 1), [null, null, null]);
  assert.deepEqual(values.filter((_, index) => index % 2 === 0).sort(), ['jev-router-astra', 'jev-router-manual', 'jev-router-sol']);
  assert.equal(native.provider, 'openai');
});

test('a new official chat never starts under a provider that is switched for another chat', async () => {
  const { bridge, calls, threads } = setup();
  const jevId = await jevThread(bridge);
  const turn = bridge.handle('turn/start', turnInput(jevId));
  while (!calls.some((call) => call.method === 'config/batchWrite')) await new Promise((resolve) => setImmediate(resolve));
  const started = bridge.handle('thread/start', { model: 'gpt-6.1-sol' });
  const [, created] = await Promise.all([turn, started]);
  assert.equal(threads.get(created.thread.id).provider, 'openai');
});

test('a failed provider switch refuses the request and never retries the turn', async () => {
  const { bridge, calls, warnings } = setup({ failWrites: [1] });
  const threadId = await jevThread(bridge);
  calls.length = 0;
  await assert.rejects(bridge.handle('turn/start', turnInput(threadId)), /provider switch/i);
  assert.equal(calls.filter((call) => call.method === 'turn/start').length, 1);
  assert.equal(writes(calls).length, 1);
  assert.deepEqual(warnings, []);
});

test('a failed restore is reported, keeps the successful result, and is repaired by the next mismatch', async () => {
  const { bridge, calls, native, warnings } = setup({ failWrites: [2] });
  const jevId = await jevThread(bridge);
  const officialId = await officialThread(bridge);
  const result = await bridge.handle('turn/start', turnInput(jevId));
  assert.equal(result.turn.status, 'inProgress');
  assert.equal(native.provider, 'jev-router-manual');
  assert.equal(warnings.length, 1);
  assert.match(warnings[0], /restore/i);
  await bridge.handle('turn/start', official(officialId));
  assert.equal(native.provider, 'openai');
  assert.deepEqual(written(calls), ['jev-router-manual', null, null]);
});

// Native 0.166 binds a chat to the provider it was created with. These tests pin
// the bridge's answer: refuse cleanly, keep the original route usable.
const IMMUTABLE = /existing chat|new chat/i;
const switchTo = (bridge, threadId, model) => bridge.handle('thread/settings/update', { threadId, model });

test('a loaded Jev chat cannot move to an official model: clear refusal, route and global intact', async () => {
  const { bridge, native, threads, state } = setup();
  const threadId = await jevThread(bridge, 'jev/manual');
  await assert.rejects(switchTo(bridge, threadId, 'gpt-6.1-sol'), (error) => error.code === -32000 && IMMUTABLE.test(error.message));
  assert.equal(threads.get(threadId).provider, 'jev-router-manual');
  assert.equal(native.provider, 'openai');
  assert.deepEqual({ model: state.read(threadId).model, phase: state.read(threadId).phase }, { model: 'jev/manual', phase: 'confirmed' });
  const turn = await bridge.handle('turn/start', turnInput(threadId));
  assert.equal(turn.turn.status, 'inProgress');
  assert.equal(native.provider, 'openai');
});

test('a loaded Jev chat cannot change Jev mode: clear refusal, route and global intact', async () => {
  const { bridge, native, threads, state } = setup();
  const threadId = await jevThread(bridge, 'jev/manual');
  await assert.rejects(switchTo(bridge, threadId, 'jev/sol'), (error) => error.code === -32000 && IMMUTABLE.test(error.message));
  assert.equal(threads.get(threadId).provider, 'jev-router-manual');
  assert.equal(native.provider, 'openai');
  assert.equal(state.read(threadId).model, 'jev/manual');
  await bridge.handle('turn/start', turnInput(threadId));
});

test('an unloaded official chat refuses a Jev model without leaving an unconfirmed record', async () => {
  const { bridge, restart, native, threads, state, unload } = setup();
  const threadId = await officialThread(bridge);
  unload(threadId);
  const reopened = restart();
  await assert.rejects(reopened.handle('thread/resume', { threadId, model: 'jev/sol' }),
    (error) => error.code === -32000 && IMMUTABLE.test(error.message));
  assert.equal(threads.get(threadId).provider, 'openai');
  assert.equal(native.provider, 'openai');
  assert.equal(state.read(threadId), null);
  await reopened.handle('thread/resume', { threadId });
  const turn = await reopened.handle('turn/start', official(threadId));
  assert.equal(turn.turn.status, 'inProgress');
});

test('an unloaded Jev chat refuses another Jev mode and its saved route is restored', async () => {
  const { bridge, restart, native, threads, state, unload } = setup();
  const threadId = await jevThread(bridge, 'jev/manual');
  const before = state.read(threadId);
  unload(threadId);
  const reopened = restart();
  await assert.rejects(reopened.handle('thread/resume', { threadId, model: 'jev/sol' }),
    (error) => error.code === -32000 && IMMUTABLE.test(error.message));
  assert.equal(threads.get(threadId).provider, 'jev-router-manual');
  assert.equal(native.provider, 'openai');
  const after = state.read(threadId);
  assert.deepEqual({ model: after.model, effort: after.effort, phase: after.phase }, { model: before.model, effort: before.effort, phase: 'confirmed' });
  const resumed = await reopened.handle('thread/resume', { threadId });
  assert.equal(resumed.model, 'jev/manual');
  await reopened.handle('turn/start', turnInput(threadId));
});

test('a loaded official chat cannot move to a Jev model: clear refusal, official turns keep working', async () => {
  const { bridge, native, threads } = setup();
  const threadId = await officialThread(bridge);
  await assert.rejects(switchTo(bridge, threadId, 'jev/sol'), (error) => error.code === -32000 && IMMUTABLE.test(error.message));
  assert.equal(threads.get(threadId).provider, 'openai');
  assert.equal(native.provider, 'openai');
  const turn = await bridge.handle('turn/start', official(threadId));
  assert.equal(turn.turn.status, 'inProgress');
  assert.equal(native.provider, 'openai');
});

test('a Jev provider missing from the native configuration is refused before anything is written', async () => {
  const { bridge, calls, native } = setup({ defined: [] });
  const threadId = await jevThread(bridge);
  calls.length = 0;
  await assert.rejects(bridge.handle('turn/start', turnInput(threadId)),
    /jev-router-manual is not defined in the native configuration.*No request was sent/);
  assert.equal(writes(calls).length, 0, 'an undefined provider must never be written as the global default');
  assert.equal(calls.filter((call) => call.method === 'turn/start').length, 1, 'the turn is not retried');
  assert.equal(native.provider, 'openai');
});

test('an unreadable native configuration refuses the switch without writing', async () => {
  const { bridge, calls, native } = setup({ failReads: true });
  const threadId = await jevThread(bridge);
  calls.length = 0;
  await assert.rejects(bridge.handle('turn/start', turnInput(threadId)), /could not read the native configuration.*no request was sent/);
  assert.equal(writes(calls).length, 0);
  assert.equal(native.provider, 'openai');
});

test('clearing a stale Jev default needs no provider definition', async () => {
  const { bridge, native, calls } = setup({ initial: 'jev-router-auto', defined: [] });
  const id = (await bridge.handle('thread/start', { model: 'gpt-6.1-sol', modelProvider: 'openai' })).thread.id;
  calls.length = 0;
  await bridge.handle('turn/start', official(id));
  assert.deepEqual(written(calls), [null]);
  assert.equal(native.provider, 'openai');
});

// Second review round: a switch must not interleave with any request whose result
// depends on the global provider, and the original value must be restored from what
// the user's file holds, not guessed from the error that triggered the switch.
const pause = (ms = 20) => new Promise((resolve) => setTimeout(resolve, ms));

test('a chat already being created finishes under the original provider before another chat switches it', async () => {
  const { bridge, hold, threads, native } = setup();
  const jevId = await jevThread(bridge);
  const creating = hold('thread/start');
  let attempts = 0;
  const midSwitch = hold('turn/start', (params) => params.threadId === jevId && ++attempts === 2);
  const created = bridge.handle('thread/start', { model: 'gpt-6.1-sol' });
  await creating.started;
  const turn = bridge.handle('turn/start', turnInput(jevId));
  // Without serialization the turn reaches its retry with the global switched to
  // manual while native is still creating the chat; with it, the turn waits.
  await Promise.race([midSwitch.started, pause(60)]);
  creating.release();
  await midSwitch.started;
  midSwitch.release();
  const [chat] = await Promise.all([created, turn]);
  assert.equal(threads.get(chat.thread.id).provider, 'openai');
  assert.equal(native.provider, 'openai');
});

test('a Desktop configuration write already in flight finishes before the provider switch starts', async () => {
  const { bridge, hold, events } = setup();
  const jevId = await jevThread(bridge);
  const parked = hold('config/batchWrite', (params) => params.edits.some((edit) => edit.keyPath === 'approval_policy'));
  const edit = bridge.handle('config/batchWrite', { edits: [{ keyPath: 'approval_policy', value: 'never', mergeStrategy: 'replace' }] });
  await parked.started;
  const turn = bridge.handle('turn/start', turnInput(jevId));
  await pause();
  parked.release();
  await Promise.all([edit, turn]);
  const order = events.filter((event) => event.method === 'config/batchWrite').map((event) => `${event.phase}:${event.key}`);
  assert.deepEqual(order.slice(0, 4), ['start:approval_policy', 'end:approval_policy', 'start:model_provider', 'end:model_provider']);
});

test('a mismatch seen during another chat\'s switch is re-checked after the restore and needs no write', async () => {
  const { bridge, calls, hold, native } = setup();
  const jevId = await jevThread(bridge);
  const officialId = await officialThread(bridge);
  let seen = 0;
  const parked = hold('turn/start', (params) => params.threadId === jevId && ++seen === 2);
  const jevTurn = bridge.handle('turn/start', turnInput(jevId));
  await parked.started;
  const officialTurn = bridge.handle('turn/start', official(officialId));
  await pause();
  parked.release();
  const [first, second] = await Promise.all([jevTurn, officialTurn]);
  assert.equal(first.turn.status, 'inProgress');
  assert.equal(second.turn.status, 'inProgress');
  assert.deepEqual(written(calls), ['jev-router-manual', null]);
  assert.equal(native.provider, 'openai');
});

test('after a failed restore the next new chat repairs the provider first and starts on the original', async () => {
  const { bridge, native, threads } = setup({ failWrites: [2] });
  await bridge.handle('turn/start', turnInput(await jevThread(bridge)));
  assert.equal(native.provider, 'jev-router-manual');
  const created = await bridge.handle('thread/start', { model: 'gpt-6.1-sol' });
  assert.equal(threads.get(created.thread.id).provider, 'openai');
  assert.equal(native.provider, 'openai');
});

test('while a failed restore cannot be repaired, new chats are refused instead of created on a Jev provider', async () => {
  const { bridge, native, threads } = setup({ failWrites: [2, 3] });
  await bridge.handle('turn/start', turnInput(await jevThread(bridge)));
  const before = threads.size;
  await assert.rejects(bridge.handle('thread/start', { model: 'gpt-6.1-sol' }), /could not be restored.*no request was sent/i);
  assert.equal(threads.size, before, 'no chat may be created on the stranded provider');
  assert.equal(native.provider, 'jev-router-manual');
});

test('an explicit model_provider in the user file is written back, not deleted', async () => {
  const { bridge, calls, native } = setup({ initial: 'openai', explicit: true });
  await bridge.handle('turn/start', turnInput(await jevThread(bridge)));
  assert.deepEqual(written(calls), ['jev-router-manual', 'openai']);
  assert.equal(native.file, 'openai');
});

test('a provider pinned outside the user file is refused without writing anything', async () => {
  for (const pin of ['jev-router-astra', 'azure']) {
    const { bridge, calls, native } = setup({ pin });
    const jevId = await jevThread(bridge, 'jev/manual');
    const officialId = (await bridge.handle('thread/start', { model: 'gpt-6.1-sol', modelProvider: 'openai' })).thread.id;
    calls.length = 0;
    await assert.rejects(bridge.handle('turn/start', turnInput(jevId)), /pinned.*no request was sent/i, `jev chat, pin ${pin}`);
    // A pin by a Jev provider is refused as pinned; a user's own azure pin never involves a
    // Jev provider for an official chat, so native's error reaches Desktop untouched.
    await assert.rejects(bridge.handle('turn/start', official(officialId)),
      pin === 'azure' ? /current provider is azure/ : /pinned.*no request was sent/i, `official chat, pin ${pin}`);
    assert.equal(writes(calls).length, 0, `nothing may be written while ${pin} is pinned`);
    assert.equal(native.file, null, 'the user file must stay untouched');
  }
});

test('after a failed restore the exact original is recovered even when the next chat needs another provider', async () => {
  const { bridge, native } = setup({ initial: 'azure', failWrites: [2] });
  const jevId = await jevThread(bridge);
  const azureId = (await bridge.handle('thread/start', { model: 'gpt-6.1-sol' })).thread.id;
  await bridge.handle('turn/start', turnInput(jevId));
  assert.equal(native.provider, 'jev-router-manual');
  const turn = await bridge.handle('turn/start', official(azureId));
  assert.equal(turn.turn.status, 'inProgress');
  assert.equal(native.file, 'azure', 'the user\'s own default must not be cleared');
});

test('a chat on a custom default provider stays usable after a refused switch to Jev', async () => {
  const { bridge } = setup({ initial: 'azure' });
  const threadId = (await bridge.handle('thread/start', { model: 'gpt-6.1-sol' })).thread.id;
  await assert.rejects(switchTo(bridge, threadId, 'jev/sol'), (error) => error.code === -32000 && IMMUTABLE.test(error.message));
  const turn = await bridge.handle('turn/start', official(threadId));
  assert.equal(turn.turn.status, 'inProgress');
});

// Codex round 2.

test('a Desktop provider change made while a restore is stranded is not overwritten by the later repair', async () => {
  // Write 2 (restore) and write 3 (the repair attempted before the user's change) fail;
  // write 4 is the user's own change to azure, which must outlive the stranded value.
  const { bridge, native, calls } = setup({ failWrites: [2, 3] });
  await bridge.handle('turn/start', turnInput(await jevThread(bridge)));
  assert.equal(native.file, 'jev-router-manual');
  await bridge.handle('config/batchWrite', { edits: [{ keyPath: 'model_provider', value: 'azure', mergeStrategy: 'replace' }] });
  assert.equal(native.file, 'azure');
  const before = writes(calls).length;
  await bridge.handle('thread/start', { model: 'gpt-6.1-sol' });
  assert.equal(writes(calls).length, before, 'no stale repair may run after the user changed the provider');
  assert.equal(native.file, 'azure', 'the user\'s choice must survive');
});

test('an unloaded Jev chat whose switch could not be prepared keeps its confirmed route', async () => {
  const { bridge, restart, state, unload, calls } = setup({ failReads: true });
  const threadId = await jevThread(bridge, 'jev/manual');
  const before = state.read(threadId);
  unload(threadId);
  const reopened = restart();
  calls.length = 0;
  await assert.rejects(reopened.handle('thread/resume', { threadId, effort: 'low' }), /could not read the native configuration.*no request was sent/);
  assert.equal(writes(calls).length, 0);
  const after = state.read(threadId);
  assert.deepEqual({ model: after.model, effort: after.effort, phase: after.phase }, { model: before.model, effort: before.effort, phase: 'confirmed' });
  // The chat is still addressable: the next attempt fails on the unreadable config, not on a stuck route.
  await assert.rejects(reopened.handle('thread/resume', { threadId }), /could not read the native configuration/);
});

test('a loaded Jev chat whose switch could not be prepared keeps its confirmed route', async () => {
  const { bridge, state, calls } = setup({ failReads: true });
  const threadId = await jevThread(bridge, 'jev/manual');
  const before = state.read(threadId);
  calls.length = 0;
  await assert.rejects(bridge.handle('turn/start', { ...turnInput(threadId), effort: 'low' }), /could not read the native configuration.*no request was sent/);
  assert.equal(writes(calls).length, 0);
  const after = state.read(threadId);
  assert.deepEqual({ model: after.model, effort: after.effort, phase: after.phase }, { model: before.model, effort: before.effort, phase: 'confirmed' });
  await assert.rejects(bridge.handle('turn/start', turnInput(threadId)), /could not read the native configuration/);
});

test('a matching turn still repairs a stranded restore instead of leaving the global on a Jev provider', async () => {
  const { bridge, native, warnings } = setup({ failWrites: [2] });
  const jevId = await jevThread(bridge);
  await bridge.handle('turn/start', turnInput(jevId));
  assert.equal(native.provider, 'jev-router-manual');
  assert.equal(warnings.length, 1);
  // The same Jev chat now matches the leftover global, so native would accept it as is.
  const turn = await bridge.handle('turn/start', turnInput(jevId));
  assert.equal(turn.turn.status, 'inProgress');
  assert.equal(native.provider, 'openai', 'the earlier restore must be retried, not carried forward');
});

test('a matching turn is still sent when the repair of a stranded restore keeps failing', async () => {
  const { bridge, native } = setup({ failWrites: [2, 3, 4] });
  const jevId = await jevThread(bridge);
  await bridge.handle('turn/start', turnInput(jevId));
  assert.equal(native.writes, 2, 'switch and failed restore');
  const turn = await bridge.handle('turn/start', turnInput(jevId));
  assert.equal(turn.turn.status, 'inProgress', 'a request native accepts under the right provider is not blocked by a failed repair');
  assert.equal(native.writes, 3, 'the repair must have been attempted (and failed) before the turn');
  assert.equal(native.provider, 'jev-router-manual');
});

// Codex round 3.

test('a quoted model_provider key path written while a restore is stranded is not overwritten', async () => {
  for (const [method, params] of [
    ['config/value/write', { keyPath: '"model_provider"', value: 'azure', mergeStrategy: 'replace' }],
    ['config/batchWrite', { edits: [{ keyPath: '"model_provider"', value: 'azure', mergeStrategy: 'replace' }] }],
  ]) {
    // Write 2 (restore) and write 3 (the repair ahead of the user's change) fail.
    const { bridge, native } = setup({ failWrites: [2, 3] });
    await bridge.handle('turn/start', turnInput(await jevThread(bridge)));
    assert.equal(native.file, 'jev-router-manual');
    await bridge.handle(method, params);
    assert.equal(native.file, 'azure', `${method}: the user's write landed`);
    const writesBefore = native.writes;
    await bridge.handle('thread/start', { model: 'gpt-6.1-sol' });
    assert.equal(native.file, 'azure', `${method}: the user's choice must survive the next repair`);
    assert.equal(native.writes, writesBefore, `${method}: no stale repair may run`);
  }
});

test('a default changed outside the bridge after a failed restore is not overwritten by the repair', async () => {
  const { bridge, native } = setup({ initial: 'openai', explicit: true, failWrites: [2] });
  await bridge.handle('turn/start', turnInput(await jevThread(bridge)));
  assert.equal(native.file, 'jev-router-manual');
  native.file = 'azure'; // an editor or another Codex process, not a bridge request
  const writesBefore = native.writes;
  const created = await bridge.handle('thread/start', { model: 'gpt-6.1-sol' });
  assert.equal(native.file, 'azure', 'the outside change must stand');
  assert.equal(native.writes, writesBefore, 'nothing may be written over it');
  assert.ok(created.thread.id);
});

test('a Jev turn after an outside change restores that change, not the older stranded value', async () => {
  const { bridge, native } = setup({ initial: 'openai', explicit: true, failWrites: [2] });
  const jevId = await jevThread(bridge);
  await bridge.handle('turn/start', turnInput(jevId));
  native.file = 'azure';
  const turn = await bridge.handle('turn/start', turnInput(jevId));
  assert.equal(turn.turn.status, 'inProgress');
  assert.equal(native.file, 'azure', 'the section must put back the value it found, not the stale openai');
});

test('a restore write that never answers does not block a turn native would accept', async () => {
  const { bridge, native, hold, threads } = setup({ failWrites: [2] }, { repairWaitMs: 20 });
  const jevId = await jevThread(bridge);
  await bridge.handle('turn/start', turnInput(jevId));
  assert.equal(native.provider, 'jev-router-manual');
  const parked = hold('config/batchWrite');
  const outcome = await Promise.race([
    bridge.handle('turn/start', turnInput(jevId)),
    new Promise((resolve) => setTimeout(() => resolve('blocked'), 1500)),
  ]);
  assert.notEqual(outcome, 'blocked', 'the turn must not wait for a repair that never answers');
  assert.equal(outcome.turn.status, 'inProgress');
  await parked.started;
  assert.equal(native.provider, 'jev-router-manual', 'the parked repair has not applied yet');
  // The unfinished repair stays serialized: later sections wait for it and then start clean.
  const creating = bridge.handle('thread/start', { model: 'gpt-6.1-sol' });
  parked.release();
  const created = await creating;
  assert.equal(threads.get(created.thread.id).provider, 'openai');
  assert.equal(native.provider, 'openai');
});

// Codex round 4.

// 'nullProvider': the key is present but null; native never produces it (it rejects a TOML null),
// yet an absent key and an explicit null must not be confused.
const LAYER_FAULTS = ['null', 'noUser', 'noConfig', 'nullProvider'];

test('an unreadable user layer keeps the stranded restore instead of treating it as repaired', async () => {
  for (const fault of LAYER_FAULTS) {
    const { bridge, native, threads } = setup({ initial: 'azure', failWrites: [2] });
    await bridge.handle('turn/start', turnInput(await jevThread(bridge)));
    assert.equal(native.file, 'jev-router-manual', fault);
    native.layerMode = fault;
    const before = threads.size;
    await assert.rejects(bridge.handle('thread/start', { model: 'gpt-6.1-sol' }), /could not be restored.*no request was sent/i, fault);
    assert.equal(threads.size, before, `${fault}: no chat may inherit the leftover Jev provider`);
    assert.equal(native.file, 'jev-router-manual', `${fault}: nothing may be guessed onto the file`);
    // Once the configuration reads again, the original value still goes back.
    native.layerMode = 'ok';
    const created = await bridge.handle('thread/start', { model: 'gpt-6.1-sol' });
    assert.equal(threads.get(created.thread.id).provider, 'azure', fault);
    assert.equal(native.file, 'azure', `${fault}: the stranded value must survive until it can be written`);
  }
});

test('a switch is refused, not guessed, when the user layer cannot be read', async () => {
  for (const fault of LAYER_FAULTS) {
    const { bridge, native, calls } = setup({ initial: 'azure' });
    const jevId = await jevThread(bridge);
    native.layerMode = fault;
    calls.length = 0;
    await assert.rejects(bridge.handle('turn/start', turnInput(jevId)), /could not read the native configuration.*no request was sent/i, fault);
    assert.equal(writes(calls).length, 0, `${fault}: an unknown original must never be overwritten`);
    assert.equal(native.file, 'azure', fault);
  }
});
