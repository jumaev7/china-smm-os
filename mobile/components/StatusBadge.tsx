import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { priorityColor } from '@/constants/theme';
import { useTheme } from '@/hooks/useTheme';

export function PriorityBadge({ priority }: { priority: string }) {
  const colors = useTheme();
  const fg = priorityColor(colors, priority);
  return (
    <View style={[styles.badge, { borderColor: fg }]}>
      <Text style={[styles.text, { color: fg }]}>{priority.toUpperCase()}</Text>
    </View>
  );
}

export function StatusChip({ label, tone }: { label: string; tone?: string }) {
  const colors = useTheme();
  const color =
    tone === 'ok'
      ? colors.ok
      : tone === 'danger'
        ? colors.danger
        : tone === 'warning'
          ? colors.warning
          : colors.textMuted;
  return (
    <View style={[styles.chip, { backgroundColor: colors.surfaceMuted }]}>
      <View style={[styles.dot, { backgroundColor: color }]} />
      <Text style={[styles.chipText, { color: colors.text }]}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  badge: {
    borderWidth: 1,
    borderRadius: 4,
    paddingHorizontal: 8,
    paddingVertical: 2,
  },
  text: {
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 0.4,
  },
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    borderRadius: 6,
    paddingHorizontal: 10,
    paddingVertical: 6,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  chipText: {
    fontSize: 13,
    fontWeight: '600',
  },
});
