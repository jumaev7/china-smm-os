import { CLIENT_SOURCE, REQUEST_TIMEOUT_MS } from '@/config/constants';
import { assertHttpsInProduction, getApiV1BaseUrl } from '@/config/env';
import { AppError, classifyHttpStatus } from '@/utils/errors';
import { safeLog } from '@/utils/logging';

export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

export interface ApiRequestOptions {
  method?: HttpMethod;
  path: string;
  body?: unknown;
  accessToken?: string | null;
  /** Skip Authorization header (login/refresh). */
  anonymous?: boolean;
  signal?: AbortSignal;
  /** Extra headers */
  headers?: Record<string, string>;
  /** When true, do not attempt refresh on 401 (caller handles). */
  skipAuthRetry?: boolean;
}

export interface ApiClientHooks {
  getAccessToken: () => string | null;
  refreshAccessToken: () => Promise<string | null>;
  onSessionInvalid: () => void | Promise<void>;
}

let hooks: ApiClientHooks | null = null;

export function configureApiClient(next: ApiClientHooks): void {
  hooks = next;
}

function buildUrl(path: string): string {
  const base = getApiV1BaseUrl();
  // Enforce HTTPS for non-dev builds (certificate pinning is future hardening).
  assertHttpsInProduction(base.replace(/\/api\/v1$/, ''));
  if (path.startsWith('http')) {
    throw new AppError('validation', 'Absolute URLs are not allowed');
  }
  const normalized = path.startsWith('/') ? path : `/${path}`;
  return `${base}${normalized}`;
}

async function rawFetch(url: string, init: RequestInit): Promise<Response> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  const onAbort = () => controller.abort();
  if (init.signal) {
    if (init.signal.aborted) {
      clearTimeout(timeout);
      throw new AppError('timeout', 'Request aborted', { retryable: true });
    }
    init.signal.addEventListener('abort', onAbort, { once: true });
  }

  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } catch (err) {
    if (err instanceof Error && err.name === 'AbortError') {
      throw new AppError('timeout', 'Request timed out', { retryable: true, cause: err });
    }
    throw new AppError('network', 'Network request failed', { retryable: true, cause: err });
  } finally {
    clearTimeout(timeout);
    if (init.signal) {
      init.signal.removeEventListener('abort', onAbort);
    }
  }
}

async function parseBody(res: Response): Promise<unknown> {
  const text = await res.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return { detail: text.slice(0, 200) };
  }
}

function detailMessage(body: unknown, fallback: string): string {
  if (body && typeof body === 'object' && 'detail' in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === 'string') return d;
  }
  return fallback;
}

/**
 * Authenticated JSON API helper with single-flight 401 refresh.
 */
export async function apiRequest<T>(opts: ApiRequestOptions): Promise<T> {
  const url = buildUrl(opts.path);
  const method = opts.method ?? 'GET';

  const headers: Record<string, string> = {
    Accept: 'application/json',
    'X-Client-Source': CLIENT_SOURCE,
    ...(opts.headers ?? {}),
  };

  if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json';
  }

  let token = opts.accessToken ?? (opts.anonymous ? null : hooks?.getAccessToken() ?? null);
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  const doFetch = () =>
    rawFetch(url, {
      method,
      headers,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      signal: opts.signal,
    });

  safeLog('debug', 'api request', { method, path: opts.path });

  let res = await doFetch();

  if (res.status === 401 && !opts.anonymous && !opts.skipAuthRetry && hooks) {
    const refreshed = await hooks.refreshAccessToken();
    if (!refreshed) {
      await hooks.onSessionInvalid();
      throw new AppError('unauthorized', 'Session expired', { status: 401 });
    }
    token = refreshed;
    headers.Authorization = `Bearer ${token}`;
    res = await doFetch();
    if (res.status === 401) {
      await hooks.onSessionInvalid();
      throw new AppError('unauthorized', 'Session expired', { status: 401 });
    }
  }

  const body = await parseBody(res);

  if (!res.ok) {
    const kind = classifyHttpStatus(res.status);
    const message = detailMessage(body, `Request failed (${res.status})`);
    safeLog('warn', 'api error', { method, path: opts.path, status: res.status });
    throw new AppError(kind, message, {
      status: res.status,
      retryable: kind === 'server' || kind === 'rate_limited',
    });
  }

  return body as T;
}
