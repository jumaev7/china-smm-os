import React from 'react';
import { StyleSheet, ViewStyle } from 'react-native';
import { SafeAreaView, type Edge } from 'react-native-safe-area-context';

type ScreenVariant = 'tabs' | 'fullscreen';

const EDGES: Record<ScreenVariant, readonly Edge[]> = {
  // Tab bar already respects the home indicator — avoid double bottom inset.
  tabs: ['top', 'left', 'right'],
  fullscreen: ['top', 'right', 'bottom', 'left'],
};

/**
 * Canonical safe-area shell for operator screens.
 * Uses react-native-safe-area-context (already provided by Expo Router).
 */
export function Screen({
  children,
  variant = 'tabs',
  style,
  testID,
}: {
  children: React.ReactNode;
  variant?: ScreenVariant;
  style?: ViewStyle;
  testID?: string;
}) {
  return (
    <SafeAreaView
      edges={[...EDGES[variant]]}
      style={[styles.root, style]}
      testID={testID}
    >
      {children}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
  },
});
