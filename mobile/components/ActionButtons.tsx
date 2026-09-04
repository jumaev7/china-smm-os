import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { MOBILE_MUTATIONS_ENABLED } from '@/config/constants';
import { useTheme } from '@/hooks/useTheme';
import type { OperatorWorkspaceAction } from '@/types/workspace';
import { isMutationActionId } from '@/api/guard';

/**
 * Renders backend-provided actions[] metadata.
 * All mutation controls are visually present but non-executable in Phase 2.
 */
export function ActionButtons({
  actions,
  onDisabledPress,
}: {
  actions: OperatorWorkspaceAction[];
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
        const isMutation = isMutationActionId(action.action_id);
        const blocked = !MOBILE_MUTATIONS_ENABLED || isMutation || !action.enabled;
        const showPhaseNote = isMutation || !MOBILE_MUTATIONS_ENABLED;

        return (
          <View key={`${action.action_id}-${action.label}`} style={styles.row}>
            <Pressable
              disabled
              accessibilityState={{ disabled: true }}
              onPress={() => onDisabledPress?.(action)}
              style={[
                styles.btn,
                {
                  backgroundColor: colors.surfaceMuted,
                  borderColor: colors.border,
                  opacity: 0.75,
                },
              ]}
            >
              <Text style={[styles.btnText, { color: colors.disabled }]}>
                {action.label}
              </Text>
            </Pressable>
            <View style={styles.meta}>
              <Text style={[styles.metaText, { color: colors.textMuted }]}>
                id={action.action_id} · tier={action.confirmation_tier}
                {action.requires_confirmation ? ' · confirm' : ''}
                {action.external_side_effect ? ' · external' : ''}
                {action.destructive ? ' · destructive' : ''}
              </Text>
              {showPhaseNote || blocked ? (
                <Text style={[styles.phase, { color: colors.warning }]}>
                  Available in next phase
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
