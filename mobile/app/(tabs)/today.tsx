import React from 'react';
import {
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { router } from 'expo-router';

import { AttentionCard } from '@/components/AttentionCard';
import { MetricTile } from '@/components/MetricTile';
import { OfflineBanner } from '@/components/OfflineBanner';
import { Screen } from '@/components/Screen';
import { ScreenState } from '@/components/ScreenState';
import { StatusChip } from '@/components/StatusBadge';
import { useMobileHome } from '@/hooks/useOperatorQueries';
import { useNetworkStatus } from '@/hooks/useNetworkStatus';
import { useTheme } from '@/hooks/useTheme';
import {
  resolveDashboardCardNavigation,
  type DashboardCardId,
} from '@/utils/dashboardNavigation';
import { formatLastUpdated } from '@/utils/format';
import { isNetworkLikeError } from '@/utils/errors';

function navigateDashboardCard(card: DashboardCardId): void {
  const target = resolveDashboardCardNavigation(card);
  if (target.navigable) {
    router.navigate(target.href);
  }
}

export default function TodayScreen() {
  const colors = useTheme();
  const { isOffline } = useNetworkStatus();
  const query = useMobileHome();
  const data = query.data;
  const showOffline = isOffline || isNetworkLikeError(query.error);
  return (
    <Screen style={{ backgroundColor: colors.bg }} testID="today-screen">
      <OfflineBanner visible={showOffline && !!data} />
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
        <Text style={[styles.heading, { color: colors.text }]}>Today</Text>
        <Text style={[styles.updated, { color: colors.textMuted }]}>
          {formatLastUpdated(data?.last_updated_at)}
          {showOffline && data ? ' · cached' : ''}
        </Text>

        <ScreenState
          loading={query.isLoading && !data}
          error={!data ? query.error : null}
          onRetry={() => void query.refetch()}
        >
          {data ? (
            <>
              <View style={styles.grid}>
                <MetricTile
                  testID="tile-attention"
                  label="Attention"
                  value={data.attention_summary.total}
                  tone={data.attention_summary.total > 0 ? 'danger' : 'ok'}
                  onPress={() => navigateDashboardCard('attention')}
                />
                <MetricTile
                  testID="tile-approvals"
                  label="Approvals"
                  value={data.approvals_count}
                  onPress={() => navigateDashboardCard('approvals')}
                />
                <MetricTile
                  testID="tile-problems"
                  label="Problems"
                  value={data.problems_count}
                  onPress={() => navigateDashboardCard('problems')}
                />
                {/* Waiting: no onPress — no Waiting route; keep visually non-tappable. */}
                <MetricTile
                  testID="tile-waiting"
                  label="Waiting"
                  value={data.waiting_for_client}
                />
              </View>

              <View style={styles.systemRow}>
                <StatusChip
                  testID="chip-system"
                  label={`System ${data.system_status.overall}`}
                  tone={
                    data.system_status.overall === 'ok'
                      ? 'ok'
                      : data.system_status.overall === 'degraded'
                        ? 'danger'
                        : 'warning'
                  }
                  onPress={() => navigateDashboardCard('system')}
                />
                {data.unread_notifications > 0 ? (
                  <StatusChip
                    testID="chip-unread"
                    label={`${data.unread_notifications} unread`}
                    tone="warning"
                  />
                ) : null}
              </View>

              <Text style={[styles.section, { color: colors.text }]}>
                Urgent
              </Text>
              {data.urgent_items.length === 0 ? (
                <Text style={{ color: colors.textMuted }}>
                  No urgent items
                </Text>
              ) : (
                data.urgent_items.map((item) => (
                  <AttentionCard key={item.id} item={item} />
                ))
              )}

              {query.isError ? (
                <Pressable onPress={() => void query.refetch()}>
                  <Text style={{ color: colors.warning, marginTop: 8 }}>
                    Refresh failed — pull to retry
                  </Text>
                </Pressable>
              ) : null}
            </>
          ) : null}
        </ScreenState>
      </ScrollView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  content: { padding: 16, paddingBottom: 40 },
  heading: { fontSize: 28, fontWeight: '800' },
  updated: { marginTop: 4, marginBottom: 16, fontSize: 13 },
  grid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
    marginBottom: 14,
  },
  systemRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginBottom: 18,
  },
  section: {
    fontSize: 18,
    fontWeight: '700',
    marginBottom: 10,
  },
});
