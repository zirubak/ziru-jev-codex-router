import assert from 'node:assert/strict';
import test from 'node:test';
import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { createInterface } from 'node:readline';
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { DesktopProviderBridge } from '../src/desktop-provider-bridge.mjs';
import { PrivateRouteState } from '../src/desktop-provider-state.mjs';

const binary = process.env.JEV_DESKTOP_NATIVE_BINARY;
const catalog = process.env.JEV_DESKTOP_NATIVE_CATALOG;

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

async function fixture(t) {
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
  const server = createServer(async (req, res) => {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const body = JSON.parse(Buffer.concat(chunks));
    const additionalTools = body.input?.some((item) => item.type === 'additional_tools');
    const compaction = !(body.tools?.length || additionalTools);
    calls.push({ model: body.model, mode: req.headers['x-jev-selection-mode'], lite: req.headers['x-openai-internal-codex-responses-lite'], effort: body.reasoning?.effort, additionalTools, compaction });
    respond(res, body.model, calls.length, compaction);
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  t.after(async () => {
    await new Promise((resolve) => server.close(resolve));
    assert.equal(await readFile(join(directory, 'config.toml'), 'utf8'), config);
    assert.equal(await readFile(localCatalog, 'utf8'), catalogData);
    assert.deepEqual(await readFile(catalog), original);
    await rm(directory, { recursive: true, force: true });
  });
  return { directory, calls, provider: { name: 'Local fixture', base_url: `http://127.0.0.1:${server.address().port}/v1`, wire_api: 'responses', requires_openai_auth: false } };
}

async function connect(context) {
  const env = { ...process.env, HOME: context.directory, CODEX_HOME: context.directory };
  delete env.OPENAI_API_KEY;
  delete env.OPENAI_BASE_URL;
  delete env.CODEX_APP_SERVER_USE_LOCAL_DAEMON;
  const child = spawn(binary, ['app-server'], { env, stdio: ['pipe', 'pipe', 'ignore'] });
  const pending = new Map();
  const notices = [];
  const settings = [];
  let settingsWaiter;
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
      if (message.method === 'turn/completed') turnDone?.(message.params.turn.status);
    }
  });
  await request('initialize', { clientInfo: { name: 'jev_pressure_fixture', version: '1' }, capabilities: { experimentalApi: true } });
  child.stdin.write('{"method":"initialized"}\n');
  const bridge = new DesktopProviderBridge({ request, provider: context.provider, state: new PrivateRouteState(join(context.directory, 'private-routes')) });
  return {
    request, bridge, notices, settings,
    nextSettings(threadId) {
      return new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error('Native settings notification timed out')), 10000);
        settingsWaiter = { threadId, resolve(entry) { clearTimeout(timer); settingsWaiter = null; resolve(entry); } };
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
        assert.equal(await done, 'completed');
      } finally { clearTimeout(timer); }
    },
    async close() {
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
  let connection = await connect(context);
  try {
    const legacy = await connection.request('thread/start', {
      model: 'jev/manual', modelProvider: 'legacy-jev', cwd: context.directory, permissions: ':read-only', approvalPolicy: 'never',
      config: { model_providers: { 'legacy-jev': context.provider } },
    });
    await connection.turn(connection.request, { threadId: legacy.thread.id, effort: 'low' });
    await connection.turn(connection.request, { threadId: legacy.thread.id, effort: 'medium' });
    assert.ok(connection.notices.some((item) => item.compaction));
    assert.ok(connection.notices.some((item) => item.window === 258400));
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
    assert.ok(connection.notices.some((item) => item.window === 828400));
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
