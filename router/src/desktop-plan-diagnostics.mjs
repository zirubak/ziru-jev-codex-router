import { createHash } from 'node:crypto';
import { closeSync, constants, fstatSync, lstatSync, openSync, writeSync } from 'node:fs';
import { join } from 'node:path';

const METHODS = new Set(['thread/start', 'thread/resume', 'thread/read', 'thread/settings/update', 'thread/settings/updated', 'turn/start']);
const EVENTS = new Set(['client_request', 'native_request', 'native_reply', 'native_error', 'native_notification', 'public_notification']);
const MODELS = new Set(['jev/auto', 'jev/manual', 'gpt-6.1-sol']);
const EFFORTS = new Set(['low', 'medium', 'high', 'xhigh', 'max', 'ultra']);
const LIMIT = 1024 * 1024;
const safeValue = (value, allowed) => value == null ? null : allowed.has(value) ? value : 'other';
function privateFile(info) {
  if (!info.isFile() || info.uid !== process.getuid() || (info.mode & 0o077)) throw new Error('Unsafe diagnostics file');
}

/** Opt-in local metadata only; diagnostics must never change routing behavior. */
export function createPlanDiagnostics(directory, warn = text => process.stderr.write(text)) {
  let warned = false;
  return (event, method, params = {}) => {
    if (!EVENTS.has(event) || !METHODS.has(method)) return;
    let fd;
    try {
      let flag;
      try { flag = lstatSync(join(directory, 'plan-diagnostics.enabled')); }
      catch (error) { if (error.code === 'ENOENT') return; throw error; }
      privateFile(flag);
      const settings = params.threadSettings ?? params;
      const collaboration = settings.collaborationMode;
      const threadId = params.threadId ?? params.thread?.id;
      const row = { time: new Date().toISOString(), event, method,
        threadHash: typeof threadId === 'string' ? createHash('sha256').update(threadId).digest('hex') : null,
        model: safeValue(settings.model ?? collaboration?.settings?.model, MODELS),
        effort: safeValue(settings.effort ?? settings.reasoningEffort ?? collaboration?.settings?.reasoning_effort, EFFORTS),
        mode: safeValue(collaboration?.mode, new Set(['plan', 'default'])),
        errorCode: Number.isSafeInteger(params.errorCode) ? params.errorCode : null };
      fd = openSync(join(directory, 'plan-diagnostics.jsonl'), constants.O_WRONLY | constants.O_APPEND | constants.O_CREAT | constants.O_NOFOLLOW, 0o600);
      const info = fstatSync(fd);
      privateFile(info);
      const data = `${JSON.stringify(row)}\n`;
      if (info.size + Buffer.byteLength(data) > LIMIT) throw new Error('Diagnostics size limit');
      writeSync(fd, data);
    } catch {
      if (!warned) { warned = true; warn('Jev Plan diagnostics could not record safely or reached its 1 MiB limit; routing was preserved.\n'); }
    } finally { if (fd !== undefined) closeSync(fd); }
  };
}
