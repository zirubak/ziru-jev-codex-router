import assert from 'node:assert/strict';
import test from 'node:test';
import { execFileSync, spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { createInterface } from 'node:readline';
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { callerBaseUrl } from '../src/caller-auth.mjs';
import { DesktopProviderBridge } from '../src/desktop-provider-bridge.mjs';
import { PrivateRouteState } from '../src/desktop-provider-state.mjs';

const binary = process.env.JEV_DESKTOP_NATIVE_BINARY;
const catalog = process.env.JEV_DESKTOP_NATIVE_CATALOG;
const nativeVersion = binary && catalog ? execFileSync(binary, ['--version'], { encoding: 'utf8' }).trim() : null;
const windowsByVersion = {
  'codex-cli 0.159.0-alpha.12.1': { unknown: 258400, carrier: 828400 },
  'codex-cli 0.160.0': { unknown: 245480, carrier: 828400 },
};

function respond(res, model, number, compaction) {
  const output = [{ id: `msg_${number}`, type: 'message', role: 'assistant', status: 'completed', content: [{ type: 'output_text', text: 'FIXTURE_OK', annotations: [] }] }];
  const tokens = compaction ? 100 : 319852;
  const response = { id: `resp_${number}`, object: 'response', created_at: 1, status: 'completed', model, output, usage: { input_tokens: tokens, output_tokens: 2, total_tokens: tokens + 2 } };
  res.writeHead(200, { 'content-type': 'text/event-stream' });
  for (const event of [
    { type: 'response.created', response: { ...response, status: 'in_progress', output: [] } },
    { type: 'response.output_item.added', output_index: 0, item: { ...output[0], status: 'in_progress', content: [] } },
    { type: 'response.content_part.added', item_id: output[0].id, output_index: 0, content_index: 0, part: { type: 'output_text', text: '', annotations: [] } },
    { type: 'response.output_text.delta', item_id: output[0].id, output_index: 0, content_index: 0, delta: 'FIXTURE_OK' },
    { type: 'response.output_item.done', output_index: 0, item: output[0] },
    { type: 'response.completed', response },
  ]) res.write(`event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`);
  res.end();
}

async function startRouterRelay(t, directory, upstream) {
  const probe = createServer();
  await new Promise(resolve => probe.listen(0, '127.0.0.1', resolve));
  const port = probe.address().port;
  await new Promise(resolve => probe.close(resolve));
  const state = await mkdtemp(join(directory, 'router-state-'));
  const providers = join(state, 'providers.json');
  const models = join(state, 'models.json');
  await writeFile(providers, JSON.stringify({ version: 1, providers: [{
    id: 'jev', displayName: 'Fixture Jev', baseUrl: upstream,
    adapter: 'openai-responses', allowPrivate: true, enabled: true, headers: {},
  }] }));
  await writeFile(models, JSON.stringify({ version: 1, models: ['auto', 'manual'].map(mode => ({
    slug: `jev/${mode}`, gatewayModel: `jev-${mode}`, upstreamModel: mode,
    provider: 'jev', listed: true, displayName: 'Fixture Jev', defaultEffort: 'high',
    description: 'Synthetic native compaction relay', compHash: `jev-${mode}-native-test`, priority: 95,
    reasoningLevels: [{ effort: 'high', description: 'Fixture effort' }],
    inputModalities: ['text'], contextWindow: 872000, autoCompact: 740000,
  })) }));
  const key = 'native-relay-synthetic-caller-capability';
  const child = spawn(process.execPath, [process.env.JEV_DESKTOP_TEST_ROUTER_SOURCE ?? new URL('../src/router.mjs', import.meta.url).pathname], {
    env: { ...process.env, CODEX_HOME: directory, HOME: directory,
      MODEL_ROUTER_STATE_DIR: state, MODEL_ROUTER_GENERIC_PROVIDERS: providers,
      MODEL_ROUTER_USER_MODELS: models, CODEX_ROUTER_CALLER_KEY: key,
      CODEX_ROUTER_INTERNAL_KEY: 'native-relay-synthetic-internal-capability',
      CODEX_ROUTER_PORT: String(port), CODEX_ROUTER_SHOW_ALL_MODELS: '1', CODEX_ROUTER_QUIET: '1',
      CODEX_ROUTER_GATEWAY_BASE_URL: upstream, CODEX_ROUTER_API_BASE_URL: upstream,
      CODEX_NATIVE_BASE_URL: upstream }, stdio: ['ignore', 'ignore', 'pipe'],
  });
  let errors = '';
  child.stderr.on('data', chunk => { errors += chunk; });
  t.after(async () => {
    if (child.exitCode == null && child.signalCode == null) {
      child.kill('SIGTERM');
      await new Promise(resolve => child.once('exit', resolve));
    }
  });
  const base = callerBaseUrl(port, key);
  const deadline = Date.now() + 5000;
  while (Date.now() < deadline) {
    if (child.exitCode != null) throw new Error(errors);
    try {
      const response = await fetch(`${base}/models`);
      if (response.ok) {
        const models = await response.json();
        assert.ok(Array.isArray(models.data), 'Fixture router must publish a valid catalog response');
        return base;
      }
    } catch (error) { if (error.code === 'ERR_ASSERTION') throw error; /* Wait for bind. */ }
    await new Promise(resolve => setTimeout(resolve, 25));
  }
  throw new Error(`Fixture router did not start: ${errors}`);
}

async function fixture(t, { relay = false } = {}) {
  const directory = await mkdtemp(join(tmpdir(), 'jev-native-pressure-'));
  const original = await readFile(catalog);
  const parsed = JSON.parse(original);
  assert.ok(parsed.models.some((model) => model.slug === 'gpt-6.1-sol' && model.max_context_window === 872000));
  const localCatalog = join(directory, 'official-models.json');
  // Use unchanged official metadata only. Real user catalog/config are read-only.
  const catalogData = JSON.stringify({ models: parsed.models });
  await writeFile(localCatalog, catalogData, { mode: 0o600 });
  const config = `model = "gpt-6.1-sol"\nmodel_catalog_json = ${JSON.stringify(localCatalog)}\n`;
  await writeFile(join(directory, 'config.toml'), config, { mode: 0o600 });
  const calls = [];
  const upstreamCalls = [];
  let relayBase;
  const server = createServer(async (req, res) => {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const body = JSON.parse(Buffer.concat(chunks));
    const additionalTools = body.input?.some((item) => item.type === 'additional_tools');
    const compaction = !(body.tools?.length || additionalTools);
    if (req.url.startsWith('/upstream/')) {
      const selection = execFileSync('python3', ['-c',
        'import json,sys; from selection_policy import resolve_selection; from jev_server import plan_collaboration_mode; p=json.load(sys.stdin); print(json.dumps({**resolve_selection(p).state(), "plan_mode": plan_collaboration_mode(p)}))'], {
        cwd: new URL('../../server/', import.meta.url), input: JSON.stringify(body), encoding: 'utf8',
      });
      upstreamCalls.push({ model: body.model, input: body.input, selection: JSON.parse(selection) });
      respond(res, body.model, upstreamCalls.length, compaction);
      return;
    }
    calls.push({ path: req.url, terminalType: body.input?.at(-1)?.type,
      planMode: body.input?.some(item => item.role === 'developer' && JSON.stringify(item).includes('# Plan Mode (Conversational)')),
      bridge: req.headers['x-jev-desktop-recovery'], model: body.model,
      mode: req.headers['x-jev-selection-mode'], lite: req.headers['x-openai-internal-codex-responses-lite'],
      effort: body.reasoning?.effort, additionalTools, compaction });
    if (relayBase && req.headers['x-jev-selection-mode']) {
      const headers = { ...req.headers };
      delete headers.host;
      delete headers['content-length'];
      const forwarded = await fetch(`${relayBase}/responses`, {
        method: 'POST', headers, body: JSON.stringify(body),
      });
      res.writeHead(forwarded.status, { 'content-type': forwarded.headers.get('content-type') });
      for await (const chunk of forwarded.body) res.write(chunk);
      res.end();
      return;
    }
    respond(res, body.model, calls.length, compaction);
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  try {
    if (relay) relayBase = await startRouterRelay(t, directory, `http://127.0.0.1:${server.address().port}/upstream/v1`);
  } catch (error) {
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
    await rm(directory, { recursive: true, force: true });
    throw error;
  }
  t.after(async () => {
    await new Promise((resolve) => server.close(resolve));
    assert.equal(await readFile(join(directory, 'config.toml'), 'utf8'), config);
    assert.equal(await readFile(localCatalog, 'utf8'), catalogData);
    assert.deepEqual(await readFile(catalog), original);
    await rm(directory, { recursive: true, force: true });
  });
  return { directory, calls, upstreamCalls, provider: { name: 'Local fixture', base_url: `http://127.0.0.1:${server.address().port}/v1`, wire_api: 'responses', requires_openai_auth: false } };
}

async function connect(context, args = ['app-server']) {
  const env = { ...process.env, HOME: context.directory, CODEX_HOME: context.directory };
  delete env.OPENAI_API_KEY;
  delete env.OPENAI_BASE_URL;
  delete env.CODEX_APP_SERVER_USE_LOCAL_DAEMON;
  const child = spawn(binary, args, { env, stdio: ['pipe', 'pipe', 'ignore'] });
  const pending = new Map();
  const notices = [];
  const errors = [];
  const settings = [];
  let settingsWaiter;
  let settingsTimer;
  let sequence = 0;
  let turnDone;
  const request = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++sequence;
    pending.set(id, { resolve, reject });
    child.stdin.write(`${JSON.stringify({ id, method, params })}\n`);
  });
  const lines = createInterface({ input: child.stdout });
  lines.on('line', (line) => {
    const message = JSON.parse(line);
    if (pending.has(message.id)) {
      const entry = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) entry.reject(new Error(message.error.message));
      else entry.resolve(message.result);
    } else {
      if (message.method === 'thread/settings/updated') {
        const entry = { raw: message, public: bridge.notification(message) };
        settings.push(entry);
        if (settingsWaiter?.threadId === message.params.threadId) settingsWaiter.resolve(entry);
      }
      if (message.method === 'thread/tokenUsage/updated') notices.push({ window: message.params.tokenUsage.modelContextWindow });
      if (message.method === 'item/started' && message.params.item.type === 'contextCompaction') notices.push({ compaction: true });
      if (message.method === 'error') errors.push(message.params.error);
      if (message.method === 'turn/completed') turnDone?.(message.params.turn.status);
    }
  });
  await request('initialize', { clientInfo: { name: 'jev_pressure_fixture', version: '1' }, capabilities: { experimentalApi: true } });
  child.stdin.write('{"method":"initialized"}\n');
  const bridge = new DesktopProviderBridge({ request, provider: context.provider, state: new PrivateRouteState(join(context.directory, 'jev-desktop-thread-routes')) });
  return {
    request, bridge, notices, settings,
    nextSettings(threadId) {
      return new Promise((resolve, reject) => {
        settingsTimer = setTimeout(() => reject(new Error('Native settings notification timed out')), 10000);
        settingsWaiter = { threadId, resolve(entry) { clearTimeout(settingsTimer); settingsWaiter = null; resolve(entry); } };
      });
    },
    async turn(call, params) {
      let timer;
      const done = new Promise((resolve, reject) => {
        turnDone = resolve;
        timer = setTimeout(() => reject(new Error('Native fixture turn timed out')), 10000);
      });
      try {
        await call('turn/start', { ...params, input: [{ type: 'text', text: 'Synthetic fixture. Do not call tools.', text_elements: [] }] });
        assert.equal(await done, 'completed', JSON.stringify(errors.at(-1)));
      } finally { clearTimeout(timer); }
    },
    async close() {
      clearTimeout(settingsTimer);
      lines.close();
      child.kill('SIGTERM');
      await new Promise((resolve) => child.once('exit', resolve));
    },
  };
}

