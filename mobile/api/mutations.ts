/**
 * Workspace mutation API — Phase 2 hard-blocked.
 * No HTTP leaves the device while MOBILE_MUTATIONS_ENABLED is false.
 */
import { assertMutationsEnabled } from '@/api/guard';
import { apiRequest } from '@/api/client';

export interface ExecuteActionParams {
  attentionId: string;
  actionId: string;
  note?: string;
}

/**
 * Intentionally unreachable in Phase 2.
 * Tests assert this throws before any fetch.
 */
export async function executeWorkspaceAction(
  params: ExecuteActionParams,
): Promise<never> {
  assertMutationsEnabled(params.actionId);

  // Unreachable while MOBILE_MUTATIONS_ENABLED === false.
  // Kept for Phase 3 wiring — still goes through guard first.
  await apiRequest({
    method: 'POST',
    path: `/operator-workspace/items/${encodeURIComponent(params.attentionId)}/actions/${encodeURIComponent(params.actionId)}`,
    body: {
      note: params.note,
      source: 'mobile',
    },
  });

  throw new Error('unreachable');
}

export async function approveContent(attentionId: string): Promise<never> {
  return executeWorkspaceAction({ attentionId, actionId: 'approve_content' });
}

export async function retryPublish(attentionId: string): Promise<never> {
  return executeWorkspaceAction({ attentionId, actionId: 'retry_publish' });
}

export async function acknowledgeAlert(attentionId: string): Promise<never> {
  return executeWorkspaceAction({ attentionId, actionId: 'acknowledge_alert' });
}

export async function resolveAlert(attentionId: string): Promise<never> {
  return executeWorkspaceAction({ attentionId, actionId: 'resolve_alert' });
}
