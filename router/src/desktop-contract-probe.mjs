import { execFile, spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { mkdtemp, readFile, realpath, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { promisify, isDeepStrictEqual } from 'node:util';
import { DesktopProviderBridge } from './desktop-provider-bridge.mjs';
import { PrivateRouteState } from './desktop-provider-state.mjs';
import { DesktopContractMismatch } from './desktop-compatibility.mjs';

const run = promisify(execFile);
const CARRIER = 'gpt-6.1-sol';
const EFFORTS = ['low', 'medium', 'high', 'xhigh', 'max'];
const REQUEST_TIMEOUT = 8000;
const MAX_BYTES = 4 * 1024 * 1024;
const PRESSURE_TOKENS = 319852;
const MIN_CONTEXT = 740000;
const NETWORK_PROFILE = '(version 1)(allow default)(deny network*)(allow network-outbound (remote ip "localhost:*"))';

function nativeCommand(binary, args) {
  return process.platform === 'darwin'
    ? { file: '/usr/bin/sandbox-exec', args: ['-p', NETWORK_PROFILE, binary, ...args] }
    : { file: binary, args };
}

function failure(reason) {
  return new Error(`Jev Desktop compatibility: ${reason}. Keep Jev disabled for this app build and update the router.`);
}

function requireContract(condition, reason) {
  if (!condition) throw new DesktopContractMismatch(reason);
}

function requireSafety(condition, reason) {
  if (!condition) throw failure(reason);
}

async function bundledMetadata(context) {
  const options = { env: context.env, cwd: context.directory, timeout: REQUEST_TIMEOUT, killSignal: 'SIGKILL', maxBuffer: MAX_BYTES, encoding: 'utf8' };
  const versionCommand = nativeCommand(context.binary, ['--version']);
  const nativeVersion = (await run(versionCommand.file, versionCommand.args, options)).stdout.trim();
  requireContract(/^codex-cli [0-9][\w.+-]{0,100}$/.test(nativeVersion), 'native version protocol changed');
  const catalogCommand = nativeCommand(context.binary, ['debug', 'models', '--bundled']);
  const catalogText = (await run(catalogCommand.file, catalogCommand.args, options)).stdout;
  let catalog;
  try { catalog = JSON.parse(catalogText); }
  catch (error) {
    if (error instanceof SyntaxError) throw new DesktopContractMismatch('bundled native catalog protocol changed');
    throw error;
  }
  requireContract(catalog && typeof catalog === 'object' && Array.isArray(catalog.models),
    'bundled native catalog protocol changed');
  const carrier = catalog.models.find((model) => model?.slug === CARRIER);
  requireContract(carrier?.max_context_window >= 872000
    && EFFORTS.every((effort) => carrier.supported_reasoning_levels?.some((entry) => entry.effort === effort)),
  'carrier metadata does not preserve the required context and Manual efforts');
  const catalogPath = join(context.directory, 'official-models.json');
  context.catalogData = JSON.stringify({ models: catalog.models });
  context.config = `model = "${CARRIER}"\nmodel_catalog_json = ${JSON.stringify(catalogPath)}\ncli_auth_credentials_store = "file"\n[analytics]\nenabled = false\n[features]\nplugins = false\napps = false\nremote_plugin = false\nplugin_sharing = false\nrecommended_plugins = false\n`;
  await writeFile(catalogPath, context.catalogData, { mode: 0o600 });
  await writeFile(join(context.directory, 'config.toml'), context.config, { mode: 0o600 });
  return nativeVersion;
}

function respond(res, number) {
  const output = [{ id: `msg_${number}`, type: 'message', role: 'assistant', status: 'completed', content: [{ type: 'output_text', text: 'JEV_CONTRACT_OK', annotations: [] }] }];
  const response = { id: `resp_${number}`, object: 'response', created_at: 1, status: 'completed', model: CARRIER, output,
    usage: { input_tokens: PRESSURE_TOKENS, output_tokens: 2, total_tokens: PRESSURE_TOKENS + 2 } };
  res.writeHead(200, { 'content-type': 'text/event-stream' });
  for (const event of [
    { type: 'response.created', response: { ...response, status: 'in_progress', output: [] } },
    { type: 'response.output_item.added', output_index: 0, item: { ...output[0], status: 'in_progress', content: [] } },
    { type: 'response.content_part.added', item_id: output[0].id, output_index: 0, content_index: 0, part: { type: 'output_text', text: '', annotations: [] } },
    { type: 'response.output_text.delta', item_id: output[0].id, output_index: 0, content_index: 0, delta: 'JEV_CONTRACT_OK' },
    { type: 'response.output_item.done', output_index: 0, item: output[0] },
    { type: 'response.completed', response },
  ]) res.write(`event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`);
  res.end();
}

function verifyHttp(context, req, body) {
  requireContract(req.method === 'POST' && req.url === '/v1/responses', 'unexpected HTTP path or automatic compaction');
  const expected = context.expected;
  requireContract(expected && !expected.received, 'unexpected extra native HTTP request');
  requireContract(body.model === CARRIER && req.headers['x-jev-selection-mode'] === expected.mode
    && body.reasoning?.effort === expected.effort, 'HTTP carrier, selection mode, or effort changed');
  requireContract(req.headers['x-jev-desktop-recovery'] === 'bridge-active', 'native config did not replace the Desktop recovery marker for a bridged request');
  const canonical = JSON.stringify(body.input);
  requireContract(Array.isArray(body.input) && expected.markers.every((marker) => canonical.includes(marker)), 'canonical turn input and history were not preserved');
  if (expected.collaborationMarker) requireContract(canonical.includes(`<collaboration_mode>${expected.collaborationMarker}</collaboration_mode>`),
    'Plan collaboration instructions were not preserved');
  const tools = body.tools?.length || body.input.some((item) => item.type === 'additional_tools' && item.tools?.length);
  requireContract(tools, 'canonical tool metadata was not preserved');
  requireContract(req.headers['x-openai-internal-codex-responses-lite'] === 'true', 'canonical Responses transport changed');
  expected.received = true;
  context.httpRequests += 1;
}

function refuseRecovery(context, req, body, res) {
  const recovery = context.recovery;
  requireSafety(req.method === 'POST' && ['/v1/responses', '/v1/responses/compact'].includes(req.url),
    'bare native recovery used an unexpected HTTP path');
  requireSafety(req.headers['x-jev-desktop-recovery'] === 'required'
    && req.headers['x-jev-selection-mode'] === recovery.mode && body.model === CARRIER,
  'bare native did not preserve the persisted recovery guard');
  recovery.requests += 1;
  requireSafety(recovery.requests <= 16, 'bare native repeatedly retried the recovery refusal');
  context.recoveryDeniedRequests += 1;
  if (req.url.endsWith('/compact')) context.recoveryCompactRequests += 1;
  // Exercise the router's refusal response without invoking any model or upstream.
  res.writeHead(400, { 'content-type': 'application/json' });
  res.end(JSON.stringify({ error: { type: 'invalid_request_error', code: 'jev_desktop_recovery_required',
    message: 'Jev Desktop needs to reconnect. No request was sent.' } }));
}

async function startResponder(context) {
  const server = createServer((req, res) => {
    void (async () => {
      const chunks = [];
      let size = 0;
      for await (const chunk of req) {
        size += chunk.length;
        requireSafety(size <= MAX_BYTES, 'synthetic HTTP request exceeded the size limit');
        chunks.push(chunk);
      }
      let body;
      try { body = JSON.parse(Buffer.concat(chunks)); }
      catch { throw new DesktopContractMismatch('native HTTP JSON protocol changed'); }
      if (context.recovery) return refuseRecovery(context, req, body, res);
      verifyHttp(context, req, body);
      respond(res, context.httpRequests);
    })().catch((error) => {
      context.fail(error);
      if (!res.headersSent) res.writeHead(400);
      res.end();
    });
  });
  server.requestTimeout = REQUEST_TIMEOUT;
  server.headersTimeout = REQUEST_TIMEOUT;
  context.server = server;
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  context.provider = { name: 'Jev isolated compatibility probe', base_url: `http://127.0.0.1:${server.address().port}/v1`,
    wire_api: 'responses', requires_openai_auth: false };
  for (const mode of ['auto', 'manual']) {
    context.config += `\n[model_providers.jev-router-${mode}]\nname = "Jev recovery probe"\nbase_url = ${JSON.stringify(context.provider.base_url)}\nwire_api = "responses"\nrequires_openai_auth = false\nhttp_headers = { "x-jev-desktop-recovery" = "required", "x-jev-selection-mode" = "${mode}" }\n`;
  }
  await writeFile(join(context.directory, 'config.toml'), context.config, { mode: 0o600 });
}

class NativeSession {
  constructor(context) {
    this.context = context;
    this.sequence = 0;
    this.pending = new Map();
    this.notices = [];
    this.noticeSequence = 0;
    this.waiters = new Set();
    this.buffer = '';
    const command = nativeCommand(context.binary, ['app-server']);
    this.child = spawn(command.file, command.args, { env: context.env, cwd: context.directory,
      detached: process.platform !== 'win32', stdio: ['pipe', 'pipe', 'ignore'] });
    this.exited = new Promise((resolve) => { this.resolveExit = resolve; });
    this.bridge = new DesktopProviderBridge({ request: this.request.bind(this), provider: context.provider,
      state: new PrivateRouteState(join(context.directory, 'private-routes')) });
    this.child.on('error', (error) => {
      this.fail(error);
      this.resolveExit();
    });
    this.child.on('exit', () => {
      if (!this.closing) this.fail(failure('native process exited before qualification completed'));
      this.resolveExit();
    });
    this.child.stdin.on('error', (error) => { if (!this.closing) this.fail(error); });
    this.child.stdout.setEncoding('utf8');
    this.child.stdout.on('data', (data) => this.consume(data));
  }

  fail(error) {
    this.error ??= error;
    this.context.error ??= this.error;
    for (const pending of this.pending.values()) { clearTimeout(pending.timer); pending.reject(this.error); }
    this.pending.clear();
    for (const waiter of this.waiters) { clearTimeout(waiter.timer); waiter.reject(this.error); }
    this.waiters.clear();
  }

  consume(data) {
    if (this.error || this.closing) return;
    this.buffer += data;
    if (Buffer.byteLength(this.buffer) > MAX_BYTES) return this.fail(failure('native protocol frame exceeded the size limit'));
    let newline;
    while ((newline = this.buffer.indexOf('\n')) !== -1) {
      const line = this.buffer.slice(0, newline);
      this.buffer = this.buffer.slice(newline + 1);
      let message;
      try { message = JSON.parse(line); }
      catch { this.fail(new DesktopContractMismatch('native JSON protocol changed')); }
      if (!this.error) {
        try { this.receive(message); }
        catch (error) { this.fail(error); }
      }
      if (this.error) return;
    }
  }

  receive(message) {
    requireContract(message && typeof message === 'object', 'native protocol envelope changed');
    if (message.method && message.id != null) {
      // The responder only returns text. Any native callback is outside the probe contract.
      this.child.stdin.write(`${JSON.stringify({ id: message.id, error: { code: -32601, message: 'Qualification forbids tool execution and approval callbacks.' } })}\n`);
      return this.fail(failure('unexpected native callback; no tool or permission was granted'));
    }
    if (message.id != null) {
      const pending = this.pending.get(message.id);
      requireContract(pending, 'native response identity changed');
      clearTimeout(pending.timer);
      this.pending.delete(message.id);
      if (message.error) {
        if (message.error.code === -32601) pending.reject(new DesktopContractMismatch(`native ${pending.method} method is unavailable`));
        else pending.reject(failure(`native ${pending.method} request was rejected`));
      }
      else pending.resolve(message.result);
      return;
    }
    requireContract(typeof message.method === 'string', 'native notification protocol changed');
    const mapped = this.bridge.notification(message);
    const recovery = this.context.recovery;
    if (message.method === 'item/started' && message.params?.item?.type === 'contextCompaction') {
      if (recovery?.threadId === message.params.threadId) {
        this.context.recoveryCompactionAttempts += 1;
        return;
      }
      this.context.compactions += 1;
      return this.fail(failure('unexpected automatic context compaction'));
    }
    if (recovery && (message.method === 'item/agentMessage/delta'
      || ['item/started', 'item/completed'].includes(message.method) && message.params?.item?.type === 'agentMessage')) {
      this.context.recoveryModelOutputs += 1;
      return this.fail(failure('bare native recovery produced model output despite refusal'));
    }
    if (!recovery && message.method === 'thread/tokenUsage/updated') {
      const window = message.params?.tokenUsage?.modelContextWindow;
      if (typeof window === 'number') {
        this.context.windowCount += 1;
        this.context.minimumContextWindow = Math.min(this.context.minimumContextWindow, window);
      }
    }
    if (!['thread/settings/updated', 'turn/completed'].includes(message.method)) return;
    const notice = { sequence: ++this.noticeSequence, raw: message, public: mapped };
    this.notices.push(notice);
    if (this.notices.length > 32) this.notices.shift();
    for (const waiter of this.waiters) {
      if (waiter.matches(notice)) { clearTimeout(waiter.timer); this.waiters.delete(waiter); waiter.resolve(notice); }
    }
  }

  request(method, params = {}) {
    if (this.error) return Promise.reject(this.error);
    return new Promise((resolve, reject) => {
      const id = ++this.sequence;
      const timer = setTimeout(() => this.fail(failure(`native ${method} request timed out`)), REQUEST_TIMEOUT);
      this.pending.set(id, { method, timer, resolve, reject });
      this.child.stdin.write(`${JSON.stringify({ id, method, params })}\n`);
    });
  }

  async initialize() {
    await this.request('initialize', { clientInfo: { name: 'jev_compatibility_probe', version: '1' }, capabilities: { experimentalApi: true } });
    this.child.stdin.write('{"method":"initialized"}\n');
    const models = new Set();
    const cursors = new Set();
    let cursor;
    do {
      const page = await this.bridge.handle('model/list', { includeHidden: true, ...(cursor ? { cursor } : {}) });
      requireContract(Array.isArray(page.data), 'native model list protocol changed');
      for (const entry of page.data) models.add(entry.model);
      cursor = page.nextCursor;
      requireContract(cursor == null || (typeof cursor === 'string' && !cursors.has(cursor) && cursors.size < 32),
        'native model list pagination did not terminate');
      cursors.add(cursor);
    } while (cursor != null);
    requireContract([CARRIER, 'jev/auto', 'jev/manual'].every((model) => models.has(model)),
      'native model list does not expose the carrier and Jev selections');
  }

  waitNotice(method, threadId, after) {
    if (this.error) return Promise.reject(this.error);
    const matches = (notice) => notice.sequence > after && notice.raw.method === method && notice.raw.params?.threadId === threadId;
    const observed = this.notices.find(matches);
    if (observed) return Promise.resolve(observed);
    return new Promise((resolve, reject) => {
      const waiter = { matches, resolve, reject };
      waiter.timer = setTimeout(() => this.fail(failure(`native ${method} notification timed out`)), REQUEST_TIMEOUT);
      this.waiters.add(waiter);
    });
  }

  async close() {
    if (this.closed) return;
    this.closing = true;
    for (const entry of this.pending.values()) clearTimeout(entry.timer);
    for (const entry of this.waiters) clearTimeout(entry.timer);
    this.child.stdin.destroy();
    let cleanupError;
    try { this.terminateGroup('SIGTERM'); }
    catch (error) { cleanupError = error; }
    const timer = setTimeout(() => {
      try { this.terminateGroup('SIGKILL'); }
      catch (error) { cleanupError ??= error; }
    }, 1000);
    let exitTimer;
    try {
      await Promise.race([this.exited, new Promise((resolve) => { exitTimer = setTimeout(resolve, 2000); })]);
      if (this.child.pid && this.child.exitCode == null && this.child.signalCode == null) {
        cleanupError ??= new Error('Private native process did not exit after termination');
      }
    }
    finally {
      clearTimeout(timer);
      clearTimeout(exitTimer);
      try { this.terminateGroup('SIGKILL'); }
      catch (error) { cleanupError ??= error; }
      this.closed = true;
    }
    if (cleanupError) throw cleanupError;
  }

  terminateGroup(signal) {
    if (!this.child.pid) return;
    if (process.platform === 'win32') { this.child.kill(signal); return; }
    try { process.kill(-this.child.pid, signal); }
    catch (error) { if (error.code !== 'ESRCH') throw error; }
  }
}

function verifyPermissions(result) {
  requireSafety(result.sandbox?.type === 'readOnly' && result.approvalPolicy === 'never'
    && result.activePermissionProfile?.id === ':read-only', 'read-only permissions were not preserved');
}

async function settings(session, threadId, mode, effort) {
  const before = session.noticeSequence;
  await session.bridge.handle('thread/settings/update', { threadId, effort });
  const notice = await session.waitNotice('thread/settings/updated', threadId, before);
  const raw = notice.raw.params.threadSettings;
  const mapped = notice.public?.params?.threadSettings;
  requireContract(raw?.model === CARRIER && mapped?.model === `jev/${mode}` && mapped.effort === effort
    && mapped.collaborationMode?.settings?.model === `jev/${mode}` && mapped.modelProvider === `jev-router-${mode}`,
  'nested settings notification lost Jev identity or effort');
  requireSafety(raw.sandboxPolicy?.type === 'readOnly' && isDeepStrictEqual(mapped.sandboxPolicy, raw.sandboxPolicy),
    'nested settings notification changed read-only permissions');
}

async function turn(session, threadId, mode, effort, useCollaboration = true) {
  const context = session.context;
  const marker = `JEV_CONTRACT_INPUT_${context.httpRequests + 1}`;
  const previous = context.history.get(threadId) ?? [];
  const collaborationMarker = useCollaboration && effort === 'xhigh' ? `JEV_COLLABORATION_${context.httpRequests + 1}` : null;
  context.expected = { mode, effort, markers: [...previous, marker], collaborationMarker, received: false };
  const before = session.noticeSequence;
  const params = { threadId, input: [{ type: 'text', text: `${marker}. Synthetic compatibility check. Do not call tools.`, text_elements: [] }] };
  if (useCollaboration) params.collaborationMode = { mode: effort === 'xhigh' ? 'plan' : 'default',
    settings: { model: `jev/${mode}`, reasoning_effort: effort, developer_instructions: collaborationMarker } };
  await session.bridge.handle('turn/start', params);
  const notice = await session.waitNotice('turn/completed', threadId, before);
  requireContract(notice.raw.params.turn?.status === 'completed' && context.expected.received,
    'synthetic turn did not complete through the loopback provider');
  if (context.error) throw context.error;
  context.history.set(threadId, [...previous, marker]);
  context.expected = null;
}

async function recoveryTurn(session, threadId, mode) {
  const context = session.context;
  const before = session.noticeSequence;
  context.recovery = { threadId, mode, requests: 0 };
  try {
    await session.request('turn/start', { threadId,
      input: [{ type: 'text', text: 'Synthetic recovery guard check. Do not call tools.', text_elements: [] }] });
    const notice = await session.waitNotice('turn/completed', threadId, before);
    requireSafety(notice.raw.params.turn?.status === 'failed' && context.recovery.requests > 0
      && context.recoveryModelOutputs === 0, 'bare native recovery did not stop after the HTTP refusal');
    if (context.error) throw context.error;
  } finally { context.recovery = null; }
}

async function exercise(context) {
  const connect = async () => {
    if (context.error) throw context.error;
    const session = new NativeSession(context);
    context.session = session;
    await session.initialize();
    return session;
  };
  let session = await connect();
  context.checks.push('initialize-model-list');
  let autoThread;
  const threads = [];
  for (const mode of ['manual', 'auto']) {
    const started = await session.bridge.handle('thread/start', { model: `jev/${mode}`, cwd: context.directory,
      permissions: ':read-only', approvalPolicy: 'never', config: { model_reasoning_effort: 'medium' } });
    requireContract(started.model === `jev/${mode}` && started.modelProvider === `jev-router-${mode}`, 'thread start lost Jev identity');
    verifyPermissions(started);
    const threadId = started.thread.id;
    threads.push({ threadId, mode });
    for (const effort of mode === 'manual' ? EFFORTS : ['low', 'high']) {
      await settings(session, threadId, mode, effort);
      await turn(session, threadId, mode, effort);
    }
    if (mode === 'auto') autoThread = threadId;
  }
  context.checks.push('manual-efforts', 'auto-routing', 'nested-settings', 'canonical-input-tools', 'collaboration-mode', 'read-only-permissions');
  await session.close();
  session = await connect();
  const previousRequests = context.httpRequests;
  for (const { threadId, mode } of threads) {
    const bare = await session.request('thread/resume', { threadId });
    requireContract(bare.model === CARRIER && bare.modelProvider === `jev-router-${mode}`, 'bare native could not reopen a persisted Jev thread');
    verifyPermissions(bare);
  }
  requireSafety(context.httpRequests === previousRequests, 'bare native recovery resume sent an inference request');
  context.checks.push('bare-native-recovery-resume');
  for (const { threadId, mode } of threads) await recoveryTurn(session, threadId, mode);
  context.checks.push('bare-native-recovery-http-guard');
  context.checks.push('recovery-registry-native-deep-merge');
  await session.close();
  session = await connect();
  const resumed = await session.bridge.handle('thread/resume', { threadId: autoThread });
  requireContract(resumed.model === 'jev/auto' && resumed.modelProvider === 'jev-router-auto' && resumed.reasoningEffort === 'high',
    'persisted thread lost Jev identity or effort after restart');
  verifyPermissions(resumed);
  await turn(session, autoThread, 'auto', 'high', false);
  context.checks.push('restart-resume');
  await session.bridge.handle('thread/settings/update', { threadId: autoThread, model: CARRIER, effort: 'high' });
  await session.close();
  session = await connect();
  const official = await session.bridge.handle('thread/resume', { threadId: autoThread });
  requireContract(official.model === CARRIER && official.modelProvider === 'openai', 'official provider was not restored');
  verifyPermissions(official);
  context.checks.push('official-provider-restored');
  requireContract(context.windowCount >= context.httpRequests && context.minimumContextWindow >= MIN_CONTEXT,
    'native context pressure contract changed');
  requireSafety(context.compactions === 0, 'native context pressure caused automatic compaction');
  context.checks.push('context-pressure');
}

/** Qualify a signed native executable using only private synthetic local state. */
export async function probeDesktopContract(nativeBinary) {
  const directory = await realpath(await mkdtemp(join(tmpdir(), 'jev-desktop-contract-')));
  const context = { binary: nativeBinary, directory, checks: [], httpRequests: 0, compactions: 0,
    windowCount: 0, minimumContextWindow: Infinity, history: new Map(), recoveryDeniedRequests: 0,
    recoveryCompactRequests: 0, recoveryCompactionAttempts: 0, recoveryModelOutputs: 0 };
  // Do not inherit credentials, proxy overrides, plugins, or caller-controlled native flags.
  context.env = { PATH: '/usr/bin:/bin:/usr/sbin:/sbin', HOME: directory, CODEX_HOME: directory, TMPDIR: directory, LANG: 'C', LC_ALL: 'C' };
  context.fail = (error) => { context.error ??= error; context.session?.fail(context.error); };
  // Desktop's startup config read has a hard 30-second budget; leave room for
  // signature verification, artifact hashes, cleanup, and native initialization.
  const deadline = setTimeout(() => context.fail(failure('qualification exceeded the overall time limit')), 18000);
  try {
    const nativeVersion = await bundledMetadata(context);
    context.checks.push('bundled-carrier-metadata');
    await startResponder(context);
    await exercise(context);
    requireSafety(await readFile(join(directory, 'config.toml'), 'utf8') === context.config
      && await readFile(join(directory, 'official-models.json'), 'utf8') === context.catalogData, 'qualification changed the official local configuration');
    if (context.error) throw context.error;
    return { nativeVersion, checks: context.checks, httpRequests: context.httpRequests, compactions: context.compactions,
      minimumContextWindow: context.minimumContextWindow, recoveryDeniedRequests: context.recoveryDeniedRequests,
      recoveryCompactRequests: context.recoveryCompactRequests, recoveryCompactionAttempts: context.recoveryCompactionAttempts,
      recoveryModelOutputs: context.recoveryModelOutputs };
  } finally {
    clearTimeout(deadline);
    let cleanupError;
    try { await context.session?.close(); }
    catch (error) { cleanupError = error; }
    if (context.server) {
      try {
        context.server.closeAllConnections();
        await new Promise((resolve) => context.server.close(resolve));
      } catch (error) { cleanupError ??= error; }
    }
    try { await rm(directory, { recursive: true, force: true }); }
    catch (error) { cleanupError ??= error; }
    if (cleanupError) throw cleanupError;
  }
}
