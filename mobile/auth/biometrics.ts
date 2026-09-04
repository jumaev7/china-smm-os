import * as LocalAuthentication from 'expo-local-authentication';

import {
  readBiometricEnabled,
  saveBiometricEnabled,
} from '@/storage/secureSession';
import { safeLog } from '@/utils/logging';

export interface BiometricCapability {
  hardware: boolean;
  enrolled: boolean;
  available: boolean;
}

export async function getBiometricCapability(): Promise<BiometricCapability> {
  try {
    const hardware = await LocalAuthentication.hasHardwareAsync();
    const enrolled = hardware ? await LocalAuthentication.isEnrolledAsync() : false;
    return { hardware, enrolled, available: hardware && enrolled };
  } catch (err) {
    safeLog('warn', 'biometric capability check failed', { err: String(err) });
    return { hardware: false, enrolled: false, available: false };
  }
}

export async function isBiometricPreferenceEnabled(): Promise<boolean> {
  return readBiometricEnabled();
}

export async function setBiometricPreference(enabled: boolean): Promise<void> {
  await saveBiometricEnabled(enabled);
}

/**
 * Local unlock only — does NOT authenticate against the backend.
 * Returns true if unlocked (or biometric unavailable → soft pass to avoid lockout).
 */
export async function promptBiometricUnlock(
  reason = 'Unlock China SMM Operator',
): Promise<{ success: boolean; softPassed: boolean }> {
  const cap = await getBiometricCapability();
  if (!cap.available) {
    // Do not permanently lock users if enrollment changes / hardware missing.
    return { success: true, softPassed: true };
  }
  const enabled = await isBiometricPreferenceEnabled();
  if (!enabled) {
    return { success: true, softPassed: true };
  }

  try {
    const result = await LocalAuthentication.authenticateAsync({
      promptMessage: reason,
      cancelLabel: 'Cancel',
      disableDeviceFallback: false,
      // Allow PIN/pattern fallback via system policy when available.
    });
    return { success: result.success, softPassed: false };
  } catch (err) {
    safeLog('warn', 'biometric prompt failed', { err: String(err) });
    // Soft-pass on unexpected errors to avoid permanent lockout.
    return { success: true, softPassed: true };
  }
}