test('native pressure reproduces unknown alias compaction; known metadata preserves mode, effort, and restart', {
  skip: !binary || !catalog, timeout: 90000,
}, async (t) => {
  const context = await fixture(t);
  const windows = windowsByVersion[nativeVersion];
  assert.ok(windows, `Unqualified native version: ${nativeVersion}`);
  let connection = await connect(context);
  try {
    const legacy = await connection.request('thread/start', {
      model: 'jev/manual', modelProvider: 'legacy-jev', cwd: context.directory, permissions: ':read-only', approvalPolicy: 'never',
      config: { model_providers: { 'legacy-jev': context.provider } },
    });
    await connection.turn(connection.request, { threadId: legacy.thread.id, effort: 'low' });
    await connection.turn(connection.request, { threadId: legacy.thread.id, effort: 'medium' });
    assert.ok(connection.notices.some((item) => item.compaction));
    assert.ok(connection.notices.some((item) => item.window === windows.unknown), JSON.stringify(connection.notices));
    context.calls.length = 0;
    connection.notices.length = 0;
    let started = await connection.bridge.handle('thread/start', { model: 'jev/manual', cwd: context.directory, permissions: ':read-only', approvalPolicy: 'never', config: { model_reasoning_effort: 'medium' } });
    const threadId = started.thread.id;
    for (const [model, effort] of [['jev/manual', 'low'], ['jev/manual', 'medium'], ['jev/manual', 'high'], ['jev/manual', 'xhigh'], ['jev/manual', 'max'], ['jev/auto', 'high']]) {
      await connection.bridge.handle('thread/settings/update', { threadId, model, effort });
      await connection.turn(connection.bridge.handle.bind(connection.bridge), {
        threadId, collaborationMode: { mode: 'default', settings: { model, reasoning_effort: effort, developer_instructions: null } },
      });
    }
    assert.deepEqual(context.calls.map(({ model, mode, effort, lite, additionalTools }) => ({ model, mode, effort, lite, additionalTools })), [
      { model: 'gpt-6.1-sol', mode: 'manual', effort: 'low', lite: 'true', additionalTools: true },
      { model: 'gpt-6.1-sol', mode: 'manual', effort: 'medium', lite: 'true', additionalTools: true },
      { model: 'gpt-6.1-sol', mode: 'manual', effort: 'high', lite: 'true', additionalTools: true },
      { model: 'gpt-6.1-sol', mode: 'manual', effort: 'xhigh', lite: 'true', additionalTools: true },
      { model: 'gpt-6.1-sol', mode: 'manual', effort: 'max', lite: 'true', additionalTools: true },
      { model: 'gpt-6.1-sol', mode: 'auto', effort: 'high', lite: 'true', additionalTools: true },
    ]);
    assert.equal(connection.notices.some((item) => item.compaction), false);
    assert.ok(connection.notices.some((item) => item.window === windows.carrier), JSON.stringify(connection.notices));
    await connection.close();
    connection = await connect(context);
    started = await connection.bridge.handle('thread/resume', { threadId });
    assert.equal(started.model, 'jev/auto');
    assert.equal(started.modelProvider, 'jev-router-auto');
    await connection.turn(connection.bridge.handle.bind(connection.bridge), { threadId });
    assert.equal(context.calls.at(-1).mode, 'auto');
    assert.equal(connection.notices.some((item) => item.compaction), false);
    await connection.bridge.handle('thread/settings/update', { threadId, model: 'gpt-6.1-sol', effort: 'high' });
    await connection.close();
    connection = await connect(context);
    started = await connection.bridge.handle('thread/resume', { threadId });
    assert.equal(started.model, 'gpt-6.1-sol');
    assert.equal(started.modelProvider, 'openai');
    assert.equal(started.sandbox.type, 'readOnly');
  } finally { await connection.close(); }
});

