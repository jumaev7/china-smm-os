import { apiRequest } from '@/api/client';
import type {
  AuthLoginResponse,
  AuthMeResponse,
  AuthRefreshResponse,
} from '@/types/auth';

export async function loginRequest(email: string, password: string): Promise<AuthLoginResponse> {
  return apiRequest<AuthLoginResponse>({
    method: 'POST',
    path: '/auth/login',
    body: { email: email.trim().toLowerCase(), password },
    anonymous: true,
  });
}

export async function refreshRequest(refreshToken: string): Promise<AuthRefreshResponse> {
  return apiRequest<AuthRefreshResponse>({
    method: 'POST',
    path: '/auth/refresh',
    body: { refresh_token: refreshToken },
    anonymous: true,
    skipAuthRetry: true,
  });
}

export async function meRequest(accessToken?: string): Promise<AuthMeResponse> {
  return apiRequest<AuthMeResponse>({
    method: 'GET',
    path: '/auth/me',
    accessToken,
    skipAuthRetry: true,
  });
}

export async function logoutRequest(): Promise<{ message: string }> {
  return apiRequest<{ message: string }>({
    method: 'POST',
    path: '/auth/logout',
  });
}
