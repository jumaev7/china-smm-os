import {
  MOBILE_ALLOWED_MUTATIONS,
  MOBILE_MUTATIONS_KILL_SWITCH,
  MOBILE_MUTATIONS_UNLOCK_ALL,
  MUTATION_BLOCKED_MESSAGE,
  MUTATION_KILL_SWITCH_MESSAGE,
} from '@/config/constants';
import { AppError } from '@/utils/errors';
import type { MutationActionId } from '@/types/workspace';

/**
 * Pure gate evaluator (testable without mutating compile-time constants).
 * Fail closed: kill switch or missing allowlist entry → blocked.
 *
 * Note: MOBILE_MUTATIONS_UNLOCK_ALL is intentionally NOT consulted here.
 * Unlock-all must not accidentally enable non-allowlisted actions.
 */
export function evaluateMutationGate(
  actionId: string,
  opts: {
    killSwitch: boolean;
    allowlist: readonly string[];
  },
): boolean {
  if (opts.killSwitch) return false;
  return opts.allowlist.includes(actionId);
}

/**
 * Whether a specific mutation action_id may leave the device.
 * Fail closed: unknown IDs and non-allowlisted IDs are blocked.
 */
export function isMobileMutationAllowed(actionId: string): boolean {
  return evaluateMutationGate(actionId, {
    killSwitch: MOBILE_MUTATIONS_KILL_SWITCH,
    allowlist: MOBILE_ALLOWED_MUTATIONS,
  });
}

/**
 * Legacy global check used by Phase 2 tests / dashboard invariants.
 * Reflects MOBILE_MUTATIONS_UNLOCK_ALL only — does NOT unlock the allowlist
 * and does NOT mean Phase 3A approve_content is off.
 * Prefer assertActionAllowed / isMobileMutationAllowed for execution.
 */
export function assertMutationsEnabled(actionLabel = 'mutation'): void {
  if (MOBILE_MUTATIONS_KILL_SWITCH) {
    throw new AppError('mutation_blocked', MUTATION_KILL_SWITCH_MESSAGE, {
      retryable: false,
    });
  }
  if (!MOBILE_MUTATIONS_UNLOCK_ALL) {
    throw new AppError('mutation_blocked', MUTATION_BLOCKED_MESSAGE, {
      retryable: false,
    });
  }
  void actionLabel;
}

/**
 * Per-action execution gate. Call before any mutation HTTP.
 * Hierarchy: kill switch → allowlist → (backend eligibility remains separate).
 * Does not use MOBILE_MUTATIONS_UNLOCK_ALL (fail closed / allowlist-only).
 */
export function assertActionAllowed(actionId: string): void {
  if (MOBILE_MUTATIONS_KILL_SWITCH) {
    throw new AppError('mutation_blocked', MUTATION_KILL_SWITCH_MESSAGE, {
      retryable: false,
    });
  }
  if (actionId === 'open') {
    throw new AppError(
      'mutation_blocked',
      'Navigation actions cannot run through the mutation endpoint',
      { retryable: false },
    );
  }
  if (!isMobileMutationAllowed(actionId)) {
    throw new AppError('mutation_blocked', MUTATION_BLOCKED_MESSAGE, {
      retryable: false,
    });
  }
}

export function isMutationActionId(actionId: string): actionId is MutationActionId {
  return (
    actionId === 'acknowledge_alert' ||
    actionId === 'resolve_alert' ||
    actionId === 'retry_publish' ||
    actionId === 'approve_content'
  );
}

/**
 * UI eligibility for executing a backend action on mobile.
 * Backend actions[] presence is caller's responsibility (pass action.enabled).
 * Approvals-only: Today/Problems keep executionContext='readonly'.
 */
export function canExecuteMobileAction(opts: {
  actionId: string;
  enabled: boolean;
  executionContext: 'approvals' | 'readonly';
}): boolean {
  if (opts.executionContext !== 'approvals') return false;
  if (opts.actionId !== 'approve_content') return false;
  if (!opts.enabled) return false;
  return isMobileMutationAllowed(opts.actionId);
}
