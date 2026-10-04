import { randomUUID } from 'node:crypto';
import { createInterface } from 'node:readline';
import { isDeepStrictEqual } from 'node:util';
import { MemoryRouteState, validateRouteRecord } from './desktop-provider-state.mjs';

const JEV_PROVIDER = 'jev-router';
const CARRIER = 'gpt-6.1-sol';
const modeOf = (model) => model === 'jev/auto' ? 'auto' : model === 'jev/manual' ? 'manual' : null;
const providerMode = (provider) => provider === 'jev-router-auto' ? 'auto' : provider === 'jev-router-manual' ? 'manual' : null;
const controlled = (provider) => provider === JEV_PROVIDER || providerMode(provider) != null;
const providerFor = (model, previous) => modeOf(model) ? `jev-router-${modeOf(model)}` : controlled(previous) ? 'openai' : previous;
const nativeModel = (model, provider) => providerMode(provider) ? CARRIER : model;
const EFFORTS = ['low', 'medium', 'high', 'xhigh', 'max'];
const isJev = (model) => model === 'jev/auto' || model === 'jev/manual';

export class JevBridgeError extends Error {
  constructor(code, message, data) {
    super(message);
    this.code = code;
    this.data = data;
  }
}

function refuse(message) {
  throw new JevBridgeError(-32000, `Jev provider switch: ${message}`);
}

function modelEntries() {
  return ['auto', 'manual'].map((mode) => ({
    id: `jev/${mode}`, model: `jev/${mode}`,
    displayName: `Jev Codex Router ${mode === 'auto' ? 'Auto' : 'Manual'}`,
    description: mode === 'auto'
      ? 'Jev chooses the model and reasoning effort; the selected effort is ignored.'
      : 'Jev chooses the model and preserves your selected reasoning effort.',
    hidden: false, isDefault: false,
    defaultReasoningEffort: mode === 'auto' ? 'high' : 'medium',
    supportedReasoningEfforts: EFFORTS.map((reasoningEffort) => ({ reasoningEffort, description: reasoningEffort })),
    inputModalities: ['text', 'image'], supportsPersonality: false,
  }));
}

function selection(params, fallback = {}) {
  const settings = params.collaborationMode?.settings;
  const model = settings?.model ?? params.model ?? fallback.model;
  let effort = settings?.reasoning_effort ?? params.effort ?? params.config?.model_reasoning_effort ?? (model === fallback.model ? fallback.reasoningEffort : undefined);
  if (isJev(model)) {
    effort ??= model === 'jev/manual' ? 'medium' : 'high';
    if (!EFFORTS.includes(effort)) refuse('unsupported reasoning effort; choose low, medium, high, xhigh, or max.');
  }
  return { model, effort };
}

/** Keep provider changes scoped to one native thread, never the default config. */
export class DesktopProviderBridge {
  constructor({ request, provider, state = new MemoryRouteState() }) {
    this.request = request;
    this.provider = provider;
    this.state = state;
    this.routes = new Map();
    this.rebinding = new Set();
    this.statuses = new Map();
    this.blocked = new Set();
    this.carrierAvailable = false;
  }

  async hasCarrier() {
    if (this.carrierAvailable) return true;
    const seen = new Set();
    let cursor;
    do {
      const result = await this.request('model/list', { includeHidden: true, ...(cursor ? { cursor } : {}) });
      if (result.data?.some((entry) => entry.model === CARRIER)) {
        this.carrierAvailable = true;
        return true;
      }
      cursor = result.nextCursor;
      if (cursor == null || seen.has(cursor)) return false;
      seen.add(cursor);
    } while (true);
  }

  async requireCarrier(model) {
    if (isJev(model) && !await this.hasCarrier()) refuse('native carrier metadata is unavailable; refresh official models before selecting Jev.');
  }

  remember(result) {
    if (result?.thread?.id && result.modelProvider && result.model) {
      this.routes.set(result.thread.id, {
        ...result, thread: undefined,
        model: providerMode(result.modelProvider) ? `jev/${providerMode(result.modelProvider)}` : result.model, modelProvider: result.modelProvider,
      });
    }
    return result;
  }

  record(threadId) {
    try { return this.state.read(threadId); }
    catch { refuse('private route state cannot be verified; no turn was sent.'); }
  }

