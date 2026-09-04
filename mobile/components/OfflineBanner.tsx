import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { useTheme } from '@/hooks/useTheme';

export function OfflineBanner({ visible }: { visible: boolean }) {
  const colors = useTheme();
  if (!visible) return null;
  return (
    <View style={[styles.banner, { backgroundColor: colors.banner }]}>
      <Text style={[styles.text, { color: colors.bannerText }]}>
        Offline — showing last known data when available
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  banner: {
    paddingHorizontal: 14,
    paddingVertical: 8,
  },
  text: {
    fontSize: 13,
    fontWeight: '600',
    textAlign: 'center',
  },
});
