import assert from 'node:assert/strict';
import test from 'node:test';
import { mkdtempSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync, chmodSync, symlinkSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { PrivateRouteState } from '../src/desktop-provider-state.mjs';

function fixture(t) {
  const root = mkdtempSync(join(tmpdir(), 'jev-route-state-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  return { root, directory: join(root, 'thread-routes') };
}
const route = { mode: 'manual', model: 'jev/manual', effort: 'medium', phase: 'confirmed' };

test('route records survive reopening with owner-only files and no other fields', (t) => {
  const { directory } = fixture(t);
  const state = new PrivateRouteState(directory);
  assert.equal(state.read('thread-1'), null);
  const saved = state.write('thread-1', route, null);
  assert.equal(saved.revision, 1);
  assert.deepEqual(new PrivateRouteState(directory).read('thread-1'), saved);
  assert.equal(statSync(directory).mode & 0o777, 0o700);
  const name = readdirSync(directory)[0];
  assert.equal(statSync(join(directory, name)).mode & 0o777, 0o600);
  assert.deepEqual(Object.keys(JSON.parse(readFileSync(join(directory, name)))).sort(), ['effort', 'mode', 'model', 'phase', 'revision', 'threadId', 'version']);
});

test('stale writers cannot overwrite another confirmed transition', (t) => {
  const { directory } = fixture(t);
  const state = new PrivateRouteState(directory);
  const first = state.write('thread-1', route, null);
  state.write('thread-1', { ...route, phase: 'pending' }, first.revision);
  assert.throws(() => state.write('thread-1', { ...route, effort: 'high' }, first.revision), /changed|revision/);
});

test('pending states persist and unsafe records or directories fail closed', (t) => {
  const { root, directory } = fixture(t);
  const state = new PrivateRouteState(directory);
  state.write('thread-1', { ...route, phase: 'pending' }, null);
  assert.equal(new PrivateRouteState(directory).read('thread-1').phase, 'pending');
  const name = readdirSync(directory)[0];
  chmodSync(join(directory, name), 0o644);
  assert.throws(() => state.read('thread-1'), /private|owner/);
  const linked = join(root, 'linked');
  symlinkSync(directory, linked);
  assert.throws(() => new PrivateRouteState(linked), /private|owner|symbolic/);
});

test('invalid values cannot be persisted and unexpected record fields are rejected', (t) => {
  const { directory } = fixture(t);
  const state = new PrivateRouteState(directory);
  assert.throws(() => state.write('thread-1', { ...route, prompt: 'not allowed' }, null), /record/);
  state.write('thread-1', route, null);
  const name = readdirSync(directory)[0];
  writeFileSync(join(directory, name), '{"version":99}', { mode: 0o600 });
  assert.throws(() => state.read('thread-1'), /record/);
});


test('official effort uses native non-empty string contract while Jev stays bounded', (t) => {
  const { directory } = fixture(t);
  const state = new PrivateRouteState(directory);
  for (const effort of ['none', 'minimal', 'ultra', 'future-native-effort', null]) {
    const id = `official-${effort}`;
    const record = state.write(id, { ...route, mode: 'official', model: 'gpt-6.1-sol', effort }, null);
    assert.deepEqual(new PrivateRouteState(directory).read(id), record);
  }
  for (const effort of ['', 42, {}, ['ultra'], 'x'.repeat(4096)]) {
    assert.throws(() => state.write('invalid', { ...route, mode: 'official', model: 'gpt-6.1-sol', effort }, null), /record/);
  }
  for (const mode of ['auto', 'manual']) {
    assert.throws(() => state.write(mode, { ...route, mode, model: `jev/${mode}`, effort: 'ultra' }, null), /record/);
  }
});