  save(threadId, model, effort, phase, previous = this.record(threadId)) {
    const route = { mode: modeOf(model) ?? 'official', model, effort: effort ?? null, phase };
    // Reject proposed metadata before storage or native mutation. A rejected
    // selection leaves the confirmed route intact and does not poison retries.
    try {
      validateRouteRecord({ ...route, version: 1, threadId, revision: (previous?.revision ?? 0) + 1 });
    } catch {
      refuse('invalid route selection; no settings or turn were sent.');
    }
    try {
      return this.state.write(threadId, route, previous?.revision ?? null);
    } catch {
      this.blocked.add(threadId);
      refuse('private route state could not be saved; reopen or start a new chat before sending.');
    }
  }

  publicThread(thread) {
    if (!thread?.id) return thread;
    let record;
    try { record = this.record(thread.id); }
    catch { this.blocked.add(thread.id); return thread; }
    if (record?.phase === 'confirmed') return { ...thread, model: record.model, modelProvider: providerFor(record.model, 'openai') };
    const mode = providerMode(thread.modelProvider);
    return mode && thread.model === CARRIER ? { ...thread, model: `jev/${mode}` } : thread;
  }

  publicResult(result) {
    if (!result || typeof result !== 'object') return result;
    let mapped = { ...result };
    const mode = providerMode(result.modelProvider);
    if (mode && result.model === CARRIER) mapped.model = `jev/${mode}`;
    if (mode && result.collaborationMode?.settings?.model === CARRIER) {
      mapped.collaborationMode = { ...result.collaborationMode, settings: { ...result.collaborationMode.settings, model: `jev/${mode}` } };
    }
    if (result.thread) mapped.thread = this.publicThread(result.thread);
    if (Array.isArray(result.data) && result.data.some((item) => item?.modelProvider)) mapped.data = result.data.map((item) => this.publicThread(item));
    return mapped;
  }

  notification(message) {
    const id = message.params?.threadId ?? message.params?.thread?.id;
    if (message.method === 'thread/status/changed') this.statuses.set(id, message.params.status);
    if (this.rebinding.has(id) && ['thread/closed', 'thread/started', 'thread/status/changed'].includes(message.method)) return null;
    if (message.params?.thread) return { ...message, params: { ...message.params, thread: this.publicThread(message.params.thread) } };
    let mode;
    if (id && message.method === 'thread/settings/updated') {
      try { mode = modeOf(this.record(id)?.model); }
      catch { this.blocked.add(id); return message; }
    }
    if (mode && message.method === 'thread/settings/updated') {
      const params = this.virtualSettings(message.params, `jev/${mode}`);
      // Desktop takes its current model and the next turn's collaboration
      // settings from this nested native notification, not the outer envelope.
      if (params.threadSettings) params.threadSettings = this.virtualSettings(params.threadSettings, `jev/${mode}`);
      return { ...message, params };
    }
    return message;
  }

  virtualSettings(params, model) {
    const mapped = { ...params };
    if (mapped.model === CARRIER) mapped.model = model;
    if (mapped.collaborationMode?.settings?.model === CARRIER) {
      mapped.collaborationMode = { ...mapped.collaborationMode, settings: { ...mapped.collaborationMode.settings, model } };
    }
    return mapped;
  }

  nativeSettings(params, model, effort) {
    const mapped = { ...params, model: isJev(model) ? CARRIER : model, effort };
    if (mapped.collaborationMode?.settings && isJev(mapped.collaborationMode.settings.model)) {
      mapped.collaborationMode = { ...mapped.collaborationMode, settings: { ...mapped.collaborationMode.settings, model: CARRIER } };
    }
    return mapped;
  }

  scoped(params, model, effort, providerId) {
    const config = { ...params.config };
    if (effort != null) config.model_reasoning_effort = effort;
    const mode = providerMode(providerId);
    if (mode || providerId === JEV_PROVIDER) {
      // Native config deep-merges header maps: explicitly override the recovery
      // marker instead of relying on an omitted key to delete the base value.
      const definition = mode ? { ...this.provider, http_headers: { ...this.provider.http_headers,
        'x-jev-selection-mode': mode, 'x-jev-desktop-recovery': 'bridge-active' } } : this.provider;
      config.model_providers = { ...config.model_providers, [providerId]: definition };
    }
    if (mode) {
      config.model_context_window = 872000;
      config.model_auto_compact_token_limit = 740000;
    }
    return { ...params, model: nativeModel(model, providerId), modelProvider: providerId, config };
  }

  verify(result, model, providerId) {
    if (result.modelProvider !== providerId || result.model !== nativeModel(model, providerId)) {
      refuse('native Codex did not confirm the requested model and provider; no turn was sent.');
    }
    return this.remember(result);
  }

