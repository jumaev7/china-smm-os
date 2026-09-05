import { useCallback, useRef, useState } from 'react';
import { Alert } from 'react-native';
import { useQueryClient } from '@tanstack/react-query';

import { acknowledgeAlert } from '@/api/mutations';
import { isMobileMutationAllowed } from '@/api/guard';
import { useAuth } from '@/auth/AuthContext';
import { getAccessToken } from '@/auth/tokenMemory';
import { queryKeys } from '@/hooks/useOperatorQueries';
import { useNetworkStatus } from '@/hooks/useNetworkStatus';
import type { OperatorWorkspaceAction } from '@/types/workspace';
import { confirmAcknowledgeAlert } from '@/utils/confirmAction';
import { AppError, userFacingMessage } from '@/utils/errors';

async function invalidateOperatorReads(
  client: ReturnType<typeof useQueryClient>,
): Promise<void> {
  await Promise.all([
    client.invalidateQueries({ queryKey: queryKeys.problems }),
    client.invalidateQueries({ queryKey: queryKeys.home }),
  ]);
}

function mutationOutcomeMessage(error: unknown): string {
  if (error instanceof AppError) {
    if (error.kind === 'conflict' || error.status === 409) {
      return 'This item changed since it was loaded. The latest state has been refreshed.';
    }
    if (error.status === 404) {
      return 'This item is no longer available. The list has been refreshed.';
    }
    if (error.kind === 'forbidden') {
      return 'You do not have permission for this action.';
    }
    if (error.kind === 'rate_limited') {
      return 'Too many requests. Please wait and try again later.';
    }
    if (
      error.kind === 'network' ||
      error.kind === 'timeout' ||
      error.kind === 'offline' ||
      error.kind === 'server'
    ) {
      return (
        'Could not confirm the result. Pull to refresh and review the item ' +
        'before trying again. The action was not resent.'
      );
    }
  }
  return userFacingMessage(error);
}

/**
 * Phase 3B acknowledge_alert execution — Problems screen only.
 * No optimistic state, no automatic retry/replay, per-item in-flight lock.
 */
export function useAcknowledgeAlert() {
  const queryClient = useQueryClient();
  const { isOffline } = useNetworkStatus();
  const { status } = useAuth();
  const inFlightRef = useRef(new Set<string>());
  const [inFlightIds, setInFlightIds] = useState<ReadonlySet<string>>(
    () => new Set(),
  );

  const isInFlight = useCallback(
    (attentionId: string) => inFlightIds.has(attentionId),
    [inFlightIds],
  );

  const runAcknowledge = useCallback(
    async (attentionId: string, action: OperatorWorkspaceAction) => {
      // Eligibility: backend action_id only — never invent from severity/status.
      if (action.action_id !== 'acknowledge_alert') return;
      if (!action.enabled) return;
      if (!isMobileMutationAllowed('acknowledge_alert')) {
        Alert.alert('Unavailable', 'Acknowledge is not enabled on this build.');
        return;
      }
      if (isOffline) {
        Alert.alert('Offline', 'Acknowledge is unavailable while offline.');
        return;
      }
      if (status !== 'authenticated' || !getAccessToken()) {
        Alert.alert('Session', 'Sign in again before acknowledging.');
        return;
      }
      // Double-tap / per-item in-flight lock.
      if (inFlightRef.current.has(attentionId)) return;

      const accepted = await confirmAcknowledgeAlert(action);
      if (!accepted) return;

      inFlightRef.current.add(attentionId);
      setInFlightIds(new Set(inFlightRef.current));

      try {
        const result = await acknowledgeAlert(attentionId);
        // Refetch canonical state — do not synthesize local acknowledged.
        // Acknowledged alerts may remain in attention; do not remove locally.
        await invalidateOperatorReads(queryClient);
        Alert.alert(
          'Alert acknowledged',
          result.message?.trim() || 'Alert acknowledged',
        );
      } catch (err) {
        const shouldRefresh =
          err instanceof AppError &&
          (err.kind === 'conflict' ||
            err.status === 409 ||
            err.status === 404 ||
            err.kind === 'network' ||
            err.kind === 'timeout' ||
            err.kind === 'server');

        if (shouldRefresh) {
          await invalidateOperatorReads(queryClient);
        }

        Alert.alert('Could not acknowledge', mutationOutcomeMessage(err));
        // Explicitly no automatic retry / replay.
      } finally {
        inFlightRef.current.delete(attentionId);
        setInFlightIds(new Set(inFlightRef.current));
      }
    },
    [isOffline, queryClient, status],
  );

  return { runAcknowledge, isInFlight };
}
