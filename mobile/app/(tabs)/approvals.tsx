import React from 'react';
import { RefreshControl, ScrollView, StyleSheet, Text } from 'react-native';

import { AttentionCard } from '@/components/AttentionCard';
import { OfflineBanner } from '@/components/OfflineBanner';
import { Screen } from '@/components/Screen';
import { ScreenState } from '@/components/ScreenState';
import { useApproveContent } from '@/hooks/useApproveContent';
import { useApprovals } from '@/hooks/useOperatorQueries';
import { useNetworkStatus } from '@/hooks/useNetworkStatus';
import { useTheme } from '@/hooks/useTheme';
import { isNetworkLikeError } from '@/utils/errors';

export default function ApprovalsScreen() {
  const colors = useTheme();
  const { isOffline } = useNetworkStatus();
  const query = useApprovals();
  const { runApprove, isInFlight } = useApproveContent();
  const items = query.data?.items ?? [];
  const showOffline = isOffline || isNetworkLikeError(query.error);

  return (
    <Screen style={{ backgroundColor: colors.bg }} testID="approvals-screen">
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
          Internal content review — approve when offered by the backend
        </Text>

        <ScreenState
          loading={query.isLoading && !query.data}
          error={!query.data ? query.error : null}
          empty={!!query.data && items.length === 0}
          emptyMessage="No approvals waiting"
          onRetry={() => void query.refetch()}
        >
          {items.map((item) => (
            <AttentionCard
              key={item.id}
              item={item}
              executionContext="approvals"
              submitting={isInFlight(item.id)}
              onExecuteAction={(action) => {
                void runApprove(item.id, action);
              }}
            />
          ))}
        </ScreenState>
      </ScrollView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  content: { padding: 16, paddingBottom: 40 },
  heading: { fontSize: 28, fontWeight: '800' },
  sub: { marginTop: 4, marginBottom: 16, fontSize: 13 },
});