  checkCachedRoute(threadId, record) {
    const known = this.routes.get(threadId);
    if (known && record && (known.model !== record.model
        || known.modelProvider !== providerFor(record.model, 'openai')
        || (record.effort != null && known.reasoningEffort !== record.effort))) {
      refuse('private route selection changed in another instance; reopen the chat before sending.');
    }
  }

  async current(threadId) {
    const record = this.record(threadId);
    if (record?.phase === 'pending' || this.blocked.has(threadId)) refuse('route is unconfirmed; open a new chat before sending.');
    this.checkCachedRoute(threadId, record);
    const { thread } = await this.request('thread/read', { threadId, includeTurns: false });
    let route = this.routes.get(threadId);
    if (!route && record) {
      const expected = providerFor(record.model, 'openai');
      if (thread.status?.type !== 'notLoaded') {
        const live = await this.request('thread/resume', { threadId });
        if (live.modelProvider !== expected || live.model !== nativeModel(record.model, expected)) {
          this.save(threadId, record.model, record.effort, 'pending', record);
          refuse('loaded native route changed; saved selection is unconfirmed.');
        }
        this.remember(live);
        route = this.routes.get(threadId);
      } else route = { ...thread, model: record.model, reasoningEffort: record.effort, modelProvider: expected };
    }
    if (!route && providerMode(thread.modelProvider)) refuse('private route selection is missing; no turn was sent.');
    route ??= thread;
    return { thread, route, record };
  }

  async rebind(threadId, model, effort, current) {
    const { thread } = current;
    if (thread.status?.type !== 'idle' || this.statuses.get(threadId)?.type === 'active') {
      refuse('wait until this thread is idle before changing providers.');
    }
    if (!thread.path || thread.ephemeral) refuse('a persisted thread with history is required for changing providers.');
    // Read effective settings from the live session before unloading; the stored
    // Thread.modelProvider can describe its original provider after a switch.
    const old = this.remember(await this.request('thread/resume', { threadId }));
    const providerId = providerFor(model, old.modelProvider);
    if (old.modelProvider === providerId) return old;
    if (!old.activePermissionProfile?.id) refuse('permission profile cannot be preserved; select the model in a new chat.');
    const original = this.scoped({
      threadId, cwd: old.cwd, approvalPolicy: old.approvalPolicy,
      approvalsReviewer: old.approvalsReviewer, serviceTier: old.serviceTier,
      runtimeWorkspaceRoots: old.runtimeWorkspaceRoots,
      ...(old.activePermissionProfile?.id ? { permissions: old.activePermissionProfile.id } : {}),
    }, providerMode(old.modelProvider) ? `jev/${providerMode(old.modelProvider)}` : old.model, old.reasoningEffort, old.modelProvider);
    const previousRecord = current.record;
    let pending = this.save(threadId, model, effort, 'pending', previousRecord);
    this.rebinding.add(threadId);
    try {
      const status = await this.request('thread/unsubscribe', { threadId });
      if (status.status !== 'unsubscribed') refuse('native thread could not be exclusively unloaded.');
      try {
        const result = await this.request('thread/resume', this.scoped({ ...original, config: undefined }, model, effort, providerId));
        this.verify(result, model, providerId);
        for (const key of ['sandbox', 'approvalPolicy', 'approvalsReviewer', 'activePermissionProfile', 'runtimeWorkspaceRoots']) {
          if (!isDeepStrictEqual(result[key], old[key])) refuse('effective permissions changed during rebind; no turn was sent.');
        }
        this.save(threadId, model, effort, 'confirmed', pending);
        return result;
      } catch (error) {
        // A remaining subscriber can keep a thread loaded. Never acknowledge a
        // selection based on stale nested metadata; restore the original route.
        try {
          let restored = await this.request('thread/resume', original);
          if (restored.modelProvider !== old.modelProvider || restored.model !== old.model) {
            const unloaded = await this.request('thread/unsubscribe', { threadId });
            if (unloaded.status !== 'unsubscribed') refuse('original route could not be restored.');
            restored = await this.request('thread/resume', original);
          }
          this.verify(restored, providerMode(old.modelProvider) ? `jev/${providerMode(old.modelProvider)}` : old.model, old.modelProvider);
          for (const key of ['sandbox', 'approvalPolicy', 'approvalsReviewer', 'activePermissionProfile', 'runtimeWorkspaceRoots']) {
            if (!isDeepStrictEqual(restored[key], old[key])) refuse('original permissions could not be restored.');
          }
        } catch {
          this.blocked.add(threadId);
          refuse('rebind failed and the prior route could not be confirmed; open a new chat before sending.');
        }
        this.save(threadId, current.route.model, old.reasoningEffort, 'confirmed', pending);
        refuse(`rebind failed; the original route was restored (${error.code ?? 'native error'}).`);
      }
    } finally {
      this.rebinding.delete(threadId);
    }
  }

