import React from 'react';
import { RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';

import { OfflineBanner } from '@/components/OfflineBanner';
import { ScreenState } from '@/components/ScreenState';
import { StatusChip } from '@/components/StatusBadge';
import { useMobileSystem } from '@/hooks/useOperatorQueries';
import { useNetworkStatus } from '@/hooks/useNetworkStatus';
import { useTheme } from '@/hooks/useTheme';
import { statusColor } from '@/constants/theme';
import { formatLastUpdated, formatUptime } from '@/utils/format';
import { isNetworkLikeError } from '@/utils/errors';

function Row({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  const colors = useTheme();
  return (
    <View
      style={[
        styles.row,
        { backgroundColor: colors.surface, borderColor: colors.border },
      ]}
    >
      <Text style={[styles.label, { color: colors.textMuted }]}>{label}</Text>
      <Text
        style={[
          styles.value,
          { color: tone ? statusColor(colors, tone) : colors.text },
        ]}
      >
        {value}
      </Text>
    </View>
  );
}

export default function SystemScreen() {
  const colors = useTheme();
  const { isOffline } = useNetworkStatus();
  const query = useMobileSystem();
  const status = query.data?.system_status;
  const showOffline = isOffline || isNetworkLikeError(query.error);

  const backupLabel = (() => {
    if (!status) return '—';
    if (status.backup.status === 'unavailable') {
      return 'Backup status not available in mobile control plane';
    }
    return status.backup.status;
  })();

  return (
    <View style={[styles.root, { backgroundColor: colors.bg }]}>
      <OfflineBanner visible={showOffline && !!status} />
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
        <Text style={[styles.heading, { color: colors.text }]}>System</Text>
        <Text style={[styles.updated, { color: colors.textMuted }]}>
          {formatLastUpdated(query.data?.generated_at)}
          {showOffline && status ? ' · cached' : ''}
        </Text>

        <ScreenState
          loading={query.isLoading && !query.data}
          error={!query.data ? query.error : null}
          onRetry={() => void query.refetch()}
        >
          {status ? (
            <>
              <View style={styles.overall}>
                <StatusChip
                  label={`Overall ${status.overall}`}
                  tone={
                    status.overall === 'ok'
                      ? 'ok'
                      : status.overall === 'degraded'
                        ? 'danger'
                        : 'warning'
                  }
                />
              </View>

              <Row label="API" value={status.api} tone={status.api} />
              <Row label="Database" value={status.database} tone={status.database} />
              <Row label="Scheduler" value={status.scheduler} tone={status.scheduler} />
              <Row
                label="Integration Health"
                value={`${status.integration_attention_count} need attention`}
                tone={status.integration_attention_count > 0 ? 'degraded' : 'ok'}
              />
              <Row
                label="AI services"
                value={status.ai_services}
                tone={status.ai_services}
              />
              <Row
                label="Telegram"
                value={status.telegram_bot}
                tone={status.telegram_bot}
              />
              <Row label="Uptime" value={formatUptime(status.uptime_seconds)} />
              <Row label="Backup" value={backupLabel} />

              {status.notes?.length ? (
                <View style={styles.notes}>
                  <Text style={[styles.notesTitle, { color: colors.text }]}>
                    Notes
                  </Text>
                  {status.notes.map((n) => (
                    <Text
                      key={n}
                      style={[styles.note, { color: colors.textSecondary }]}
                    >
                      · {n}
                    </Text>
                  ))}
                </View>
              ) : null}
            </>
          ) : null}
        </ScreenState>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  content: { padding: 16, paddingBottom: 40, gap: 10 },
  heading: { fontSize: 28, fontWeight: '800' },
  updated: { marginTop: 4, marginBottom: 8, fontSize: 13 },
  overall: { marginBottom: 8 },
  row: {
    borderWidth: 1,
    borderRadius: 10,
    padding: 14,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: 12,
  },
  label: {
    fontSize: 13,
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: 0.3,
    flexShrink: 0,
  },
  value: {
    fontSize: 14,
    fontWeight: '700',
    textAlign: 'right',
    flex: 1,
  },
  notes: { marginTop: 12, gap: 6 },
  notesTitle: { fontSize: 16, fontWeight: '700' },
  note: { fontSize: 13, lineHeight: 18 },
});
