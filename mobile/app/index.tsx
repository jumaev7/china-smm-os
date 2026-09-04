import { Redirect } from 'expo-router';

import { useAuth } from '@/auth/AuthContext';

export default function Index() {
  const { status } = useAuth();
  if (status === 'bootstrapping') return null;
  if (status === 'authenticated') return <Redirect href="/(tabs)/today" />;
  if (status === 'locked') return <Redirect href="/lock" />;
  return <Redirect href="/login" />;
}