  async ensureRoute(params) {
    if (this.blocked.has(params.threadId) || this.record(params.threadId)?.phase === 'pending') refuse('route is unconfirmed; open a new chat before sending.');
    this.checkCachedRoute(params.threadId, this.record(params.threadId));
    const known = this.routes.get(params.threadId);
    const proposed = selection(params, known);
    if (known && !controlled(known.modelProvider) && !isJev(proposed.model)) return proposed;
    const current = await this.current(params.threadId);
    const { model, effort } = selection(params, current.route);
    await this.requireCarrier(model);
    const expected = providerFor(model, current.route.modelProvider);
    if (expected !== current.route.modelProvider) await this.rebind(params.threadId, model, effort, current);
    return { model, effort };
  }

  async defaults(method, params) {
    const edits = method === 'config/value/write'
      ? [{ keyPath: params.keyPath, value: params.value, mergeStrategy: params.mergeStrategy }]
      : params.edits;
    if (!Array.isArray(edits)) return this.request(method, params);
    const jevModel = edits.find((edit) => edit.keyPath === 'model' && isJev(edit.value));
    const filtered = edits.filter((edit) => !(edit.keyPath === 'model' && isJev(edit.value))
      && !(edit.keyPath === 'model_reasoning_effort' && (jevModel || edit.value === 'auto')));
    if (filtered.length === edits.length) return this.request(method, params);
    const { keyPath, value, mergeStrategy, ...batch } = params;
    // Even an empty native transaction checks expectedVersion and returns the
    // real canonical path/version. Unrelated edits retain native semantics.
    const result = await this.request('config/batchWrite', { ...batch, edits: filtered });
    return {
      ...result, status: 'okOverridden',
      overriddenMetadata: {
        effectiveValue: jevModel?.value ?? 'high',
        message: 'Jev selection is local to this Desktop chat; official Codex defaults were preserved.',
        overridingLayer: { name: { type: 'sessionFlags' }, version: result.version },
      },
    };
  }

  async handle(method, params = {}) {
    if (method === 'model/list') {
      const result = await this.request(method, params);
      if (result.data?.some((entry) => entry.model === CARRIER)) this.carrierAvailable = true;
      if (result.nextCursor != null || !Array.isArray(result.data) || !await this.hasCarrier()) return result;
      return { ...result, data: [...result.data.filter((model) => !isJev(model.model)), ...modelEntries()] };
    }
    if (method === 'config/batchWrite' || method === 'config/value/write') return this.defaults(method, params);
    if (method === 'thread/start' || method === 'thread/fork') {
      let fallback = {};
      if (method === 'thread/fork') fallback = (await this.current(params.threadId)).route;
      const { model, effort } = selection(params, fallback);
      await this.requireCarrier(model);
      const providerId = providerFor(model, params.modelProvider ?? fallback.modelProvider);
      const scoped = providerId ? this.scoped(params, model, effort, providerId) : params;
      const result = await this.request(method, scoped);
      if (isJev(model)) {
        this.verify(result, model, providerId);
        this.save(result.thread.id, model, effort, 'confirmed');
      } else this.remember(result);
      return this.publicResult(result);
    }
    if (method === 'thread/resume') {
      if (!params.threadId) {
        const { model, effort } = selection(params);
        await this.requireCarrier(model);
        const providerId = providerFor(model, params.modelProvider);
        const result = await this.request(method, isJev(model) ? this.scoped(params, model, effort, providerId) : params);
        if (isJev(model)) { this.verify(result, model, providerId); this.save(result.thread.id, model, effort, 'confirmed'); }
        else this.remember(result);
        return this.publicResult(result);
      }
      const current = await this.current(params.threadId);
      const { model, effort } = selection(params, current.route);
      await this.requireCarrier(model);
      const providerId = providerFor(model, current.route.modelProvider);
      if (current.thread.status?.type !== 'notLoaded' && providerId !== current.route.modelProvider) {
        await this.rebind(params.threadId, model, effort, current);
      }
      const scoped = isJev(model) || controlled(current.route.modelProvider)
        ? this.scoped(params, model, effort, providerId) : params;
      const record = this.record(params.threadId);
      if (current.thread.status?.type === 'notLoaded' && (isJev(model) || record)
          && (record?.model !== model || record?.effort !== (effort ?? null))) {
        this.save(params.threadId, model, effort, 'pending', record);
      }
      const result = await this.request(method, scoped);
      if (isJev(model) || current.record || controlled(current.route.modelProvider)) {
        this.verify(result, model, providerId);
        this.save(params.threadId, model, effort, 'confirmed');
      } else this.remember(result);
      return this.publicResult(result);
    }
    if (method === 'thread/settings/update' || method === 'turn/start') {
      const { model, effort } = await this.ensureRoute(params);
      const record = this.record(params.threadId);
      const changed = (isJev(model) || record) && (record?.model !== model || record?.effort !== (effort ?? null));
      const pending = changed ? this.save(params.threadId, model, effort, 'pending', record) : null;
      const selected = isJev(model) ? this.nativeSettings(params, model, effort) : params;
      const result = await this.request(method, selected);
      const prior = this.routes.get(params.threadId);
      if (prior) this.routes.set(params.threadId, { ...prior, model, reasoningEffort: effort });
      if (pending) this.save(params.threadId, model, effort, 'confirmed', pending);
      return this.publicResult(result);
    }
    return this.publicResult(await this.request(method, params));
  }
}

