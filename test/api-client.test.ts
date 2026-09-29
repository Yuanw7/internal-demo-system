import assert from 'node:assert/strict';
import test from 'node:test';

import {
  ApiError,
  ApiProtocolError,
  MissingCredentialError,
  RetrievalApiClient,
  parseContract,
  type FetchLike,
} from '../src/api/index.ts';
import { contractExamples } from '../src/api/generated/contracts.ts';

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

test('client preserves the receiver required by browser fetch', async () => {
  let receiver: unknown;
  const fetchFn = function (this: unknown): Promise<Response> {
    receiver = this;
    return Promise.resolve(jsonResponse({ documents: 2, chunks: 2, sources: 2, policy_version: 1 }));
  };
  const client = new RetrievalApiClient({
    baseUrl: 'http://example.test',
    readToken: 'read-token',
    fetchFn,
  });
  await client.getStatus();
  assert.equal(receiver, globalThis);
});

test('client uses one contract-shaped boundary and the correct credentials', async () => {
  const calls: Array<{ url: string; init: RequestInit | undefined }> = [];
  const responses = [
    { documents: 2, chunks: 2, sources: 2, policy_version: 1 },
    contractExamples.sources_response,
    contractExamples.search_response,
    contractExamples.document_response,
    contractExamples.policy_response,
    contractExamples.policy_update_response,
  ];
  const fetchFn: FetchLike = async (input, init) => {
    calls.push({ url: String(input), init });
    const response = responses.shift();
    assert.ok(response);
    return jsonResponse(response);
  };
  const client = new RetrievalApiClient({
    baseUrl: 'http://example.test/',
    readToken: 'read-token',
    adminToken: 'admin-token',
    fetchFn,
  });

  await client.getStatus();
  await client.getSources();
  await client.search(parseContract('SearchRequest', structuredClone(contractExamples.search_request)));
  await client.getDocument(contractExamples.document_response.id);
  await client.getPolicy();
  await client.updatePolicy(structuredClone(contractExamples.policy_update_request));

  assert.deepEqual(
    calls.map((call) => [call.init?.method, call.url]),
    [
      ['GET', 'http://example.test/api/status'],
      ['GET', 'http://example.test/api/sources'],
      ['POST', 'http://example.test/api/search'],
      ['GET', `http://example.test/api/documents/${contractExamples.document_response.id}`],
      ['GET', 'http://example.test/api/policy'],
      ['PUT', 'http://example.test/api/policy'],
    ],
  );
  assert.equal((calls[0]?.init?.headers as Record<string, string>).Authorization, 'Bearer read-token');
  assert.equal((calls[5]?.init?.headers as Record<string, string>).Authorization, 'Bearer admin-token');
  assert.deepEqual(
    JSON.parse(String(calls[5]?.init?.body)),
    contractExamples.policy_update_request,
  );
});

for (const status of [401, 403, 404, 409, 413, 422]) {
  test(`client maps ${status} error responses`, async () => {
    const client = new RetrievalApiClient({
      baseUrl: 'http://example.test',
      readToken: 'read-token',
      fetchFn: async () => jsonResponse(contractExamples.error_response, status),
    });

    await assert.rejects(
      client.search(parseContract('SearchRequest', structuredClone(contractExamples.search_request))),
      (error: unknown) =>
        error instanceof ApiError &&
        error.status === status &&
        error.code === 'policy_version_conflict',
    );
  });
}

test('client rejects unknown response fields instead of silently accepting drift', async () => {
  const client = new RetrievalApiClient({
    baseUrl: 'http://example.test',
    readToken: 'read-token',
    fetchFn: async () => jsonResponse({ ...contractExamples.sources_response, unexpected: true }),
  });

  await assert.rejects(
    client.getSources(),
    (error: unknown) => error instanceof ApiProtocolError && error.cause instanceof Error,
  );
});

test('client refuses policy mutation without an admin credential', async () => {
  const client = new RetrievalApiClient({
    baseUrl: 'http://example.test',
    readToken: 'read-token',
    fetchFn: async () => assert.fail('fetch must not be called'),
  });

  await assert.rejects(
    client.updatePolicy(structuredClone(contractExamples.policy_update_request)),
    MissingCredentialError,
  );
});

test('local no-auth client omits authorization for read and admin requests', async () => {
  const calls: RequestInit[] = [];
  const responses = [
    { documents: 2, chunks: 2, sources: 2, policy_version: 1 },
    contractExamples.policy_update_response,
  ];
  const client = new RetrievalApiClient({
    baseUrl: 'http://127.0.0.1:8765',
    authMode: 'none',
    fetchFn: async (_input, init) => {
      calls.push(init ?? {});
      const response = responses.shift();
      assert.ok(response);
      return jsonResponse(response);
    },
  });

  await client.getStatus();
  await client.updatePolicy(structuredClone(contractExamples.policy_update_request));
  assert.equal((calls[0]?.headers as Record<string, string>).Authorization, undefined);
  assert.equal((calls[1]?.headers as Record<string, string>).Authorization, undefined);
});

test('ingestion monitoring reads with read token and retries with admin token', async () => {
  const calls: Array<{ url: string; init: RequestInit | undefined }> = [];
  const item = {
    id: 'item-1',
    connector_id: 'capital_iq_folder',
    external_id: 'fictional.pdf',
    display_name: 'fictional.pdf',
    status: 'failed',
    pipeline_stage: 'parse',
    outcome: '',
    attempt_count: 1,
    max_attempts: 3,
    discovered_at: '2026-09-29T00:00:00+00:00',
    started_at: '2026-09-29T00:00:01+00:00',
    searchable_at: null,
    finished_at: '2026-09-29T00:00:02+00:00',
    error_code: 'pdf_parse_failed',
    state_version: 3,
  } as const;
  const responses = [
    {
      as_of: '2026-09-29T00:00:03+00:00',
      counts: { pending: 0, processing: 0, processed: 0, failed: 1, retrying: 0 },
      vector_backlog: 0,
      unresolved_dead_letters: 1,
      oldest_pending_age_seconds: null,
    },
    { items: [item], next_cursor: null },
    {
      ...item,
      source_locator: 'fictional.pdf',
      content_fingerprint: 'fixture-sha',
      pipeline_version: 'fixture-v1',
      semantic_required: true,
      semantic_generation_id: null,
      input_bytes: 12,
      duration_ms: 1000,
      error_class: 'data',
      error_message: 'fixture',
      document_ids: [],
      attempts: [],
      events: [],
    },
    {
      item_id: 'item-1',
      status: 'retrying',
      next_attempt_at: '2026-09-29T00:00:04+00:00',
      state_version: 4,
    },
  ];
  const client = new RetrievalApiClient({
    baseUrl: 'http://example.test',
    readToken: 'read-token',
    adminToken: 'admin-token',
    fetchFn: async (input, init) => {
      calls.push({ url: String(input), init });
      const response = responses.shift();
      assert.ok(response);
      return jsonResponse(response);
    },
  });

  await client.getIngestionSummary();
  await client.getIngestionItems({ status: 'failed', limit: 50 });
  await client.getIngestionItem('item-1');
  await client.retryIngestionItem('item-1', {
    expected_state_version: 3,
    mode: 'restart',
    reason: 'fixture repair',
  });

  assert.equal(calls[1]?.url, 'http://example.test/api/ingestion/items?status=failed&limit=50');
  assert.equal((calls[0]?.init?.headers as Record<string, string>).Authorization, 'Bearer read-token');
  assert.equal((calls[3]?.init?.headers as Record<string, string>).Authorization, 'Bearer admin-token');
});
