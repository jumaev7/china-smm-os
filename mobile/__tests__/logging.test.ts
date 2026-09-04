/**
 * @jest-environment node
 */
import { scrubValue, safeLog } from '../utils/logging';

describe('sensitive log scrub', () => {
  it('redacts tokens, passwords, and authorization fields', () => {
    const scrubbed = scrubValue({
      email: 'ops@example.com',
      password: 'super-secret',
      access_token: 'eyJhbGciOiJIUzI1NiJ9.aaa.bbb',
      Authorization: 'Bearer abc.def.ghi',
      nested: { refresh_token: 'rrr', ok: true },
    }) as Record<string, unknown>;

    expect(scrubbed.email).toBe('ops@example.com');
    expect(scrubbed.password).toBe('[REDACTED]');
    expect(scrubbed.access_token).toBe('[REDACTED]');
    expect(scrubbed.Authorization).toBe('[REDACTED]');
    expect((scrubbed.nested as Record<string, unknown>).refresh_token).toBe(
      '[REDACTED]',
    );
    expect((scrubbed.nested as Record<string, unknown>).ok).toBe(true);
  });

  it('redacts bearer strings embedded in messages', () => {
    const scrubbed = scrubValue(
      'Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.aaa.bbb',
    );
    expect(String(scrubbed)).toContain('[REDACTED]');
    expect(String(scrubbed)).not.toContain('eyJ');
  });

  it('safeLog does not throw on sensitive meta', () => {
    const spy = jest.spyOn(console, 'info').mockImplementation(() => undefined);
    expect(() =>
      safeLog('info', 'login ok', { token: 'secret', route: '/auth/login' }),
    ).not.toThrow();
    spy.mockRestore();
  });
});