test('native Plan selection survives settings notification and reaches HTTP for both Jev modes', {
  skip: !binary || !catalog, timeout: 90000,
}, async (t) => {
  const context = await fixture(t, { relay: true });
  const connection = await connect(context, ['-c', 'features.code_mode_host=true', 'app-server', '--analytics-default-enabled']);
  try {
    const modes = await connection.bridge.handle('collaborationMode/list', {});
    assert.ok(modes.data.some(mode => mode.mode === 'plan'));
    for (const mode of ['auto', 'manual']) {
      const model = `jev/${mode}`;
      const started = await connection.bridge.handle('thread/start', {
        model, cwd: context.directory, permissions: ':read-only', approvalPolicy: 'never',
      });
      const threadId = started.thread.id;
      const observed = connection.nextSettings(threadId);
      await connection.bridge.handle('thread/settings/update', {
        threadId, collaborationMode: { mode: 'plan', settings: {
          model, reasoning_effort: 'high', developer_instructions: null,
        } },
      });
      const notice = await observed;
      assert.equal(notice.public.params.threadSettings.collaborationMode.mode, 'plan');
      assert.equal(notice.public.params.threadSettings.collaborationMode.settings.model, model);
      await connection.turn(connection.bridge.handle.bind(connection.bridge), {
        threadId, collaborationMode: notice.public.params.threadSettings.collaborationMode,
      });
      assert.equal(context.calls.at(-1).planMode, true);
      assert.equal(context.calls.at(-1).mode, mode);
      assert.equal(context.upstreamCalls.at(-1).selection.plan_mode, true);
      const effortNotice = connection.nextSettings(threadId);
      await connection.bridge.handle('thread/settings/update', { threadId, effort: 'xhigh' });
      const updated = await effortNotice;
      assert.equal(updated.public.params.threadSettings.collaborationMode.mode, 'plan');
      assert.equal(updated.public.params.threadSettings.collaborationMode.settings.model, model);
      const defaultNotice = connection.nextSettings(threadId);
      await connection.bridge.handle('thread/settings/update', {
        threadId, collaborationMode: { mode: 'default', settings: {
          model, reasoning_effort: 'xhigh', developer_instructions: null,
        } },
      });
      const normal = await defaultNotice;
      assert.equal(normal.public.params.threadSettings.collaborationMode.mode, 'default');
      await connection.turn(connection.bridge.handle.bind(connection.bridge), {
        threadId, collaborationMode: normal.public.params.threadSettings.collaborationMode,
      });
      assert.equal(context.upstreamCalls.at(-1).selection.plan_mode, false);
    }
  } finally { await connection.close(); }
});

