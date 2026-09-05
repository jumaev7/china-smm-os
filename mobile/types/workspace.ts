export type AttentionCategory =
  | 'content_internal_review'
  | 'waiting_for_client'
  | 'publishing_issue'
  | 'scheduling_issue'
  | 'integration_issue'
  | 'telegram_ingestion_issue'
  | 'automation_failure';

export type AttentionPriority = 'critical' | 'high' | 'medium' | 'low';

export type ConfirmationTier = 'low' | 'medium' | 'high';

export type WorkspaceActionType = 'mutation' | 'navigation';

export interface OperatorWorkspaceAction {
  action_id: string;
  label: string;
  action_type: WorkspaceActionType;
  enabled: boolean;
  requires_confirmation: boolean;
  confirmation_message?: string | null;
  confirmation_tier: ConfirmationTier;
  disabled_reason?: string | null;
  destructive: boolean;
  external_side_effect: boolean;
  target_resource?: string | null;
  href?: string | null;
  primary: boolean;
}

export interface OperatorAttentionItem {
  id: string;
  attention_type: AttentionCategory;
  priority: AttentionPriority;
  client_id?: string | null;
  company_name: string;
  content_id?: string | null;
  resource_id?: string | null;
  title: string;
  reason: string;
  current_state?: string | null;
  responsible_party: string;
  suggested_action: string;
  action_path: string;
  created_at?: string | null;
  due_at?: string | null;
  overdue: boolean;
  source_domain: string;
  metadata?: Record<string, unknown>;
  actions: OperatorWorkspaceAction[];
}

export interface OperatorWorkspaceSummary {
  needs_action_now: number;
  waiting_for_client: number;
  publishing_issues: number;
  due_today: number;
  integration_issues: number;
  scheduling_issues: number;
  telegram_issues: number;
  automation_failures: number;
  total: number;
}

export interface OperatorWorkspaceItemsResponse {
  items: OperatorAttentionItem[];
  total: number;
  page: number;
  page_size: number;
  summary: OperatorWorkspaceSummary;
}

/** Categories shown on Approvals tab. */
export const APPROVAL_CATEGORIES: AttentionCategory[] = ['content_internal_review'];

/** Categories shown on Problems tab. */
export const PROBLEM_CATEGORIES: AttentionCategory[] = [
  'publishing_issue',
  'scheduling_issue',
  'integration_issue',
  'telegram_ingestion_issue',
  'automation_failure',
];

export const MUTATION_ACTION_IDS = [
  'acknowledge_alert',
  'resolve_alert',
  'retry_publish',
  'approve_content',
] as const;

export type MutationActionId = (typeof MUTATION_ACTION_IDS)[number];

/** Canonical POST …/actions/{action_id} success payload. */
export interface OperatorWorkspaceActionResult {
  success: boolean;
  action_id: string;
  message: string;
  canonical_state?: Record<string, unknown> | null;
  attention_still_relevant?: boolean;
  refresh_recommended?: boolean;
  redirect_path?: string | null;
}
