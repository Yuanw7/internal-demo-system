export interface LiveConnectionPreference {
  version: 1;
  baseUrl: string;
  authMode: 'none';
}

interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

export const LIVE_CONNECTION_PREFERENCE_KEY = 'research-dashboard-live-connection-v1';

export function isLoopbackBaseUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return (
      (url.protocol === 'http:' || url.protocol === 'https:') &&
      (url.hostname === '127.0.0.1' || url.hostname === 'localhost' || url.hostname === '[::1]')
    );
  } catch {
    return false;
  }
}

export function parseLiveConnectionPreference(raw: string | null): LiveConnectionPreference | undefined {
  if (!raw) return undefined;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (
      typeof parsed === 'object' &&
      parsed !== null &&
      Object.keys(parsed).length === 3 &&
      'version' in parsed &&
      parsed.version === 1 &&
      'baseUrl' in parsed &&
      typeof parsed.baseUrl === 'string' &&
      isLoopbackBaseUrl(parsed.baseUrl) &&
      'authMode' in parsed &&
      parsed.authMode === 'none'
    ) {
      return { version: 1, baseUrl: parsed.baseUrl.replace(/\/$/, ''), authMode: 'none' };
    }
  } catch {
    // Invalid local state is ignored and replaced after the next successful connection.
  }
  return undefined;
}

export function loadLiveConnectionPreference(
  storage: Pick<StorageLike, 'getItem'>,
): LiveConnectionPreference | undefined {
  return parseLiveConnectionPreference(storage.getItem(LIVE_CONNECTION_PREFERENCE_KEY));
}

export function saveLiveConnectionPreference(
  storage: Pick<StorageLike, 'setItem'>,
  baseUrl: string,
): void {
  if (!isLoopbackBaseUrl(baseUrl)) return;
  storage.setItem(
    LIVE_CONNECTION_PREFERENCE_KEY,
    JSON.stringify({ version: 1, baseUrl: baseUrl.replace(/\/$/, ''), authMode: 'none' }),
  );
}

export function clearLiveConnectionPreference(storage: Pick<StorageLike, 'removeItem'>): void {
  storage.removeItem(LIVE_CONNECTION_PREFERENCE_KEY);
}
