import { randomUUID } from 'node:crypto';
import { createInterface } from 'node:readline';
import { isDeepStrictEqual } from 'node:util';

const JEV_PROVIDER = 'jev-router';
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
  constructor({ request, provider }) {
    this.request = request;
    this.provider = provider;
    this.routes = new Map();
    this.rebinding = new Set();
    this.statuses = new Map();
    this.blocked = new Set();
  }

  remember(result) {
    if (result?.thread?.id && result.modelProvider && result.model) {
      this.routes.set(result.thread.id, {
        ...result, thread: undefined,
        model: result.model, modelProvider: result.modelProvider,
      });
    }
    return result;
  }

  notification(message) {
    const id = message.params?.threadId ?? message.params?.thread?.id;
    if (message.method === 'thread/status/changed') this.statuses.set(id, message.params.status);
    // Native unloading is an implementation detail of a provider switch. Do not
    // remove the user's chat from the UI while the same thread is being rebound.
    return !(this.rebinding.has(id) && ['thread/closed', 'thread/started', 'thread/status/changed'].includes(message.method));
  }

  scoped(params, model, effort, providerId) {
    const config = { ...params.config };
    if (effort != null) config.model_reasoning_effort = effort;
    if (providerId === JEV_PROVIDER) {
      config.model_providers = { ...config.model_providers, [JEV_PROVIDER]: this.provider };
    }
    return { ...params, model, modelProvider: providerId, config };
  }

  verify(result, model, providerId) {
    if (result.modelProvider !== providerId || result.model !== model) {
      refuse('native Codex did not confirm the requested model and provider; no turn was sent.');
    }
    return this.remember(result);
  }

  async current(threadId) {
    const { thread } = await this.request('thread/read', { threadId, includeTurns: false });
    return { thread, route: this.routes.get(threadId) ?? thread };
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
    const providerId = isJev(model) ? JEV_PROVIDER : 'openai';
    if (old.modelProvider === providerId) return old;
    if (!old.activePermissionProfile?.id) refuse('permission profile cannot be preserved; select the model in a new chat.');
    const original = this.scoped({
      threadId, cwd: old.cwd, approvalPolicy: old.approvalPolicy,
      approvalsReviewer: old.approvalsReviewer, serviceTier: old.serviceTier,
      runtimeWorkspaceRoots: old.runtimeWorkspaceRoots,
      ...(old.activePermissionProfile?.id ? { permissions: old.activePermissionProfile.id } : {}),
    }, old.model, old.reasoningEffort, old.modelProvider);
    this.rebinding.add(threadId);
    try {
      const status = await this.request('thread/unsubscribe', { threadId });
      if (status.status !== 'unsubscribed') refuse('native thread could not be exclusively unloaded.');
      try {
        const result = await this.request('thread/resume', this.scoped(original, model, effort, providerId));
        this.verify(result, model, providerId);
        for (const key of ['sandbox', 'approvalPolicy', 'approvalsReviewer', 'activePermissionProfile', 'runtimeWorkspaceRoots']) {
          if (!isDeepStrictEqual(result[key], old[key])) refuse('effective permissions changed during rebind; no turn was sent.');
        }
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
          this.verify(restored, old.model, old.modelProvider);
          for (const key of ['sandbox', 'approvalPolicy', 'approvalsReviewer', 'activePermissionProfile', 'runtimeWorkspaceRoots']) {
            if (!isDeepStrictEqual(restored[key], old[key])) refuse('original permissions could not be restored.');
          }
        } catch {
          this.blocked.add(threadId);
          refuse('rebind failed and the prior route could not be confirmed; open a new chat before sending.');
        }
        refuse(`rebind failed; the original route was restored (${error.code ?? 'native error'}).`);
      }
    } finally {
      this.rebinding.delete(threadId);
    }
  }

  async ensureRoute(params) {
    if (this.blocked.has(params.threadId)) refuse('route is unconfirmed; open a new chat before sending.');
    const known = this.routes.get(params.threadId);
    const proposed = selection(params, known);
    if (known && known.modelProvider !== JEV_PROVIDER && !isJev(proposed.model)) return proposed;
    const current = await this.current(params.threadId);
    const { model, effort } = selection(params, current.route);
    const expected = isJev(model) ? JEV_PROVIDER : current.route.modelProvider === JEV_PROVIDER ? 'openai' : current.route.modelProvider;
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
      if (result.nextCursor != null || !Array.isArray(result.data)) return result;
      return { ...result, data: [...result.data.filter((model) => !isJev(model.model)), ...modelEntries()] };
    }
    if (method === 'config/batchWrite' || method === 'config/value/write') return this.defaults(method, params);
    if (method === 'thread/start' || method === 'thread/fork') {
      let fallback = {};
      if (method === 'thread/fork') fallback = (await this.current(params.threadId)).route;
      const { model, effort } = selection(params, fallback);
      const providerId = isJev(model) ? JEV_PROVIDER : (params.modelProvider ?? fallback.modelProvider) === JEV_PROVIDER ? 'openai' : params.modelProvider;
      const scoped = providerId ? this.scoped(params, model, effort, providerId) : params;
      const result = await this.request(method, scoped);
      return isJev(model) ? this.verify(result, model, JEV_PROVIDER) : this.remember(result);
    }
    if (method === 'thread/resume') {
      if (!params.threadId) {
        const { model, effort } = selection(params);
        const result = await this.request(method, isJev(model) ? this.scoped(params, model, effort, JEV_PROVIDER) : params);
        return isJev(model) ? this.verify(result, model, JEV_PROVIDER) : this.remember(result);
      }
      const current = await this.current(params.threadId);
      const { model, effort } = selection(params, current.route);
      const providerId = isJev(model) ? JEV_PROVIDER : current.route.modelProvider === JEV_PROVIDER ? 'openai' : current.route.modelProvider;
      if (current.thread.status?.type !== 'notLoaded' && providerId !== current.route.modelProvider) {
        await this.rebind(params.threadId, model, effort, current);
      }
      const scoped = isJev(model) || current.route.modelProvider === JEV_PROVIDER
        ? this.scoped(params, model, effort, providerId) : params;
      const result = await this.request(method, scoped);
      return isJev(model) || current.route.modelProvider === JEV_PROVIDER
        ? this.verify(result, model, providerId) : this.remember(result);
    }
    if (method === 'thread/settings/update' || method === 'turn/start') {
      const { model, effort } = await this.ensureRoute(params);
      const selected = isJev(model) ? { ...params, model, effort } : params;
      const result = await this.request(method, selected);
      const prior = this.routes.get(params.threadId);
      if (prior) this.routes.set(params.threadId, { ...prior, model, reasoningEffort: effort });
      return result;
    }
    return this.request(method, params);
  }
}

/** Bidirectional JSON-RPC relay with independent IDs for native callbacks. */
export function connectDesktopBridge({ input, output, child, provider }) {
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
  const bridge = new DesktopProviderBridge({ request, provider });
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
    } else if (bridge.notification(message)) send(output, message);
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
