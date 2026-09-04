import React from 'react';
import { Redirect, Tabs } from 'expo-router';
import FontAwesome from '@expo/vector-icons/FontAwesome';

import { useAuth } from '@/auth/AuthContext';
import { useRefreshOnForeground } from '@/hooks/useOperatorQueries';
import { useTheme } from '@/hooks/useTheme';

function TabIcon(props: {
  name: React.ComponentProps<typeof FontAwesome>['name'];
  color: string;
}) {
  return <FontAwesome size={22} style={{ marginBottom: -2 }} {...props} />;
}

export default function TabsLayout() {
  const colors = useTheme();
  const { status } = useAuth();
  useRefreshOnForeground();

  if (status === 'bootstrapping') {
    return null;
  }
  if (status === 'unauthenticated') {
    return <Redirect href="/login" />;
  }
  if (status === 'locked') {
    return <Redirect href="/lock" />;
  }

  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: colors.accent,
        tabBarInactiveTintColor: colors.textMuted,
        tabBarStyle: {
          backgroundColor: colors.surface,
          borderTopColor: colors.border,
        },
      }}
    >
      <Tabs.Screen
        name="today"
        options={{
          title: 'Today',
          tabBarIcon: ({ color }) => (
            <TabIcon name="sun-o" color={String(color)} />
          ),
        }}
      />
      <Tabs.Screen
        name="approvals"
        options={{
          title: 'Approvals',
          tabBarIcon: ({ color }) => (
            <TabIcon name="check-square-o" color={String(color)} />
          ),
        }}
      />
      <Tabs.Screen
        name="problems"
        options={{
          title: 'Problems',
          tabBarIcon: ({ color }) => (
            <TabIcon name="exclamation-triangle" color={String(color)} />
          ),
        }}
      />
      <Tabs.Screen
        name="system"
        options={{
          title: 'System',
          tabBarIcon: ({ color }) => (
            <TabIcon name="heartbeat" color={String(color)} />
          ),
        }}
      />
      <Tabs.Screen
        name="settings"
        options={{
          title: 'Profile',
          tabBarIcon: ({ color }) => (
            <TabIcon name="user-o" color={String(color)} />
          ),
        }}
      />
    </Tabs>
  );
}
