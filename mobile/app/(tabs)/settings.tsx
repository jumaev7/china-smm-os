import React, { useEffect, useState } from 'react';
import { Pressable, StyleSheet, Switch, Text, View } from 'react-native';

import { useAuth } from '@/auth/AuthContext';
import {
  getBiometricCapability,
  isBiometricPreferenceEnabled,
  setBiometricPreference,
} from '@/auth/biometrics';
import { Screen } from '@/components/Screen';
import {
  MOBILE_APPROVE_CONTENT_ENABLED,
  MOBILE_MUTATIONS_UNLOCK_ALL,
} from '@/config/constants';
import { getApiBaseUrl } from '@/config/env';
import { useTheme } from '@/hooks/useTheme';

export default function SettingsScreen() {
  const colors = useTheme();
  const { user, tenant, logout } = useAuth();
  const [bioEnabled, setBioEnabled] = useState(true);
  const [bioAvailable, setBioAvailable] = useState(false);

  useEffect(() => {
    void (async () => {
      const cap = await getBiometricCapability();
      setBioAvailable(cap.available);
      setBioEnabled(await isBiometricPreferenceEnabled());
    })();
  }, []);

  return (
    <Screen style={{ backgroundColor: colors.bg }} testID="profile-screen">
      <View style={styles.inner}>
        <Text style={[styles.heading, { color: colors.text }]}>Profile</Text>

        <View
          style={[
            styles.card,
            { backgroundColor: colors.surface, borderColor: colors.border },
          ]}
        >
          <Text style={[styles.label, { color: colors.textMuted }]}>User</Text>
          <Text style={[styles.value, { color: colors.text }]}>
            {user?.email ?? '—'}
          </Text>
          <Text style={[styles.label, { color: colors.textMuted }]}>Role</Text>
          <Text style={[styles.value, { color: colors.text }]}>
            {user?.role ?? '—'}
          </Text>
          <Text style={[styles.label, { color: colors.textMuted }]}>Tenant</Text>
          <Text style={[styles.value, { color: colors.text }]}>
            {tenant?.company_name ?? '—'}
          </Text>
          <Text style={[styles.hint, { color: colors.textMuted }]}>
            Tenant scope comes from the authenticated session — never from a
            client-supplied tenant_id.
          </Text>
        </View>

        <View
          style={[
            styles.card,
            { backgroundColor: colors.surface, borderColor: colors.border },
          ]}
        >
          <View style={styles.row}>
            <View style={{ flex: 1 }}>
              <Text style={[styles.value, { color: colors.text }]}>
                Biometric lock
              </Text>
              <Text style={[styles.hint, { color: colors.textMuted }]}>
                {bioAvailable
                  ? 'Local unlock after background — not API auth'
                  : 'Biometrics unavailable on this device'}
              </Text>
            </View>
            <Switch
              value={bioEnabled && bioAvailable}
              disabled={!bioAvailable}
              onValueChange={async (v) => {
                setBioEnabled(v);
                await setBiometricPreference(v);
              }}
            />
          </View>
        </View>

        <View
          style={[
            styles.card,
            { backgroundColor: colors.surface, borderColor: colors.border },
          ]}
        >
          <Text style={[styles.label, { color: colors.textMuted }]}>API</Text>
          <Text style={[styles.value, { color: colors.text }]}>
            {getApiBaseUrl()}
          </Text>
          <Text style={[styles.label, { color: colors.textMuted }]}>
            Mutations
          </Text>
          <Text
            style={[
              styles.value,
              {
                color: MOBILE_MUTATIONS_UNLOCK_ALL
                  ? colors.danger
                  : MOBILE_APPROVE_CONTENT_ENABLED
                    ? colors.warning
                    : colors.ok,
              },
            ]}
          >
            {MOBILE_MUTATIONS_UNLOCK_ALL
              ? 'UNLOCK ALL (unexpected)'
              : MOBILE_APPROVE_CONTENT_ENABLED
                ? 'approve_content only (Phase 3A allowlist)'
                : 'Disabled'}
          </Text>
          <Text style={[styles.hint, { color: colors.textMuted }]}>
            Kill switch / allowlist gate; unlock-all stays off. Push not implemented.
          </Text>
        </View>

        <Pressable
          onPress={() => void logout()}
          style={[styles.logout, { backgroundColor: colors.dangerSoft }]}
        >
          <Text style={[styles.logoutText, { color: colors.danger }]}>
            Sign out
          </Text>
        </Pressable>
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  inner: { flex: 1, padding: 16, gap: 12 },
  heading: { fontSize: 28, fontWeight: '800', marginBottom: 4 },
  card: {
    borderWidth: 1,
    borderRadius: 10,
    padding: 14,
    gap: 4,
  },
  label: {
    fontSize: 11,
    fontWeight: '700',
    textTransform: 'uppercase',
    letterSpacing: 0.4,
    marginTop: 6,
  },
  value: { fontSize: 15, fontWeight: '600' },
  hint: { fontSize: 12, marginTop: 4, lineHeight: 16 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  logout: {
    marginTop: 8,
    minHeight: 48,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
  },
  logoutText: { fontSize: 16, fontWeight: '700' },
});
