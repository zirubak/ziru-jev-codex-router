import assert from 'node:assert/strict';
import test from 'node:test';
import { DesktopProviderBridge } from '../src/desktop-provider-bridge.mjs';
const fast = { id: 'priority', name: 'Fast', description: 'Faster serving, increased usage.' };
for (const supported of [true, false]) {
  test(`fixed Fast metadata follows paginated native capabilities: supported=${supported}`, async () => {
    const bridge = new DesktopProviderBridge({ provider: {}, request: async (_, params) => params.cursor
      ? { data: [{ model: 'gpt-6-astra', serviceTiers: supported ? [fast] : [] }], nextCursor: null }
      : { data: [{ model: 'gpt-6.1-sol', serviceTiers: supported ? [fast] : [] }], nextCursor: 'page2' } });
    await bridge.handle('model/list');
    const result = await bridge.handle('model/list', { cursor: 'page2' });
    for (const mode of ['auto', 'manual', 'sol', 'astra']) {
      const entry = result.data.find(model => model.model === `jev/${mode}`);
      assert.deepEqual(entry.serviceTiers ?? [], supported && ['sol', 'astra'].includes(mode) ? [fast] : []);
      assert.equal(entry.defaultServiceTier ?? null, null);
    }
  });
}
