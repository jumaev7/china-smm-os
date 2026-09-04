/**
 * Public runtime config only. Never place secrets here.
 * EXPO_PUBLIC_* values are embedded in the client bundle.
 */

function stripTrailingSlash(url: string): string {
  return url.replace(/\/+$/, '');
}

export function getApiBaseUrl(): string {
  const raw = process.env.EXPO_PUBLIC_API_BASE_URL?.trim();
  if (!raw) {
    // Dev-safe default — override via .env / EXPO_PUBLIC_API_BASE_URL for production canary.
    return 'http://localhost:8000';
  }
  return stripTrailingSlash(raw);
}

export function getApiV1BaseUrl(): string {
  return `${getApiBaseUrl()}/api/v1`;
}

export function assertHttpsInProduction(url: string): void {
  if (__DEV__) return;
  if (!url.startsWith('https://')) {
    throw new Error('Production API base URL must use HTTPS');
  }
}

export const IS_DEV = __DEV__;
