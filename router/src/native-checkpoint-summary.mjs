// The bundled native engine uses an ordinary Responses request for local
// checkpoint summarization when the previous model has no remote-compact metadata.
const CHECKPOINT_PREFIX = 'You are performing a CONTEXT CHECKPOINT COMPACTION.';

export function isNativeCheckpointSummary(payload) {
  if (!Array.isArray(payload?.input) || !Array.isArray(payload.tools)
      || payload.tools.length !== 0 || payload.tool_choice !== 'auto'
      || payload.input.some(item => item?.type === 'additional_tools')) return false;
  const terminal = payload.input.at(-1);
  const content = terminal?.content;
  return terminal?.type === 'message' && terminal.role === 'user'
    && Array.isArray(content) && content.length === 1
    && content[0]?.type === 'input_text' && typeof content[0].text === 'string'
    && content[0].text.startsWith(CHECKPOINT_PREFIX);
}


export function manualCheckpointEffort(payload, readRoute) {
  const threadId = payload.client_metadata?.thread_id;
  if (typeof threadId !== 'string' || !threadId || payload.prompt_cache_key !== threadId) {
    throw new Error('Native checkpoint thread identity is unconfirmed');
  }
  const record = readRoute(threadId);
  if (record?.phase !== 'confirmed' || record.mode !== 'manual'
      || record.model !== 'jev/manual' || record.threadId !== threadId
      || !['low', 'medium', 'high', 'xhigh', 'max'].includes(record.effort)) {
    throw new Error('Current Manual checkpoint effort is unconfirmed');
  }
  return record.effort;
}
