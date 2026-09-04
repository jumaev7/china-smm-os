import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { useTheme } from '@/hooks/useTheme';

export function MetricTile({
  label,
  value,
  tone,
}: {
  label: string;
  value: string | number;
  tone?: 'default' | 'danger' | 'ok';
}) {
  const colors = useTheme();
  const valueColor =
    tone === 'danger' ? colors.danger : tone === 'ok' ? colors.ok : colors.text;

  return (
    <View
      style={[
        styles.tile,
        { backgroundColor: colors.surface, borderColor: colors.border },
      ]}
    >
      <Text style={[styles.value, { color: valueColor }]}>{value}</Text>
      <Text style={[styles.label, { color: colors.textMuted }]}>{label}</Text>
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
});
