import React from 'react';
import { RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';

import { AttentionCard } from '@/components/AttentionCard';
import { OfflineBanner } from '@/components/OfflineBanner';
import { ScreenState } from '@/components/ScreenState';
import { useApprovals } from '@/hooks/useOperatorQueries';
import { useNetworkStatus } from '@/hooks/useNetworkStatus';
import { useTheme } from '@/hooks/useTheme';
import { isNetworkLikeError } from '@/utils/errors';

export default function ApprovalsScreen() {
  const colors = useTheme();
  const { isOffline } = useNetworkStatus();
  const query = useApprovals();
  const items = query.data?.items ?? [];
  const showOffline = isOffline || isNetworkLikeError(query.error);

  return (
    <View style={[styles.root, { backgroundColor: colors.bg }]}>
      <OfflineBanner visible={showOffline && items.length > 0} />
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={
          <RefreshControl
            refreshing={query.isRefetching}
            onRefresh={() => void query.refetch()}
            tintColor={colors.accent}
          />
        }
      >
        <Text style={[styles.heading, { color: colors.text }]}>Approvals</Text>
        <Text style={[styles.sub, { color: colors.textMuted }]}>
          Internal content review — actions display-only
        </Text>

        <ScreenState
          loading={query.isLoading && !query.data}
          error={!query.data ? query.error : null}
          empty={!!query.data && items.length === 0}
          emptyMessage="No approvals waiting"
          onRetry={() => void query.refetch()}
        >
          {items.map((item) => (
            <AttentionCard key={item.id} item={item} />
          ))}
        </ScreenState>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  content: { padding: 16, paddingBottom: 40 },
  heading: { fontSize: 28, fontWeight: '800' },
  sub: { marginTop: 4, marginBottom: 16, fontSize: 13 },
});
