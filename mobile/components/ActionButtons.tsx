import React from 'react';
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import {
  canExecuteMobileAction,
  isMobileMutationAllowed,
} from '@/api/guard';
import { useTheme } from '@/hooks/useTheme';
import type { OperatorWorkspaceAction } from '@/types/workspace';

export type ActionExecutionContext = 'approvals' | 'readonly';

/**
 * Renders backend-provided actions[] metadata.
 * Phase 3A: approve_content is executable only on Approvals when allowlisted
 * and present in backend actions[]. All other mutations stay disabled.
 */
export function ActionButtons({
  actions,
  attentionId,
  executionContext = 'readonly',
  submitting = false,
  onExecute,
  onDisabledPress,
}: {
  actions: OperatorWorkspaceAction[];
  attentionId?: string;
  /** Approvals-only execution; Today/Problems remain read-only. */
  executionContext?: ActionExecutionContext;
  submitting?: boolean;
  onExecute?: (action: OperatorWorkspaceAction) => void;
  onDisabledPress?: (action: OperatorWorkspaceAction) => void;
}) {
  const colors = useTheme();

  if (!actions?.length) {
    return (
      <Text style={[styles.empty, { color: colors.textMuted }]}>No actions</Text>
    );
  }

  return (
    <View style={styles.wrap}>
      {actions.map((action) => {
        const allowlisted = isMobileMutationAllowed(action.action_id);
        const canExecuteHere =
          canExecuteMobileAction({
            actionId: action.action_id,
            enabled: action.enabled,
            executionContext,
          }) &&
          !!attentionId &&
          !!onExecute;

        const executable = canExecuteHere && !submitting;
        // Later-phase note for anything not executable via Phase 3A allowlist.
        // Do not use it when approve is offered but currently disabled by backend.
        const showLaterPhase =
          !canExecuteHere &&
          !(
            allowlisted &&
            action.action_id === 'approve_content' &&
            executionContext === 'approvals'
          );
        return (
          <View key={`${action.action_id}-${action.label}`} style={styles.row}>
            <Pressable
              disabled={!executable}
              accessibilityState={{ disabled: !executable, busy: submitting && canExecuteHere }}
              accessibilityLabel={action.label}
              onPress={() => {
                if (executable) {
                  onExecute?.(action);
                } else {
                  onDisabledPress?.(action);
                }
              }}
              style={[
                styles.btn,
                {
                  backgroundColor: executable
                    ? colors.accent
                    : colors.surfaceMuted,
                  borderColor: executable ? colors.accent : colors.border,
                  opacity: executable ? 1 : 0.75,
                },
              ]}
            >
              {submitting && canExecuteHere ? (
                <ActivityIndicator color="#fff" />
              ) : (
                <Text
                  style={[
                    styles.btnText,
                    { color: executable ? '#fff' : colors.disabled },
                  ]}
                >
                  {action.label}
                </Text>
              )}
            </Pressable>
            <View style={styles.meta}>
              <Text style={[styles.metaText, { color: colors.textMuted }]}>
                id={action.action_id} · tier={action.confirmation_tier}
                {action.requires_confirmation ? ' · confirm' : ''}
                {action.external_side_effect ? ' · external' : ''}
                {action.destructive ? ' · destructive' : ''}
              </Text>
              {canExecuteHere && action.requires_confirmation ? (
                <Text style={[styles.phase, { color: colors.textMuted }]}>
                  Confirmation required
                </Text>
              ) : null}
              {showLaterPhase ? (
                <Text style={[styles.phase, { color: colors.warning }]}>
                  Available in later phase
                </Text>
              ) : null}
              {action.disabled_reason ? (
                <Text style={[styles.metaText, { color: colors.textMuted }]}>
                  {action.disabled_reason}
                </Text>
              ) : null}
            </View>
          </View>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    gap: 10,
    marginTop: 10,
  },
  row: {
    gap: 4,
  },
  btn: {
    minHeight: 44,
    borderWidth: 1,
    borderRadius: 8,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 14,
  },
  btnText: {
    fontSize: 15,
    fontWeight: '600',
  },
  meta: {
    gap: 2,
    paddingHorizontal: 2,
  },
  metaText: {
    fontSize: 11,
    lineHeight: 14,
  },
  phase: {
    fontSize: 11,
    fontWeight: '600',
  },
  empty: {
    fontSize: 12,
    marginTop: 8,
  },
});
