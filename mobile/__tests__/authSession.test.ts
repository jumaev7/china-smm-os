/**
 * @jest-environment node
 *
 * Auth / session logic tests with mocked SecureStore + fetch.
 */

const secureStore: Record<string, string> = {};

jest.mock('expo-secure-store', () => ({
  setItemAsync: jest.fn(async (k: string, v: string) => {
    secureStore[k] = v;
  }),
  getItemAsync: jest.fn(async (k: string) => secureStore[k] ?? null),
  deleteItemAsync: jest.fn(async (k: string) => {
    delete secureStore[k];
  }),
}));

import {
  clearAllSecureSession,
  clearRefreshToken,
  readRefreshToken,
  saveRefreshToken,
} from '../storage/secureSession';
import {
  clearAccessToken,
  getAccessToken,
  setAccessToken,
} from '../auth/tokenMemory';
import { loginRequest, refreshRequest } from '../api/auth';
import { configureApiClient, apiRequest } from '../api/client';
import { SECURE_STORE_KEYS } from '../config/constants';

describe('secure session persistence', () => {
  beforeEach(() => {
    for (const k of Object.keys(secureStore)) delete secureStore[k];
    clearAccessToken();
  });

  it('stores refresh token in SecureStore keys only', async () => {
    await saveRefreshToken('refresh-abc');
    expect(await readRefreshToken()).toBe('refresh-abc');
    expect(secureStore[SECURE_STORE_KEYS.refreshToken]).toBe('refresh-abc');
  });

  it('logout clears SecureStore refresh material', async () => {
    await saveRefreshToken('refresh-abc');
    await clearAllSecureSession();
    expect(await readRefreshToken()).toBeNull();
  });

  it('keeps access token memory-only', () => {
    setAccessToken('access-xyz');
    expect(getAccessToken()).toBe('access-xyz');
    clearAccessToken();
    expect(getAccessToken()).toBeNull();
    expect(secureStore[SECURE_STORE_KEYS.refreshToken]).toBeUndefined();
  });
});

describe('login + refresh HTTP contracts', () => {
  beforeEach(() => {
    clearAccessToken();
    for (const k of Object.keys(secureStore)) delete secureStore[k];
  });

  it('login success returns tokens (password never stored)', async () => {
    const fetchMock = jest.fn(async () => ({
      ok: true,
      status: 200,
      text: async () =>
        JSON.stringify({
          access_token: 'a1',
          refresh_token: 'r1',
          token_type: 'bearer',
          user: {
            id: 'u1',
            tenant_id: 't1',
            email: 'ops@example.com',
            role: 'operator',
            status: 'active',
          },
          tenant: {
            id: 't1',
            company_name: 'Acme',
            status: 'active',
          },
        }),
    }));
    global.fetch = fetchMock as unknown as typeof fetch;

    const res = await loginRequest('ops@example.com', 'pw');
    expect(res.access_token).toBe('a1');
    expect(res.refresh_token).toBe('r1');
    const call = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    const body = JSON.parse(String(call[1].body));
    expect(body.password).toBe('pw');
    // Caller must not persist password — storage remains empty here.
    expect(Object.keys(secureStore)).toHaveLength(0);
  });

  it('login failure surfaces 401', async () => {
    global.fetch = jest.fn(async () => ({
      ok: false,
      status: 401,
      text: async () => JSON.stringify({ detail: 'Invalid credentials' }),
    })) as unknown as typeof fetch;
    await expect(loginRequest('x@y.com', 'bad')).rejects.toMatchObject({
      status: 401,
      kind: 'unauthorized',
    });
  });

  it('refresh success updates tokens', async () => {
    global.fetch = jest.fn(async () => ({
      ok: true,
      status: 200,
      text: async () =>
        JSON.stringify({
          access_token: 'a2',
          refresh_token: 'r2',
          token_type: 'bearer',
        }),
    })) as unknown as typeof fetch;
    const res = await refreshRequest('r1');
    expect(res.access_token).toBe('a2');
    expect(res.refresh_token).toBe('r2');
  });

  it('refresh failure returns error (caller clears session)', async () => {
    global.fetch = jest.fn(async () => ({
      ok: false,
      status: 401,
      text: async () => JSON.stringify({ detail: 'expired' }),
    })) as unknown as typeof fetch;
    await expect(refreshRequest('bad')).rejects.toMatchObject({
      kind: 'unauthorized',
    });
  });
});

describe('401 handling + no tenant_id trust', () => {
  it('retries once after refresh then invalidates session', async () => {
    let refreshCalls = 0;
    let invalidated = 0;
    configureApiClient({
      getAccessToken: () => 'expired',
      refreshAccessToken: async () => {
        refreshCalls += 1;
        return null;
      },
      onSessionInvalid: () => {
        invalidated += 1;
      },
    });

    global.fetch = jest.fn(async () => ({
      ok: false,
      status: 401,
      text: async () => JSON.stringify({ detail: 'expired' }),
    })) as unknown as typeof fetch;

    await expect(
      apiRequest({ method: 'GET', path: '/mobile-control/home' }),
    ).rejects.toMatchObject({ kind: 'unauthorized' });
    expect(refreshCalls).toBe(1);
    expect(invalidated).toBe(1);
  });

  it('does not send client-invented tenant_id on home reads', async () => {
    configureApiClient({
      getAccessToken: () => 'good',
      refreshAccessToken: async () => 'good',
      onSessionInvalid: () => undefined,
    });
    const fetchMock = jest.fn(async () => ({
      ok: true,
      status: 200,
      text: async () =>
        JSON.stringify({
          generated_at: new Date().toISOString(),
          attention_summary: { total: 0 },
          approvals_count: 0,
          problems_count: 0,
          waiting_for_client: 0,
          unread_notifications: 0,
          system_status: {
            overall: 'ok',
            api: 'ok',
            database: 'ok',
            scheduler: 'ok',
            ai_services: 'ok',
            telegram_bot: 'ok',
            integration_attention_count: 0,
            backup: { status: 'unavailable', message: 'n/a' },
            notes: [],
          },
          urgent_items: [],
          urgent_limit: 10,
          capabilities: {
            actions_supported: [],
            push_registration: false,
            biometric_unlock: false,
            internal_content_reject: false,
            backup_status_live: false,
            realtime_channel: false,
          },
          deep_link_base: '/operator-workspace',
          last_updated_at: new Date().toISOString(),
        }),
    }));
    global.fetch = fetchMock as unknown as typeof fetch;

    await apiRequest({ method: 'GET', path: '/mobile-control/home' });
    const call = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    const url = String(call[0]);
    expect(url).toContain('/mobile-control/home');
    expect(url).not.toMatch(/tenant_id=/);
    const headers = call[1].headers as Record<string, string>;
    expect(headers['X-Client-Source']).toBe('mobile');
  });
});

describe('clearRefreshToken helper', () => {
  it('deletes refresh key', async () => {
    await saveRefreshToken('x');
    await clearRefreshToken();
    expect(await readRefreshToken()).toBeNull();
  });
});
