import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { useTheme } from '@/hooks/useTheme';

export function MetricTile({
  label,
  value,
  tone,
  onPress,
  testID,
}: {
  label: string;
  value: string | number;
  tone?: 'default' | 'danger' | 'ok';
  /** When set, tile is a Pressable with pressed feedback. */
  onPress?: () => void;
  testID?: string;
}) {
  const colors = useTheme();
  const valueColor =
    tone === 'danger' ? colors.danger : tone === 'ok' ? colors.ok : colors.text;
  const interactive = typeof onPress === 'function';
  const a11yLabel = `${label}: ${value}`;

  const body = (
    <>
      <Text style={[styles.value, { color: valueColor }]}>{value}</Text>
      <Text style={[styles.label, { color: colors.textMuted }]}>{label}</Text>
    </>
  );

  if (interactive) {
    return (
      <Pressable
        testID={testID}
        onPress={onPress}
        accessibilityRole="button"
        accessibilityLabel={a11yLabel}
        style={({ pressed }) => [
          styles.tile,
          {
            backgroundColor: colors.surface,
            borderColor: colors.border,
            opacity: pressed ? 0.7 : 1,
            transform: [{ scale: pressed ? 0.98 : 1 }],
          },
        ]}
      >
        {body}
      </Pressable>
    );
  }

  return (
    <View
      testID={testID}
      accessibilityRole="text"
      accessibilityLabel={a11yLabel}
      accessibilityState={{ disabled: true }}
      style={[
        styles.tile,
        styles.tileStatic,
        {
          backgroundColor: colors.surfaceMuted,
          borderColor: colors.border,
        },
      ]}
    >
      {body}
      <Text style={[styles.staticHint, { color: colors.textMuted }]}>
        View only
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  tile: {
    flex: 1,
    minWidth: '45%',
    borderWidth: 1,
    borderRadius: 10,
    paddingVertical: 14,
    paddingHorizontal: 12,
  },
  tileStatic: {
    opacity: 0.85,
  },
  value: {
    fontSize: 24,
    fontWeight: '800',
  },
  label: {
    marginTop: 4,
    fontSize: 12,
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: 0.3,
  },
  staticHint: {
    marginTop: 6,
    fontSize: 10,
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: 0.2,
  },
});
