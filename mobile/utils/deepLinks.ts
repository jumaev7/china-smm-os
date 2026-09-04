import { INTERNAL_ROUTE_ALLOWLIST } from '@/config/constants';

/**
 * Deep-link safety: only allowlisted internal routes.
 * Never execute actions from links. Never open arbitrary backend URLs.
 */
export function resolveSafeInternalRoute(path: string | null | undefined): string | null {
  if (!path) return null;
  const cleaned = path.trim().split('?')[0].split('#')[0];
  if (!cleaned.startsWith('/')) return null;
  if (cleaned.includes('://')) return null;
  if (/action|approve|retry|ack|resolve|oauth|callback/i.test(cleaned)) {
    return null;
  }
  const match = INTERNAL_ROUTE_ALLOWLIST.find(
    (allowed) => cleaned === allowed || cleaned.startsWith(`${allowed}/`),
  );
  return match ?? null;
}