test('resumed official history keeps Plan selected after switching to Jev before a turn', {
  skip: !binary || !catalog, timeout: 90000,
}, async (t) => {
  const context = await fixture(t);
  let connection = await connect(context);
  try {
    const started = await connection.bridge.handle('thread/start', {
      model: 'gpt-6.1-sol', modelProvider: 'fixture-native', cwd: context.directory,
      permissions: ':read-only', approvalPolicy: 'never',
      config: { model_providers: { 'fixture-native': context.provider } },
    });
    const threadId = started.thread.id;
    await connection.turn(connection.bridge.handle.bind(connection.bridge), { threadId });
    await connection.close();
    connection = await connect(context, ['-c', 'features.code_mode_host=true', 'app-server']);
    await connection.bridge.handle('thread/resume', {
      threadId, config: { model_providers: { 'fixture-native': context.provider } },
    });
    await connection.bridge.handle('thread/settings/update', { threadId, model: 'jev/auto', effort: 'xhigh' });
    connection.settings.length = 0;
    const requestsBeforePlan = context.calls.length;
    const observed = connection.nextSettings(threadId);
    await connection.bridge.handle('thread/settings/update', {
      threadId, collaborationMode: { mode: 'plan', settings: {
        model: 'jev/auto', reasoning_effort: 'xhigh', developer_instructions: null,
      } },
    });
    const notice = await observed;
    assert.equal(notice.public.params.threadSettings.collaborationMode.mode, 'plan');
    assert.equal(notice.public.params.threadSettings.collaborationMode.settings.model, 'jev/auto');
    await connection.bridge.handle('thread/read', { threadId, includeTurns: false });
    assert.equal(context.calls.length, requestsBeforePlan, 'Choosing Plan must not send a model request');
    assert.ok(connection.settings.every(entry => entry.public.params.threadSettings.collaborationMode.mode === 'plan'));
  } finally { await connection.close(); }
});

