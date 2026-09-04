import { useEffect, useState } from 'react';
import NetInfo from '@react-native-community/netinfo';

export function useNetworkStatus(): { isOffline: boolean; isUnknown: boolean } {
  const [isOffline, setIsOffline] = useState(false);
  const [isUnknown, setIsUnknown] = useState(true);

  useEffect(() => {
    const unsub = NetInfo.addEventListener((state) => {
      const offline =
        state.isConnected === false || state.isInternetReachable === false;
      setIsOffline(offline);
      setIsUnknown(state.isConnected == null);
    });
    return () => unsub();
  }, []);

  return { isOffline, isUnknown };
}
