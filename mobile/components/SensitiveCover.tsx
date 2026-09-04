import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { useTheme } from '@/hooks/useTheme';

/**
 * Optional blur overlay when app is backgrounded / locked.
 * Uses an opaque cover (no BlurView dependency) for Expo Go friendliness.
 */
export function SensitiveCover({ visible, message }: { visible: boolean; message?: string }) {
  const colors = useTheme();
  if (!visible) return null;
  return (
    <View
      style={[styles.cover, { backgroundColor: colors.bg }]}
      pointerEvents="auto"
      accessibilityViewIsModal
    >
      <Text style={[styles.title, { color: colors.text }]}>Locked</Text>
      <Text style={[styles.body, { color: colors.textSecondary }]}>
        {message ?? 'Authenticate to continue'}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  cover: {
    position: 'absolute',
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
    zIndex: 100,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 24,
  },
  title: {
    fontSize: 22,
    fontWeight: '800',
    marginBottom: 8,
  },
  body: {
    fontSize: 15,
    textAlign: 'center',
  },
});
