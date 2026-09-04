/**
 * Safe logging — never emit tokens, passwords, or Authorization headers.
 */

const SENSITIVE_KEY =
  /pass(word)?|token|authorization|secret|cookie|refresh|access_token|api[_-]?key/i;

const BEARER_RE = /Bearer\s+[A-Za-z0-9\-._~+/]+=*/gi;
const JWT_RE = /eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/g;

export function scrubValue(value: unknown): unknown {
  if (value == null) return value;
  if (typeof value === 'string') {
    return value.replace(BEARER_RE, 'Bearer [REDACTED]').replace(JWT_RE, '[REDACTED_JWT]');
  }
  if (Array.isArray(value)) {
    return value.map(scrubValue);
  }
  if (typeof value === 'object') {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      out[k] = SENSITIVE_KEY.test(k) ? '[REDACTED]' : scrubValue(v);
    }
    return out;
  }
  return value;
}

export function safeLog(level: 'debug' | 'info' | 'warn' | 'error', message: string, meta?: unknown): void {
  if (!__DEV__ && level === 'debug') return;
  const payload = meta === undefined ? undefined : scrubValue(meta);
  const fn = console[level] ?? console.log;
  if (payload === undefined) {
    fn(`[mobile] ${message}`);
  } else {
    fn(`[mobile] ${message}`, payload);
  }
}
