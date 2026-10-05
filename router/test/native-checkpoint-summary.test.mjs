import assert from 'node:assert/strict';
import test from 'node:test';
import { isNativeCheckpointSummary, manualCheckpointEffort } from '../src/native-checkpoint-summary.mjs';

const summary = () => ({ tools: [], tool_choice: 'auto', input: [{
  type: 'message', role: 'user', content: [{ type: 'input_text',
    text: 'You are performing a CONTEXT CHECKPOINT COMPACTION. Create a handoff summary.' }],
}] });

test('recognizes the native tool-free terminal checkpoint summary', () => {
  assert.equal(isNativeCheckpointSummary(summary()), true);
  const body = summary();
  body.input.unshift({ type: 'function_call_output', call_id: 'old', output: 'old evidence' });
  assert.equal(isNativeCheckpointSummary(body), true);
});

for (const [name, alter] of [
  ['live tools', body => { body.tools.push({ type: 'function', name: 'execute' }); }],
  ['deferred tools', body => { body.input.unshift({ type: 'additional_tools', tools: [] }); }],
  ['missing tools', body => { delete body.tools; }],
  ['non-auto choice', body => { body.tool_choice = 'required'; }],
  ['missing choice', body => { delete body.tool_choice; }],
  ['nonterminal prompt', body => { body.input.push({ type: 'message', role: 'user', content: [] }); }],
  ['ordinary text', body => { body.input[0].content[0].text = 'Continue the task'; }],
  ['quoted prefix', body => { body.input[0].content[0].text = 'Quote: ' + body.input[0].content[0].text; }],
  ['assistant message', body => { body.input[0].role = 'assistant'; }],
  ['system message', body => { body.input[0].role = 'system'; }],
  ['wrong item type', body => { body.input[0].type = 'agent_message'; }],
  ['mixed content', body => { body.input[0].content.push({ type: 'input_image' }); }],
  ['wrong content type', body => { body.input[0].content[0].type = 'output_text'; }],
  ['non-string text', body => { body.input[0].content[0].text = null; }],
  ['string content', body => { body.input[0].content = body.input[0].content[0].text; }],
  ['missing content', body => { delete body.input[0].content; }],
  ['null content item', body => { body.input[0].content = [null]; }],
  ['null terminal', body => { body.input[0] = null; }],
  ['empty input', body => { body.input = []; }],
  ['non-array input', body => { body.input = {}; }],
]) {
  test(`refuses ${name}`, () => {
    const body = summary();
    alter(body);
    assert.equal(isNativeCheckpointSummary(body), false);
  });
}

test('refuses absent payloads', () => {
  assert.equal(isNativeCheckpointSummary(null), false);
  assert.equal(isNativeCheckpointSummary(undefined), false);
});


const manualPayload = () => ({ client_metadata: { thread_id: 'thread-1' }, prompt_cache_key: 'thread-1' });
const manualRecord = () => ({ threadId: 'thread-1', phase: 'confirmed', mode: 'manual', model: 'jev/manual', effort: 'high' });

test('restores every supported current Manual effort without changing the record', () => {
  for (const effort of ['low', 'medium', 'high', 'xhigh', 'max']) {
    const record = { ...manualRecord(), effort };
    assert.equal(manualCheckpointEffort(manualPayload(), id => {
      assert.equal(id, 'thread-1');
      return record;
    }), effort);
    assert.equal(record.effort, effort);
  }
});

for (const [name, alter] of [
  ['absent metadata', payload => { delete payload.client_metadata; }],
  ['empty identity', payload => { payload.client_metadata.thread_id = ''; }],
  ['non-string identity', payload => { payload.client_metadata.thread_id = 1; }],
  ['different cache identity', payload => { payload.prompt_cache_key = 'other-thread'; }],
]) {
  test(`refuses ${name} before reading private state`, () => {
    const payload = manualPayload();
    alter(payload);
    assert.throws(() => manualCheckpointEffort(payload, () => assert.fail('must not read')), /identity/);
  });
}

for (const [name, change] of [
  ['pending selection', { phase: 'pending' }],
  ['Auto selection', { mode: 'auto' }],
  ['official model', { model: 'gpt-6.1-sol' }],
  ['different record identity', { threadId: 'thread-2' }],
  ['absent effort', { effort: null }],
  ['auto effort', { effort: 'auto' }],
]) {
  test(`refuses ${name}`, () => {
    assert.throws(() => manualCheckpointEffort(manualPayload(), () => ({ ...manualRecord(), ...change })), /unconfirmed/);
  });
}

test('refuses absent and unreadable private selections', () => {
  assert.throws(() => manualCheckpointEffort(manualPayload(), () => null), /unconfirmed/);
  assert.throws(() => manualCheckpointEffort(manualPayload(), () => { throw new Error('Unreadable'); }), /Unreadable/);
});