/** Bidirectional JSON-RPC relay with independent IDs for native callbacks. */
export function connectDesktopBridge({ input, output, child, provider, state }) {
  const pending = new Map();
  const callbacks = new Map();
  const serial = new Map();
  const prefix = `jev-${randomUUID()}`;
  let counter = 0;
  const send = (stream, message) => stream.write(`${JSON.stringify(message)}\n`);
  const request = (method, params) => new Promise((resolve, reject) => {
    const id = `${prefix}-${++counter}`;
    pending.set(id, { resolve, reject });
    send(child.stdin, { id, method, params });
  });
  const bridge = new DesktopProviderBridge({ request, provider, state });
  const nativeLines = createInterface({ input: child.stdout });
  const clientLines = createInterface({ input });
  nativeLines.on('line', (line) => {
    let message;
    try { message = JSON.parse(line); } catch { output.write(`${line}\n`); return; }
    if (message.method && message.id != null) {
      const id = `${prefix}-callback-${++counter}`;
      callbacks.set(id, message.id);
      send(output, { ...message, id });
    } else if (message.id != null && pending.has(message.id)) {
      const entry = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) entry.reject(new JevBridgeError(message.error.code, message.error.message, message.error.data));
      else entry.resolve(message.result);
    } else {
      const forwarded = bridge.notification(message);
      if (forwarded) send(output, forwarded);
    }
  });
  clientLines.on('line', (line) => {
    let message;
    try { message = JSON.parse(line); } catch { child.stdin.write(`${line}\n`); return; }
    if (!message.method) {
      const id = callbacks.get(message.id);
      if (id != null) { callbacks.delete(message.id); send(child.stdin, { ...message, id }); }
      else send(child.stdin, message);
      return;
    }
    if (message.id == null) { send(child.stdin, message); return; }
    const run = async () => {
      try { send(output, { id: message.id, result: await bridge.handle(message.method, message.params) }); }
      catch (error) {
        send(output, { id: message.id, error: { code: error.code ?? -32000, message: error instanceof JevBridgeError ? error.message : 'Jev Desktop bridge request failed.', ...(error.data === undefined ? {} : { data: error.data }) } });
      }
    };
    // Replies to native tool/auth callbacks bypass these queues, so an approval
    // can complete while a thread mutation is waiting for its native response.
    const key = message.params?.threadId ?? (message.method.startsWith('config/') ? 'config' : null);
    if (key) {
      const task = (serial.get(key) ?? Promise.resolve()).then(run);
      serial.set(key, task);
      task.finally(() => { if (serial.get(key) === task) serial.delete(key); });
    } else void run();
  });
  clientLines.on('close', () => child.stdin.end());
  child.on('exit', () => {
    for (const entry of pending.values()) entry.reject(new JevBridgeError(-32000, 'Native Codex process exited.'));
    pending.clear();
    clientLines.close();
    nativeLines.close();
  });
  return bridge;
}
