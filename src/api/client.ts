import type {
  MCPFetchResult,
  IngestionItemDetail,
  IngestionItemsResponse,
  IngestionSummaryResponse,
  PolicyState,
  PolicyUpdate,
  SearchRequest,
  SearchResponse,
  SourcesResponse,
  StatusResponse,
  RetryIngestionRequest,
  RetryIngestionResponse,
} from './generated/contracts.ts';
import { ContractValidationError, parseContract } from './validation.ts';

export type FetchLike = (input: string | URL, init?: RequestInit) => Promise<Response>;

export interface RetrievalApi {
  getStatus(): Promise<StatusResponse>;
  getSources(): Promise<SourcesResponse>;
  search(request: SearchRequest): Promise<SearchResponse>;
  getDocument(documentId: string): Promise<MCPFetchResult>;
  getPolicy(): Promise<PolicyState>;
  updatePolicy(request: PolicyUpdate): Promise<PolicyState>;
  getIngestionSummary(connectorId?: string): Promise<IngestionSummaryResponse>;
  getIngestionItems(filters?: IngestionItemFilters): Promise<IngestionItemsResponse>;
  getIngestionItem(itemId: string): Promise<IngestionItemDetail>;
  retryIngestionItem(itemId: string, request: RetryIngestionRequest): Promise<RetryIngestionResponse>;
}

export interface IngestionItemFilters {
  status?: string;
  connector_id?: string;
  pipeline_stage?: string;
  limit?: number;
  cursor?: string;
}

export interface RetrievalApiClientOptions {
  baseUrl: string;
  authMode?: 'bearer' | 'none';
  readToken?: string;
  adminToken?: string;
  fetchFn?: FetchLike;
  timeoutMs?: number;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly fields: string[];

  constructor(status: number, code: string, message: string, fields: string[] = []) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.fields = fields;
  }
}

export class ApiProtocolError extends Error {
  readonly cause: unknown;

  constructor(message: string, cause?: unknown) {
    super(message);
    this.name = 'ApiProtocolError';
    this.cause = cause;
  }
}

export class MissingCredentialError extends Error {
  constructor(credential: 'read' | 'admin') {
    super(`Missing ${credential} credential`);
    this.name = 'MissingCredentialError';
  }
}

type Credential = 'read' | 'admin';

export class RetrievalApiClient implements RetrievalApi {
  private readonly baseUrl: string;
  private readonly authMode: 'bearer' | 'none';
  private readonly readToken: string | undefined;
  private readonly adminToken: string | undefined;
  private readonly fetchFn: FetchLike;
  private readonly timeoutMs: number;

  constructor(options: RetrievalApiClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/$/, '');
    this.authMode = options.authMode ?? 'bearer';
    this.readToken = options.readToken;
    this.adminToken = options.adminToken;
    this.fetchFn = (options.fetchFn ?? fetch).bind(globalThis);
    this.timeoutMs = options.timeoutMs ?? 10_000;
  }

  getStatus(): Promise<StatusResponse> {
    return this.request('/api/status', 'GET', 'read', 'StatusResponse');
  }

  getSources(): Promise<SourcesResponse> {
    return this.request('/api/sources', 'GET', 'read', 'SourcesResponse');
  }

  search(request: SearchRequest): Promise<SearchResponse> {
    const body = parseContract('SearchRequest', request);
    return this.request('/api/search', 'POST', 'read', 'SearchResponse', body);
  }

  getDocument(documentId: string): Promise<MCPFetchResult> {
    return this.request(
      `/api/documents/${encodeURIComponent(documentId)}`,
      'GET',
      'read',
      'MCPFetchResult',
    );
  }

  getPolicy(): Promise<PolicyState> {
    return this.request('/api/policy', 'GET', 'read', 'PolicyState');
  }

  updatePolicy(request: PolicyUpdate): Promise<PolicyState> {
    const body = parseContract('PolicyUpdate', request);
    return this.request('/api/policy', 'PUT', 'admin', 'PolicyState', body);
  }

  getIngestionSummary(connectorId = ''): Promise<IngestionSummaryResponse> {
    const query = connectorId ? `?connector_id=${encodeURIComponent(connectorId)}` : '';
    return this.request(`/api/ingestion/summary${query}`, 'GET', 'read', 'IngestionSummaryResponse');
  }

  getIngestionItems(filters: IngestionItemFilters = {}): Promise<IngestionItemsResponse> {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(filters)) {
      if (value !== undefined && value !== '') query.set(key, String(value));
    }
    const suffix = query.size ? `?${query.toString()}` : '';
    return this.request(`/api/ingestion/items${suffix}`, 'GET', 'read', 'IngestionItemsResponse');
  }

  getIngestionItem(itemId: string): Promise<IngestionItemDetail> {
    return this.request(
      `/api/ingestion/items/${encodeURIComponent(itemId)}`,
      'GET',
      'read',
      'IngestionItemDetail',
    );
  }

  retryIngestionItem(
    itemId: string,
    request: RetryIngestionRequest,
  ): Promise<RetryIngestionResponse> {
    const body = parseContract('RetryIngestionRequest', request);
    return this.request(
      `/api/ingestion/items/${encodeURIComponent(itemId)}/retry`,
      'POST',
      'admin',
      'RetryIngestionResponse',
      body,
    );
  }

  private async request<Name extends Parameters<typeof parseContract>[0]>(
    path: string,
    method: 'GET' | 'POST' | 'PUT',
    credential: Credential,
    responseSchema: Name,
    body?: unknown,
  ): Promise<ReturnType<typeof parseContract<Name>>> {
    const token = credential === 'admin' ? this.adminToken : this.readToken;
    if (this.authMode === 'bearer' && !token) throw new MissingCredentialError(credential);

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.timeoutMs);

    try {
      const headers: Record<string, string> = {
        Accept: 'application/json',
      };
      if (this.authMode === 'bearer' && token) headers.Authorization = `Bearer ${token}`;
      if (body !== undefined) headers['Content-Type'] = 'application/json';

      const requestInit: RequestInit = {
        method,
        headers,
        signal: controller.signal,
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      };
      const response = await this.fetchFn(`${this.baseUrl}${path}`, requestInit);
      const text = await response.text();
      let payload: unknown;

      try {
        payload = JSON.parse(text);
      } catch (error) {
        throw new ApiProtocolError(`Expected JSON from ${method} ${path}`, error);
      }

      if (!response.ok) {
        try {
          const parsed = parseContract('ErrorResponse', payload);
          throw new ApiError(
            response.status,
            parsed.error.code,
            parsed.error.message,
            parsed.error.fields ?? [],
          );
        } catch (error) {
          if (error instanceof ApiError) throw error;
          throw new ApiProtocolError(`Invalid error response from ${method} ${path}`, error);
        }
      }

      try {
        return parseContract(responseSchema, payload) as ReturnType<typeof parseContract<Name>>;
      } catch (error) {
        if (error instanceof ContractValidationError) {
          throw new ApiProtocolError(`Response contract mismatch for ${method} ${path}`, error);
        }
        throw error;
      }
    } finally {
      clearTimeout(timeout);
    }
  }
}
