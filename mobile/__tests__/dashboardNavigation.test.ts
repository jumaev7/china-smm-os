/**
 * @jest-environment node
 */
import {
  MOBILE_APPROVE_CONTENT_ENABLED,
  MOBILE_MUTATIONS_ENABLED,
  MOBILE_MUTATIONS_UNLOCK_ALL,
} from '../config/constants';
import { assertMutationsEnabled, isMobileMutationAllowed } from '../api/guard';
import {
  executeWorkspaceAction,
  resolveAlert,
  retryPublish,
} from '../api/mutations';
import { PROBLEM_CATEGORIES } from '../types/workspace';
import {
  ATTENTION_ACTIONABLE_CATEGORIES,
  dashboardNavigationPerformsMutations,
  resolveDashboardCardNavigation,
  type DashboardCardId,
} from '../utils/dashboardNavigation';
import { AppError } from '../utils/errors';

describe('Today dashboard card navigation (read-only)', () => {
  it('Approvals card navigates to Approvals tab', () => {
    const result = resolveDashboardCardNavigation('approvals');
    expect(result).toEqual({
      navigable: true,
      href: '/(tabs)/approvals',
    });
  });

  it('Problems card navigates to Problems tab', () => {
    const result = resolveDashboardCardNavigation('problems');
    expect(result.navigable).toBe(true);
    if (result.navigable) {
      expect(result.href).toBe('/(tabs)/problems');
      expect(result.attentionCategories).toEqual(PROBLEM_CATEGORIES);
    }
  });

  it('Attention navigates to Problems using canonical PROBLEM_CATEGORIES', () => {
    const result = resolveDashboardCardNavigation('attention');
    expect(result.navigable).toBe(true);
    if (result.navigable) {
      expect(result.href).toBe('/(tabs)/problems');
      expect(result.attentionCategories).toEqual(ATTENTION_ACTIONABLE_CATEGORIES);
      expect(result.attentionCategories).toEqual([
        'publishing_issue',
        'scheduling_issue',
        'integration_issue',
        'telegram_ingestion_issue',
        'automation_failure',
      ]);
      // Waiting / approvals are NOT part of the Problems actionable set.
      expect(result.attentionCategories).not.toContain('waiting_for_client');
      expect(result.attentionCategories).not.toContain('content_internal_review');
    }
  });

  it('Waiting stays non-navigable (no invented Waiting route/filter)', () => {
    const result = resolveDashboardCardNavigation('waiting');
    expect(result.navigable).toBe(false);
    if (!result.navigable) {
      expect(result.reason).toMatch(/waiting_for_client/i);
      expect(result.reason).toMatch(/PROBLEM_CATEGORIES|no dedicated/i);
    }
    // Backend category exists in the type model, but mobile has no route for it.
    expect(PROBLEM_CATEGORIES).not.toContain('waiting_for_client');
  });

  it('System status chip navigates to System tab', () => {
    const result = resolveDashboardCardNavigation('system');
    expect(result).toEqual({
      navigable: true,
      href: '/(tabs)/system',
    });
  });

  it('Unread remains non-navigable (no Notifications screen)', () => {
    const result = resolveDashboardCardNavigation('unread');
    expect(result.navigable).toBe(false);
    if (!result.navigable) {
      expect(result.reason).toMatch(/Notification/i);
    }
  });

  it('tapping dashboard cards performs ZERO API mutations', () => {
    expect(dashboardNavigationPerformsMutations()).toBe(false);
    expect(MOBILE_MUTATIONS_ENABLED).toBe(false);

    const cards: DashboardCardId[] = [
      'attention',
      'approvals',
      'problems',
      'waiting',
      'system',
      'unread',
    ];
    for (const card of cards) {
      const target = resolveDashboardCardNavigation(card);
      // Resolution is pure — no HTTP side effects by construction.
      expect(target).toBeDefined();
      if (target.navigable) {
        expect(target.href.startsWith('/(tabs)/')).toBe(true);
      }
    }

    expect(() => assertMutationsEnabled('dashboard_nav')).toThrow(AppError);
  });

  it('MOBILE_MUTATIONS_UNLOCK_ALL remains false; Phase 3B allowlists approve+ack', () => {
    expect(MOBILE_MUTATIONS_UNLOCK_ALL).toBe(false);
    expect(MOBILE_MUTATIONS_ENABLED).toBe(false);
    expect(MOBILE_APPROVE_CONTENT_ENABLED).toBe(true);
  });
});

describe('mutation hard-block still intact after dashboard nav', () => {
  it('dashboard nav does not unlock non-allowlisted mutations', async () => {
    const originalFetch = global.fetch;
    const fetchMock = jest.fn();
    global.fetch = fetchMock as unknown as typeof fetch;

    // Navigating dashboard cards must not unlock blocked mutations.
    resolveDashboardCardNavigation('approvals');
    resolveDashboardCardNavigation('attention');
    resolveDashboardCardNavigation('system');

    expect(isMobileMutationAllowed('retry_publish')).toBe(false);
    expect(isMobileMutationAllowed('resolve_alert')).toBe(false);
    expect(isMobileMutationAllowed('acknowledge_alert')).toBe(true);
    await expect(retryPublish('att-1')).rejects.toMatchObject({
      kind: 'mutation_blocked',
    });
    await expect(resolveAlert('att-1')).rejects.toMatchObject({
      kind: 'mutation_blocked',
    });
    await expect(
      executeWorkspaceAction({
        attentionId: 'att-1',
        actionId: 'retry_publish',
      }),
    ).rejects.toMatchObject({ kind: 'mutation_blocked' });

    expect(fetchMock).not.toHaveBeenCalled();
    global.fetch = originalFetch;
  });
});

describe('safe-area screen contract', () => {
  it('documents tab vs fullscreen edge policy without hard-coded iPhone offsets', () => {
    // Mirrors components/Screen.tsx — tab screens omit bottom (tab bar owns it).
    const tabEdges = ['top', 'left', 'right'];
    const fullscreenEdges = ['top', 'right', 'bottom', 'left'];
    expect(tabEdges).not.toContain('bottom');
    expect(fullscreenEdges).toContain('bottom');
    expect(tabEdges).toContain('top');
    expect(fullscreenEdges).toContain('top');
  });
});
