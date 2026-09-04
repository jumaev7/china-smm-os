import React from 'react';
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import { useTheme } from '@/hooks/useTheme';
import { userFacingMessage } from '@/utils/errors';

export function ScreenState({
  loading,
  error,
  empty,
  emptyMessage = 'Nothing needs attention',
  onRetry,
  children,
}: {
  loading?: boolean;
  error?: unknown;
  empty?: boolean;
  emptyMessage?: string;
  onRetry?: () => void;
  children: React.ReactNode;
}) {
  const colors = useTheme();

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator color={colors.accent} size="large" />
      </View>
    );
  }

  if (error) {
    return (
      <View style={styles.center}>
        <Text style={[styles.title, { color: colors.text }]}>Could not load</Text>
        <Text style={[styles.body, { color: colors.textSecondary }]}>
          {userFacingMessage(error)}
        </Text>
        {onRetry ? (
          <Pressable
            onPress={onRetry}
            style={[styles.retry, { backgroundColor: colors.accent }]}
          >
            <Text style={styles.retryText}>Retry</Text>
          </Pressable>
        ) : null}
      </View>
    );
  }

  if (empty) {
    return (
      <View style={styles.center}>
        <Text style={[styles.body, { color: colors.textMuted }]}>{emptyMessage}</Text>
        {onRetry ? (
          <Pressable
            onPress={onRetry}
            style={[styles.retry, { backgroundColor: colors.surfaceMuted }]}
          >
            <Text style={{ color: colors.text, fontWeight: '600' }}>Refresh</Text>
          </Pressable>
        ) : null}
      </View>
    );
  }

  return <>{children}</>;
}

const styles = StyleSheet.create({
  center: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 24,
    gap: 10,
  },
  title: {
    fontSize: 17,
    fontWeight: '700',
  },
  body: {
    fontSize: 14,
    textAlign: 'center',
    lineHeight: 20,
  },
  retry: {
    marginTop: 8,
    minHeight: 44,
    minWidth: 120,
    borderRadius: 8,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 16,
  },
  retryText: {
    color: '#fff',
    fontWeight: '700',
  },
});
