import * as SecureStore from 'expo-secure-store';

import { SECURE_STORE_KEYS } from '@/config/constants';
import { safeLog } from '@/utils/logging';

/**
 * Secure session persistence.
 *
 * Stored in SecureStore (encrypted OS keychain/keystore):
 * - refresh_token
 * - biometric_enabled preference (boolean string)
 *
 * NEVER stored:
 * - password
 * - access_token (memory-only)
 * - tenant_id as an authorization source of truth
 */
export async function saveRefreshToken(token: string): Promise<void> {
  await SecureStore.setItemAsync(SECURE_STORE_KEYS.refreshToken, token);
}

export async function readRefreshToken(): Promise<string | null> {
  try {
    return await SecureStore.getItemAsync(SECURE_STORE_KEYS.refreshToken);
  } catch (err) {
    safeLog('warn', 'SecureStore read failed', { err: String(err) });
    return null;
  }
}

export async function clearRefreshToken(): Promise<void> {
  try {
    await SecureStore.deleteItemAsync(SECURE_STORE_KEYS.refreshToken);
  } catch (err) {
    safeLog('warn', 'SecureStore delete refresh failed', { err: String(err) });
  }
}

export async function saveBiometricEnabled(enabled: boolean): Promise<void> {
  await SecureStore.setItemAsync(
    SECURE_STORE_KEYS.biometricEnabled,
    enabled ? '1' : '0',
  );
}

export async function readBiometricEnabled(): Promise<boolean> {
  try {
    const v = await SecureStore.getItemAsync(SECURE_STORE_KEYS.biometricEnabled);
    // Default ON for safety when enrolled hardware exists; UI can toggle.
    if (v == null) return true;
    return v === '1';
  } catch {
    return true;
  }
}

export async function clearAllSecureSession(): Promise<void> {
  await clearRefreshToken();
}
