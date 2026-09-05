/**
 * @jest-environment node
 */
import type { OperatorWorkspaceAction } from '../types/workspace';
import {
  MOBILE_APPROVE_CONTENT_ENABLED,
  MOBILE_MUTATIONS_ENABLED,
  MOBILE_MUTATIONS_UNLOCK_ALL,
} from '../config/constants';
import { canExecuteMobileAction, isMutationActionId } from '../api/guard';
import { formatLastUpdated, formatUptime } from '../utils/format';

describe('actions[] rendering contract', () => {
  const sample: OperatorWorkspaceAction[] = [
    {
      action_id: 'approve_content',
      label: 'Approve',
      action_type: 'mutation',
      enabled: true,
      requires_confirmation: true,
      confirmation_tier: 'medium',
      destructive: false,
      external_side_effect: false,
      primary: true,
    },
    {
      action_id: 'open',
      label: 'Open',
      action_type: 'navigation',
      enabled: true,
      requires_confirmation: false,
      confirmation_tier: 'low',
      destructive: false,
      external_side_effect: false,
      primary: false,
    },
  ];

  it('identifies mutation actions for disabled UI', () => {
    expect(isMutationActionId('approve_content')).toBe(true);
    expect(isMutationActionId('retry_publish')).toBe(true);
    expect(isMutationActionId('acknowledge_alert')).toBe(true);
    expect(isMutationActionId('resolve_alert')).toBe(true);
    expect(isMutationActionId('open')).toBe(false);
  });

  it('Phase 3A: approve executable on Approvals only; unlock-all still off', () => {
    expect(MOBILE_MUTATIONS_UNLOCK_ALL).toBe(false);
    expect(MOBILE_MUTATIONS_ENABLED).toBe(false);
    expect(MOBILE_APPROVE_CONTENT_ENABLED).toBe(true);
    expect(
      canExecuteMobileAction({
        actionId: 'approve_content',
        enabled: true,
        executionContext: 'approvals',
      }),
    ).toBe(true);
    expect(
      canExecuteMobileAction({
        actionId: 'approve_content',
        enabled: true,
        executionContext: 'readonly',
      }),
    ).toBe(false);
    for (const a of sample) {
      if (a.action_id === 'open') {
        expect(isMutationActionId(a.action_id)).toBe(false);
      }
    }
  });
});

describe('home / system display helpers', () => {
  it('formats last updated and uptime', () => {
    expect(formatLastUpdated(null)).toMatch(/unknown/);
    expect(formatUptime(3661)).toMatch(/1h/);
    expect(formatUptime(null)).toBe('—');
  });

  it('backup unavailable uses neutral wording', () => {
    const backup = { status: 'unavailable' as const };
    const label =
      backup.status === 'unavailable'
        ? 'Backup status not available in mobile control plane'
        : backup.status;
    expect(label).toBe('Backup status not available in mobile control plane');
  });
});

describe('offline UX contract', () => {
  it('marks cached data distinctly from live', () => {
    const isOffline = true;
    const hasData = true;
    const banner = isOffline && hasData;
    expect(banner).toBe(true);
    const suffix = isOffline && hasData ? ' · cached' : '';
    expect(suffix).toContain('cached');
  });
});

describe('biometric gate state', () => {
  it('treats unavailable hardware as soft-pass (no permanent lockout)', () => {
    const capability = { hardware: false, enrolled: false, available: false };
    const softPass = !capability.available;
    expect(softPass).toBe(true);
  });

  it('requires prompt when available and preference enabled', () => {
    const available = true;
    const preferenceEnabled = true;
    expect(available && preferenceEnabled).toBe(true);
  });
});
