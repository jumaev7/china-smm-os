import { PROBLEM_CATEGORIES } from '@/types/workspace';
import type { AttentionCategory } from '@/types/workspace';

/**
 * Today dashboard summary targets.
 * Navigation is local Expo Router only — never triggers API mutations.
 */
export type DashboardCardId =
  | 'attention'
  | 'approvals'
  | 'problems'
  | 'waiting'
  | 'system'
  | 'unread';

export type OperatorTabHref =
  | '/(tabs)/today'
  | '/(tabs)/approvals'
  | '/(tabs)/problems'
  | '/(tabs)/system'
  | '/(tabs)/settings';

export type DashboardNavigationResult =
  | {
      navigable: true;
      href: OperatorTabHref;
      /** Documents which canonical categories the destination represents. */
      attentionCategories?: readonly AttentionCategory[];
    }
  | {
      navigable: false;
      reason: string;
    };

/**
 * Canonical Problems tab categories — the mobile "actionable attention" set.
 * Matches backend mobile-control `_PROBLEM_TYPES` / PROBLEM_CATEGORIES.
 * Intentionally excludes waiting_for_client and content_internal_review.
 */
export const ATTENTION_ACTIONABLE_CATEGORIES: readonly AttentionCategory[] =
  PROBLEM_CATEGORIES;

/**
 * Pure read-only map from Today summary UI → existing Expo Router tabs.
 * Does not invent Waiting routes or notification screens.
 */
export function resolveDashboardCardNavigation(
  card: DashboardCardId,
): DashboardNavigationResult {
  switch (card) {
    case 'attention':
      // Home shows attention_summary.total (all workspace items). Phase 2 mobile
      // has no combined Attention inbox; Problems is the existing actionable
      // attention/problems view (PROBLEM_CATEGORIES).
      return {
        navigable: true,
        href: '/(tabs)/problems',
        attentionCategories: ATTENTION_ACTIONABLE_CATEGORIES,
      };
    case 'approvals':
      return { navigable: true, href: '/(tabs)/approvals' };
    case 'problems':
      return {
        navigable: true,
        href: '/(tabs)/problems',
        attentionCategories: ATTENTION_ACTIONABLE_CATEGORIES,
      };
    case 'system':
      return { navigable: true, href: '/(tabs)/system' };
    case 'waiting':
      // Backend exposes waiting_for_client as a category + home count, but mobile
      // has no Waiting screen/filter route, and Problems intentionally omits it.
      return {
        navigable: false,
        reason:
          'waiting_for_client has no dedicated mobile read-only route; not in PROBLEM_CATEGORIES',
      };
    case 'unread':
      return {
        navigable: false,
        reason: 'No Notifications screen/route exists in Phase 2',
      };
    default: {
      const _exhaustive: never = card;
      return { navigable: false, reason: `Unknown card: ${String(_exhaustive)}` };
    }
  }
}

/** Dashboard card taps must never issue mutation HTTP. */
export function dashboardNavigationPerformsMutations(): false {
  return false;
}
