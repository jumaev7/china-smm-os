import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Stack } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import React, { useEffect, useState } from 'react';
import { ActivityIndicator, View } from 'react-native';
import 'react-native-reanimated';

import { AuthProvider, useAuth } from '@/auth/AuthContext';
import { AppThemeProvider, useTheme } from '@/hooks/useTheme';
import { QUERY_STALE_TIME_MS } from '@/config/constants';

export { ErrorBoundary } from 'expo-router';

SplashScreen.preventAutoHideAsync();

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: QUERY_STALE_TIME_MS,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

function BootGate({ children }: { children: React.ReactNode }) {
  const { status } = useAuth();
  const colors = useTheme();

  useEffect(() => {
    if (status !== 'bootstrapping') {
      void SplashScreen.hideAsync();
    }
  }, [status]);

  if (status === 'bootstrapping') {
    return (
      <View
        style={{
          flex: 1,
          alignItems: 'center',
          justifyContent: 'center',
          backgroundColor: colors.bg,
        }}
      >
        <ActivityIndicator color={colors.accent} size="large" />
      </View>
    );
  }

  return <>{children}</>;
}

export default function RootLayout() {
  const [ready] = useState(true);

  if (!ready) return null;

  return (
    <QueryClientProvider client={queryClient}>
      <AppThemeProvider>
        <AuthProvider>
          <BootGate>
            <Stack screenOptions={{ headerShown: false }}>
              <Stack.Screen name="index" />
              <Stack.Screen name="login" />
              <Stack.Screen name="lock" />
              <Stack.Screen name="(tabs)" />
            </Stack>
          </BootGate>
        </AuthProvider>
      </AppThemeProvider>
    </QueryClientProvider>
  );
}