test('native effort-only updates keep Jev model identity in Desktop settings notifications', {
  skip: !binary || !catalog, timeout: 90000,
}, async (t) => {
  const context = await fixture(t);
  const connection = await connect(context);
  try {
    for (const mode of ['manual', 'auto']) {
      const model = `jev/${mode}`;
      const started = await connection.bridge.handle('thread/start', {
        model, cwd: context.directory, permissions: ':read-only', approvalPolicy: 'never',
        config: { model_reasoning_effort: 'low' },
      });
      const threadId = started.thread.id;
      for (const effort of ['medium', 'high', 'max']) {
        connection.settings.length = 0;
        const observed = connection.nextSettings(threadId);
        await connection.bridge.handle('thread/settings/update', { threadId, effort });
        // The app consumes this nested notification as its next model selection.
        const notice = await observed;
        assert.ok(notice, 'native settings notification must be observed');
        assert.equal(notice.raw.params.threadSettings.model, 'gpt-6.1-sol');
        assert.equal(notice.public.params.threadSettings.model, model);
        assert.equal(notice.public.params.threadSettings.collaborationMode.settings.model, model);
        assert.equal(notice.public.params.threadSettings.effort, effort);
        assert.equal(notice.public.params.threadSettings.modelProvider, `jev-router-${mode}`);
        assert.equal(notice.public.params.threadSettings.sandboxPolicy.type, 'readOnly');
        assert.deepEqual(notice.public.params.threadSettings.sandboxPolicy, notice.raw.params.threadSettings.sandboxPolicy);
        await connection.turn(connection.bridge.handle.bind(connection.bridge), {
          threadId, model: notice.public.params.threadSettings.model, effort,
        });
        assert.equal(context.calls.at(-1).mode, mode);
        assert.equal(context.calls.at(-1).effort, effort);
      }
      await connection.bridge.handle('thread/settings/update', { threadId, model: 'gpt-6.1-sol', effort: 'high' });
      const resumed = await connection.bridge.handle('thread/resume', { threadId });
      assert.equal(resumed.model, 'gpt-6.1-sol');
      assert.equal(resumed.modelProvider, 'openai');
      // Rebind already applies high; only an actual subsequent setting change
      // guarantees the native notification whose pass-through we check here.
      const restored = connection.nextSettings(threadId);
      await connection.bridge.handle('thread/settings/update', { threadId, effort: 'medium' });
      const official = await restored;
      assert.deepEqual(official.public, official.raw);
      assert.equal(official.public.params.threadSettings.model, 'gpt-6.1-sol');
      assert.equal(official.public.params.threadSettings.modelProvider, 'openai');
    }
  } finally { await connection.close(); }
});

