import type { OperatorAttentionItem, OperatorWorkspaceSummary } from './workspace';

export type ComponentStatus =
  | 'ok'
  | 'degraded'
  | 'unknown'
  | 'disabled'
  | 'unconfigured'
  | 'demo';

export type BackupExposure = 'unavailable' | 'healthy' | 'action_required' | 'unknown';

export interface MobileBackupStatus {
  status: BackupExposure;
  last_successful_at?: string | null;
  message: string;
}

export interface MobileSystemStatusSummary {
  overall: ComponentStatus;
  api: ComponentStatus;
  database: ComponentStatus;
  scheduler: ComponentStatus;
  ai_services: ComponentStatus;
  telegram_bot: ComponentStatus;
  integration_attention_count: number;
  backup: MobileBackupStatus;
  uptime_seconds?: number | null;
  notes: string[];
}

export interface MobileControlCapabilities {
  actions_supported: string[];
  push_registration: boolean;
  biometric_unlock: boolean;
  internal_content_reject: boolean;
  backup_status_live: boolean;
  realtime_channel: boolean;
}

export interface MobileControlHomeResponse {
  generated_at: string;
  attention_summary: OperatorWorkspaceSummary;
  approvals_count: number;
  problems_count: number;
  waiting_for_client: number;
  unread_notifications: number;
  system_status: MobileSystemStatusSummary;
  urgent_items: OperatorAttentionItem[];
  urgent_limit: number;
  capabilities: MobileControlCapabilities;
  deep_link_base: string;
  last_updated_at: string;
}

export interface MobileControlSystemResponse {
  generated_at: string;
  system_status: MobileSystemStatusSummary;
  capabilities: MobileControlCapabilities;
}
