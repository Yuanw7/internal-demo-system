import assert from 'node:assert/strict';
import test from 'node:test';

import {
  LIVE_CONNECTION_PREFERENCE_KEY,
  clearLiveConnectionPreference,
  loadLiveConnectionPreference,
  parseLiveConnectionPreference,
  saveLiveConnectionPreference,
} from '../src/ui/connection-preference.ts';

test('local no-auth connection can be restored without persisting tokens', () => {
  const values = new Map<string, string>();
  const storage = {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
    removeItem: (key: string) => values.delete(key),
  };

  saveLiveConnectionPreference(storage, 'http://127.0.0.1:8876/');
  assert.deepEqual(loadLiveConnectionPreference(storage), {
    version: 1,
    baseUrl: 'http://127.0.0.1:8876',
    authMode: 'none',
  });
  assert.equal(values.get(LIVE_CONNECTION_PREFERENCE_KEY)?.includes('token'), false);

  clearLiveConnectionPreference(storage);
  assert.equal(loadLiveConnectionPreference(storage), undefined);
});

test('connection restoration rejects non-loopback and malformed state', () => {
  assert.equal(
    parseLiveConnectionPreference(
      JSON.stringify({ version: 1, baseUrl: 'https://example.com', authMode: 'none' }),
    ),
    undefined,
  );
  assert.equal(parseLiveConnectionPreference('{broken'), undefined);
  assert.equal(
    parseLiveConnectionPreference(
      JSON.stringify({ version: 1, baseUrl: 'http://localhost:8765', authMode: 'bearer' }),
    ),
    undefined,
  );
});
