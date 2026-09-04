import React, { createContext, useContext, useMemo } from 'react';
import { useColorScheme } from 'react-native';

import { palette, type ThemeColors } from '@/constants/theme';

const ThemeContext = createContext<ThemeColors>(palette.light);

export function AppThemeProvider({ children }: { children: React.ReactNode }) {
  const scheme = useColorScheme();
  const colors = useMemo<ThemeColors>(
    () => (scheme === 'dark' ? { ...palette.dark } : { ...palette.light }),
    [scheme],
  );
  return <ThemeContext.Provider value={colors}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeColors {
  return useContext(ThemeContext);
}
