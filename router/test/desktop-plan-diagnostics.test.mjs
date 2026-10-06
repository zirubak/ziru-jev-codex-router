import assert from 'node:assert/strict';
import test from 'node:test';
import { chmodSync, mkdtempSync, readFileSync, symlinkSync, writeFileSync, existsSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { createPlanDiagnostics } from '../src/desktop-plan-diagnostics.mjs';
import { connectDesktopBridge } from '../src/desktop-provider-bridge.mjs';
import { EventEmitter } from 'node:events';
import { PassThrough } from 'node:stream';
import { createInterface } from 'node:readline';

function fixture(t) {
  const directory = mkdtempSync(join(tmpdir(), 'jev-plan-diagnostic-'));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  const warnings = [];
  return { directory, warnings, record: createPlanDiagnostics(directory, text => warnings.push(text)) };
}

test('Plan diagnostics default off and record only whitelisted settings metadata', t => {
  const { directory, record } = fixture(t);
  const params = { threadId: 'private-thread', model: 'jev/auto', effort: 'xhigh',
    collaborationMode: { mode: 'plan', settings: { model: 'jev/auto', developer_instructions: 'PRIVATE_PROMPT' } },
    input: [{ text: 'PRIVATE_PROMPT' }], authorization: 'PRIVATE_SECRET' };
  record('client_request', 'thread/settings/update', params);
  assert.equal(existsSync(join(directory, 'plan-diagnostics.jsonl')), false);
  writeFileSync(join(directory, 'plan-diagnostics.enabled'), '', { mode: 0o600 });
  record('client_request', 'thread/settings/update', params);
  record('native_notification', 'thread/settings/updated', { threadId: params.threadId, threadSettings: {
    model: 'gpt-6.1-sol', effort: 'xhigh', collaborationMode: { mode: 'default', settings: {} },
  } });
  const raw = readFileSync(join(directory, 'plan-diagnostics.jsonl'), 'utf8');
  assert.doesNotMatch(raw, /PRIVATE|private-thread|developer_instructions|authorization|input/);
  const rows = raw.trim().split('\n').map(line => JSON.parse(line));
  assert.equal(rows[0].mode, 'plan');
  assert.equal(rows[1].mode, 'default');
  assert.equal(rows[0].threadHash, rows[1].threadHash);
  assert.equal(rows[0].effort, 'xhigh');
  assert.equal(rows[0].model, 'jev/auto');
  record('client_request', 'thread/settings/update', { ...params, model: 'PRIVATE_MODEL', effort: 'PRIVATE_EFFORT' });
  assert.doesNotMatch(readFileSync(join(directory, 'plan-diagnostics.jsonl'), 'utf8'), /PRIVATE/);
});

test('Plan diagnostics refuse unsafe flags, linked logs and oversized logs', t => {
  const { directory, warnings, record } = fixture(t);
  const flag = join(directory, 'plan-diagnostics.enabled');
  const log = join(directory, 'plan-diagnostics.jsonl');
  writeFileSync(flag, '', { mode: 0o644 });
  record('client_request', 'thread/settings/update', {});
  assert.equal(existsSync(log), false);
  assert.ok(warnings.length > 0);
  chmodSync(flag, 0o600);
  const other = join(directory, 'other');
  writeFileSync(other, 'PRESERVED', { mode: 0o600 });
  symlinkSync(other, log);
  record('client_request', 'thread/settings/update', {});
  assert.equal(readFileSync(other, 'utf8'), 'PRESERVED');
  rmSync(log);
  writeFileSync(log, 'x'.repeat(1024 * 1024), { mode: 0o600 });
  record('client_request', 'thread/settings/update', {});
  assert.equal(readFileSync(log).length, 1024 * 1024);
});

test('Desktop relay records request, native reply and both notification boundaries', async t => {
  const { directory, record } = fixture(t);
  writeFileSync(join(directory, 'plan-diagnostics.enabled'), '', { mode: 0o600 });
  const input = new PassThrough();
  const output = new PassThrough();
  const child = new EventEmitter();
  child.stdin = new PassThrough();
  child.stdout = new PassThrough();
  const native = createInterface({ input: child.stdin });
  const client = createInterface({ input: output });
  t.after(() => { native.close(); client.close(); input.end(); child.emit('exit', 0); });
  native.on('line', line => {
    const request = JSON.parse(line);
    child.stdout.write(`${JSON.stringify({ method: 'thread/settings/updated', params: {
      threadId: 'fixture', threadSettings: { model: 'gpt-6.1-sol', collaborationMode: { mode: 'plan', settings: {} } },
    } })}\n`);
    child.stdout.write(`${JSON.stringify({ id: request.id, result: { thread: { id: 'fixture' } } })}\n`);
  });
  connectDesktopBridge({ input, output, child, provider: {}, diagnostics: record });
  const done = new Promise(resolve => client.on('line', line => { if (JSON.parse(line).id === 1) resolve(); }));
  input.write(`${JSON.stringify({ id: 1, method: 'thread/read', params: { threadId: 'fixture', includeTurns: false } })}\n`);
  await done;
  const rows = readFileSync(join(directory, 'plan-diagnostics.jsonl'), 'utf8').trim().split('\n').map(line => JSON.parse(line));
  assert.deepEqual(rows.map(row => row.event), ['client_request', 'native_request', 'native_notification', 'public_notification', 'native_reply']);
  assert.equal(rows[2].mode, 'plan');
  assert.equal(rows[3].mode, 'plan');
});

test('a failing diagnostic sink cannot interrupt native requests or notifications', async t => {
  const input = new PassThrough();
  const output = new PassThrough();
  const child = new EventEmitter();
  child.stdin = new PassThrough();
  child.stdout = new PassThrough();
  const native = createInterface({ input: child.stdin });
  const client = createInterface({ input: output });
  t.after(() => { native.close(); client.close(); input.end(); child.emit('exit', 0); });
  native.on('line', line => {
    const request = JSON.parse(line);
    child.stdout.write(`${JSON.stringify({ method: 'thread/settings/updated', params: {
      threadId: 'fixture', threadSettings: { collaborationMode: { mode: 'plan' } },
    } })}\n`);
    child.stdout.write(`${JSON.stringify({ id: request.id, result: { thread: { id: 'fixture' } } })}\n`);
  });
  connectDesktopBridge({ input, output, child, provider: {}, diagnostics() { throw new Error('fixture failure'); } });
  let notification;
  const done = new Promise(resolve => client.on('line', line => {
    const message = JSON.parse(line);
    if (message.method) notification = message;
    if (message.id === 1) resolve(message);
  }));
  input.write(`${JSON.stringify({ id: 1, method: 'thread/read', params: { threadId: 'fixture' } })}\n`);
  assert.deepEqual((await done).result, { thread: { id: 'fixture' } });
  assert.equal(notification.params.threadSettings.collaborationMode.mode, 'plan');
});