test('bundled native settings accept official Ultra after Jev with unchanged notifications', {
  skip: !binary || !catalog, timeout: 90000,
}, async (t) => {
  const context = await fixture(t);
  const connection = await connect(context);
  try {
    const started = await connection.bridge.handle('thread/start', {
      model: 'jev/manual', cwd: context.directory, permissions: ':read-only', approvalPolicy: 'never',
    });
    const threadId = started.thread.id;
    // Exercise the actual local HTTP carrier before returning to native settings.
    await connection.turn(connection.bridge.handle.bind(connection.bridge), { threadId, effort: 'medium' });
    assert.equal(context.calls.at(-1).mode, 'manual');
    await connection.bridge.handle('thread/settings/update', { threadId, model: 'gpt-6.1-sol', effort: 'max' });
    const observed = connection.nextSettings(threadId);
    const [notice] = await Promise.all([
      observed, connection.bridge.handle('thread/settings/update', { threadId, effort: 'ultra' }),
    ]);
    assert.deepEqual(notice.public, notice.raw);
    assert.equal(notice.raw.params.threadSettings.effort, 'ultra');
    assert.equal(notice.raw.params.threadSettings.modelProvider, 'openai');
    assert.equal(connection.bridge.state.read(threadId).effort, 'ultra');
    await connection.bridge.handle('thread/settings/update', { threadId, model: 'jev/manual', effort: 'medium' });
    await connection.bridge.handle('thread/settings/update', { threadId, model: 'gpt-6.1-sol', effort: 'ultra' });
    assert.equal(connection.bridge.state.read(threadId).effort, 'ultra');
    // No authenticated official turn is sent; this checks native settings only.
    assert.equal(context.calls.length, 1);
  } finally { await connection.close(); }
});


for (const historical of ['auto', 'manual']) {
for (const selected of ['auto', 'manual']) {
test(`legacy ${historical} compaction and ${selected} next turn complete through the actual router`, {
  skip: !binary || !catalog, timeout: 90000,
}, async (t) => {
  const context = await fixture(t, { relay: true });
  const connection = await connect(context);
  try {
    const legacy = await connection.request('thread/start', {
      model: `jev/${historical}`, modelProvider: 'legacy-jev', cwd: context.directory,
      permissions: ':read-only', approvalPolicy: 'never',
      config: { model_providers: { 'legacy-jev': context.provider } },
    });
    await connection.turn(connection.request, { threadId: legacy.thread.id, effort: 'high' });
    context.calls.length = 0;
    await connection.bridge.handle('thread/settings/update', {
      threadId: legacy.thread.id, model: `jev/${selected}`, effort: 'high',
    });
    await connection.turn(connection.bridge.handle.bind(connection.bridge), {
      threadId: legacy.thread.id, ...(selected === 'manual' ? { effort: 'low' } : {}),
    });
    assert.ok(context.calls.length > 0);
    assert.equal(context.calls[0].path, '/v1/responses');
    assert.equal(context.calls[0].terminalType, 'message');
    assert.equal(context.upstreamCalls.length, 2);
    assert.deepEqual(context.upstreamCalls.map(call => call.model), [`jev-${selected}`, `jev-${selected}`]);
    assert.equal(connection.bridge.state.read(legacy.thread.id).phase, 'confirmed');
    if (selected === 'manual') assert.equal(context.upstreamCalls[0].selection.user_effort, 'low');
    assert.deepEqual(context.calls.map(({ model, mode, compaction }) => ({ model, mode, compaction })), [
      { model: `jev/${historical}`, mode: selected, compaction: true },
      { model: 'gpt-6.1-sol', mode: selected, compaction: false },
    ]);
  } finally { await connection.close(); }
});
}
}
