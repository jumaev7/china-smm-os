import React from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';
import { Redirect } from 'expo-router';

import { useAuth } from '@/auth/AuthContext';
import { useTheme } from '@/hooks/useTheme';

export default function LockScreen() {
  const colors = useTheme();
  const { status, unlock } = useAuth();
  const [busy, setBusy] = React.useState(false);

  if (status === 'authenticated') {
    return <Redirect href="/(tabs)/today" />;
  }
  if (status === 'unauthenticated') {
    return <Redirect href="/login" />;
  }

  return (
    <View style={[styles.root, { backgroundColor: colors.bg }]}>
      <Text style={[styles.title, { color: colors.text }]}>Session locked</Text>
      <Text style={[styles.body, { color: colors.textSecondary }]}>
        Unlock with biometrics to continue. This does not re-authenticate with
        the server.
      </Text>
      <Pressable
        onPress={async () => {
          setBusy(true);
          try {
            await unlock();
          } finally {
            setBusy(false);
          }
        }}
        style={[styles.btn, { backgroundColor: colors.accent }]}
      >
        {busy ? (
          <ActivityIndicator color="#fff" />
        ) : (
          <Text style={styles.btnText}>Unlock</Text>
        )}
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 24,
    gap: 12,
  },
  title: { fontSize: 22, fontWeight: '800' },
  body: { fontSize: 14, textAlign: 'center', lineHeight: 20, marginBottom: 8 },
  btn: {
    minHeight: 48,
    minWidth: 160,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 20,
  },
  btnText: { color: '#fff', fontWeight: '700', fontSize: 16 },
});
