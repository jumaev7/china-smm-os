import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { ActionButtons } from '@/components/ActionButtons';
import type { ActionExecutionContext } from '@/api/guard';
import { PriorityBadge } from '@/components/StatusBadge';
import { useTheme } from '@/hooks/useTheme';
import type {
  OperatorAttentionItem,
  OperatorWorkspaceAction,
} from '@/types/workspace';
import { formatRelativeAge } from '@/utils/format';

/** Sanitize free-text fields — never show tokens / paths / secrets. */
function safePreview(text: string | null | undefined, max = 160): string {
  if (!text) return '';
  if (/token|authorization|secret|password|\/home\/|\/var\/|postgres:\/\//i.test(text)) {
    return '[redacted]';
  }
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

export function AttentionCard({
  item,
  executionContext = 'readonly',
  submitting = false,
  onExecuteAction,
}: {
  item: OperatorAttentionItem;
  executionContext?: ActionExecutionContext;
  submitting?: boolean;
  onExecuteAction?: (action: OperatorWorkspaceAction) => void;
}) {
  const colors = useTheme();

  return (
    <View
      style={[
        styles.card,
        { backgroundColor: colors.surface, borderColor: colors.border },
      ]}
    >
      <View style={styles.header}>
        <PriorityBadge priority={item.priority} />
        <Text style={[styles.age, { color: colors.textMuted }]}>
          {formatRelativeAge(item.created_at)}
        </Text>
      </View>

      <Text style={[styles.client, { color: colors.accent }]}>
        {item.company_name || 'Client'}
      </Text>
      <Text style={[styles.title, { color: colors.text }]}>{item.title}</Text>
      <Text style={[styles.reason, { color: colors.textSecondary }]}>
        {safePreview(item.reason)}
      </Text>

      <View style={styles.metaRow}>
        <Text style={[styles.meta, { color: colors.textMuted }]}>
          {item.attention_type.replace(/_/g, ' ')}
        </Text>
        {item.current_state ? (
          <Text style={[styles.meta, { color: colors.textMuted }]}>
            · {item.current_state}
          </Text>
        ) : null}
        {item.source_domain ? (
          <Text style={[styles.meta, { color: colors.textMuted }]}>
            · {item.source_domain}
          </Text>
        ) : null}
      </View>

      <ActionButtons
        actions={item.actions ?? []}
        attentionId={item.id}
        executionContext={executionContext}
        submitting={submitting}
        onExecute={onExecuteAction}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    borderWidth: 1,
    borderRadius: 10,
    padding: 14,
    marginBottom: 12,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  age: {
    fontSize: 12,
  },
  client: {
    fontSize: 12,
    fontWeight: '700',
    marginBottom: 2,
    textTransform: 'uppercase',
    letterSpacing: 0.3,
  },
  title: {
    fontSize: 16,
    fontWeight: '700',
    marginBottom: 4,
  },
  reason: {
    fontSize: 14,
    lineHeight: 20,
  },
  metaRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    marginTop: 8,
    gap: 4,
  },
  meta: {
    fontSize: 12,
  },
});
