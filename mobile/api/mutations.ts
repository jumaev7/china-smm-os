/**
 * Workspace mutation API — Phase 3B allowlists approve_content + acknowledge_alert.
 * All other mutation helpers remain fail-closed before HTTP.
 */
import { assertActionAllowed } from '@/api/guard';
import { apiRequest } from '@/api/client';
import type { OperatorWorkspaceActionResult } from '@/types/workspace';

export interface ExecuteActionParams {
  attentionId: string;
  actionId: string;
  note?: string;
}

/**
 * POST /operator-workspace/items/{id}/actions/{action_id}
 * Guarded by assertActionAllowed (kill switch + allowlist).
 * No automatic retry — callers must not replay on ambiguous failure.
 */
export async function executeWorkspaceAction(
  params: ExecuteActionParams,
): Promise<OperatorWorkspaceActionResult> {
  assertActionAllowed(params.actionId);

  return apiRequest<OperatorWorkspaceActionResult>({
    method: 'POST',
    path: `/operator-workspace/items/${encodeURIComponent(params.attentionId)}/actions/${encodeURIComponent(params.actionId)}`,
    body: {
      note: params.note,
      source: 'mobile',
    },
  });
}

export async function approveContent(
  attentionId: string,
  note?: string,
): Promise<OperatorWorkspaceActionResult> {
  return executeWorkspaceAction({
    attentionId,
    actionId: 'approve_content',
    note,
  });
}

export async function retryPublish(attentionId: string): Promise<OperatorWorkspaceActionResult> {
  return executeWorkspaceAction({ attentionId, actionId: 'retry_publish' });
}

export async function acknowledgeAlert(
  attentionId: string,
): Promise<OperatorWorkspaceActionResult> {
  return executeWorkspaceAction({ attentionId, actionId: 'acknowledge_alert' });
}

export async function resolveAlert(
  attentionId: string,
): Promise<OperatorWorkspaceActionResult> {
  return executeWorkspaceAction({ attentionId, actionId: 'resolve_alert' });
}
