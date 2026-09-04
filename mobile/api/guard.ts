import { MOBILE_MUTATIONS_ENABLED, MUTATION_BLOCKED_MESSAGE } from '@/config/constants';
import { AppError } from '@/utils/errors';
import type { MutationActionId } from '@/types/workspace';

/**
 * Central hard-block for Phase 2. All mutation paths must call this
 * before any HTTP. Fail closed when MOBILE_MUTATIONS_ENABLED is false.
 */
export function assertMutationsEnabled(actionLabel = 'mutation'): void {
  if (!MOBILE_MUTATIONS_ENABLED) {
    throw new AppError('mutation_blocked', MUTATION_BLOCKED_MESSAGE, {
      retryable: false,
    });
  }
  // Keep reference so tree-shaking doesn't drop the label in tests.
  void actionLabel;
}

export function assertActionAllowed(actionId: string): void {
  assertMutationsEnabled(actionId);
  if (actionId === 'open') {
    // Navigation-only — still blocked from mutating endpoints.
    return;
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
