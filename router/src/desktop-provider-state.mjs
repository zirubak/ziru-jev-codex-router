import { createHash, randomUUID } from 'node:crypto';
import { closeSync, constants, fsyncSync, fstatSync, lstatSync, mkdirSync, openSync, readFileSync, renameSync, unlinkSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const KEYS = ['effort', 'mode', 'model', 'phase', 'revision', 'threadId', 'version'];
const EFFORTS = ['low', 'medium', 'high', 'xhigh', 'max', null];
function privateFile(info, directory = false) {
  if (!(directory ? info.isDirectory() : info.isFile()) || info.uid !== process.getuid() || (info.mode & 0o077)) {
    throw new Error('Jev route state must be private and owner-only');
  }
}
export function validateRouteRecord(record) {
  if (!record || Object.keys(record).sort().join() !== KEYS.join()
      || record.version !== 1 || typeof record.threadId !== 'string' || !record.threadId
      || !Number.isSafeInteger(record.revision) || record.revision < 1
      || !['auto', 'manual', 'sol', 'astra', 'official'].includes(record.mode)
      || !['confirmed', 'pending'].includes(record.phase)
      || typeof record.model !== 'string' || !record.model
      // Official efforts belong to the native client, including client-level Ultra.
      || (record.mode === 'official'
        ? record.effort !== null && (typeof record.effort !== 'string' || !record.effort)
        : !EFFORTS.includes(record.effort))
      || (record.mode !== 'official' && record.model !== `jev/${record.mode}`)
      || (record.mode === 'official' && record.model.startsWith('jev/'))) {
    throw new Error('Invalid Jev route record');
  }
  if (Buffer.byteLength(JSON.stringify(record)) + 1 > 4096) throw new Error('Invalid Jev route record size');
  return record;
}

/** Per-thread route metadata only; never stores a prompt, tool result, or key. */
export class PrivateRouteState {
  constructor(directory, { create = true } = {}) {
    if (create) mkdirSync(directory, { mode: 0o700, recursive: true });
    privateFile(lstatSync(directory), true);
    this.directory = directory;
  }
  path(threadId) {
    if (typeof threadId !== 'string' || !threadId) throw new Error('Invalid Jev thread id');
    return join(this.directory, `${createHash('sha256').update(threadId).digest('hex')}.json`);
  }
  read(threadId) {
    privateFile(lstatSync(this.directory), true);
    let fd;
    try { fd = openSync(this.path(threadId), constants.O_RDONLY | constants.O_NOFOLLOW); }
    catch (error) { if (error.code === 'ENOENT') return null; throw error; }
    try {
      const info = fstatSync(fd);
      privateFile(info);
      if (info.size > 4096) throw new Error('Invalid Jev route record size');
      const record = validateRouteRecord(JSON.parse(readFileSync(fd, 'utf8')));
      if (record.threadId !== threadId) throw new Error('Invalid Jev route record identity');
      return record;
    } finally { closeSync(fd); }
  }
  write(threadId, route, expectedRevision) {
    const filename = this.path(threadId);
    const lock = `${filename}.lock`;
    privateFile(lstatSync(this.directory), true);
    const lockFd = openSync(lock, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o600);
    const temporary = `${filename}.${randomUUID()}.tmp`;
    try {
      const current = this.read(threadId);
      if ((current?.revision ?? null) !== expectedRevision) throw new Error('Jev route revision changed; reopen this chat');
      const record = validateRouteRecord({ ...route, version: 1, threadId, revision: (current?.revision ?? 0) + 1 });
      const fd = openSync(temporary, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o600);
      try { writeFileSync(fd, `${JSON.stringify(record)}\n`); fsyncSync(fd); } finally { closeSync(fd); }
      renameSync(temporary, filename);
      return record;
    } finally {
      closeSync(lockFd);
      unlinkSync(lock);
      try { unlinkSync(temporary); } catch (error) { if (error.code !== 'ENOENT') throw error; }
    }
  }
}

/** Explicit test-only substitute; the launcher always supplies private storage. */
export class MemoryRouteState {
  constructor() { this.records = new Map(); }
  read(threadId) { return this.records.get(threadId) ?? null; }
  write(threadId, route, expectedRevision) {
    const previous = this.read(threadId);
    if ((previous?.revision ?? null) !== expectedRevision) throw new Error('Jev route revision changed');
    const record = validateRouteRecord({ ...route, version: 1, threadId, revision: (previous?.revision ?? 0) + 1 });
    this.records.set(threadId, record);
    return record;
  }
}
