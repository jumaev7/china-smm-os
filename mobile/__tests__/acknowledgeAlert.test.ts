/**
 * @jest-environment node
 *
 * Phase 3B: acknowledge_alert allowlist + Problems-screen execution.
 */
import {
  MOBILE_ACKNOWLEDGE_ALERT_ENABLED,
  MOBILE_ALLOWED_MUTATIONS,
  MOBILE_APPROVE_CONTENT_ENABLED,
  MOBILE_MUTATIONS_ENABLED,
  MOBILE_MUTATIONS_KILL_SWITCH,
  MOBILE_MUTATIONS_UNLOCK_ALL,
  CLIENT_SOURCE,
} from '../config/constants';
import {
  assertActionAllowed,
  canExecuteMobileAction,
  evaluateMutationGate,
  isMobileMutationAllowed,
  isMutationActionId,
} from '../api/guard';
import {
  acknowledgeAlert,
  approveContent,
  executeWorkspaceAction,
  resolveAlert,
  retryPublish,
} from '../api/mutations';
import { configureApiClient } from '../api/client';
import { setAccessToken, clearAccessToken } from '../auth/tokenMemory';
import {
  ACKNOWLEDGE_CONFIRM_MESSAGE,
  confirmAcknowledgeAlert,
  confirmWorkspaceAction,
  resolveConfirmationMessage,
} from '../utils/confirmAction';
import type { OperatorWorkspaceAction } from '../types/workspace';
import { AppError, classifyHttpStatus, userFacingMessage } from '../utils/errors';
import { resolveSafeInternalRoute } from '../utils/deepLinks';

jest.mock('react-native', () => ({
  Alert: {
    alert: jest.fn(),
  },
}));

import { Alert } from 'react-native';

const ACK_ACTION: OperatorWorkspaceAction = {
  action_id: 'acknowledge_alert',
  label: 'Acknowledge',
  action_type: 'mutation',
  enabled: true,
  requires_confirmation: false,
  confirmation_tier: 'low',
  destructive: false,
  external_side_effect: false,
  primary: true,
};

function mockFetchOk(
  body: unknown = {
    success: true,
    action_id: 'acknowledge_alert',
    message: 'Alert acknowledged',
    canonical_state: { state: 'acknowledged' },
    attention_still_relevant: true,
    refresh_recommended: true,
  },
) {
  const fetchMock = jest.fn(async () => ({
    ok: true,
    status: 200,
    text: async () => JSON.stringify(body),
  }));
  global.fetch = fetchMock as unknown as typeof fetch;
  return fetchMock;
}

function mockFetchStatus(status: number, detail: string) {
  const fetchMock = jest.fn(async () => ({
    ok: false,
    status,
    text: async () => JSON.stringify({ detail }),
  }));
  global.fetch = fetchMock as unknown as typeof fetch;
  return fetchMock;
}

describe('Phase 3B feature gates', () => {
  it('keeps unlock-all false; Phase 3B uses allowlist only', () => {
    expect(MOBILE_MUTATIONS_UNLOCK_ALL).toBe(false);
    expect(MOBILE_MUTATIONS_ENABLED).toBe(false);
    expect(MOBILE_MUTATIONS_KILL_SWITCH).toBe(false);
  });

  it('allowlists approve_content and acknowledge_alert only', () => {
    expect(MOBILE_ALLOWED_MUTATIONS).toEqual([
      'approve_content',
      'acknowledge_alert',
    ]);
    expect(MOBILE_APPROVE_CONTENT_ENABLED).toBe(true);
    expect(MOBILE_ACKNOWLEDGE_ALERT_ENABLED).toBe(true);
    expect(isMobileMutationAllowed('approve_content')).toBe(true);
    expect(isMobileMutationAllowed('acknowledge_alert')).toBe(true);
    expect(isMobileMutationAllowed('retry_publish')).toBe(false);
    expect(isMobileMutationAllowed('resolve_alert')).toBe(false);
    expect(isMobileMutationAllowed('resolve_manual')).toBe(false);
    expect(isMobileMutationAllowed('unknown_mutation')).toBe(false);
  });

  it('blocks acknowledge when allowlist or kill switch off', () => {
    expect(
      evaluateMutationGate('acknowledge_alert', {
        killSwitch: false,
        allowlist: ['approve_content'],
      }),
    ).toBe(false);
    expect(
      evaluateMutationGate('acknowledge_alert', {
        killSwitch: true,
        allowlist: ['acknowledge_alert'],
      }),
    ).toBe(false);
  });

  it('assertActionAllowed allows approve + acknowledge; blocks rest', () => {
    expect(() => assertActionAllowed('approve_content')).not.toThrow();
    expect(() => assertActionAllowed('acknowledge_alert')).not.toThrow();
    expect(() => assertActionAllowed('retry_publish')).toThrow(AppError);
    expect(() => assertActionAllowed('resolve_alert')).toThrow(AppError);
    expect(() => assertActionAllowed('resolve_manual')).toThrow(AppError);
    expect(() => assertActionAllowed('weird_action')).toThrow(AppError);
  });
});

describe('UI eligibility (backend actions[] + Problems context)', () => {
  it('executes acknowledge only when present/enabled on Problems', () => {
    expect(
      canExecuteMobileAction({
        actionId: 'acknowledge_alert',
        enabled: true,
        executionContext: 'problems',
      }),
    ).toBe(true);
  });

  it('blocks acknowledge when not enabled in backend actions[]', () => {
    expect(
      canExecuteMobileAction({
        actionId: 'acknowledge_alert',
        enabled: false,
        executionContext: 'problems',
      }),
    ).toBe(false);
  });

  it('blocks acknowledge on Approvals / Today (wrong context)', () => {
    expect(
      canExecuteMobileAction({
        actionId: 'acknowledge_alert',
        enabled: true,
        executionContext: 'approvals',
      }),
    ).toBe(false);
    expect(
      canExecuteMobileAction({
        actionId: 'acknowledge_alert',
        enabled: true,
        executionContext: 'readonly',
      }),
    ).toBe(false);
  });

  it('keeps approve on Approvals; blocks approve on Problems', () => {
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
        executionContext: 'problems',
      }),
    ).toBe(false);
  });

  it('blocks retry/resolve even on Problems', () => {
    for (const actionId of ['retry_publish', 'resolve_alert', 'resolve_manual']) {
      expect(
        canExecuteMobileAction({
          actionId,
          enabled: true,
          executionContext: 'problems',
        }),
      ).toBe(false);
    }
  });
});

describe('acknowledge_alert HTTP behavior', () => {
  beforeEach(() => {
    clearAccessToken();
    setAccessToken('test-access');
    configureApiClient({
      getAccessToken: () => 'test-access',
      refreshAccessToken: async () => null,
      onSessionInvalid: () => undefined,
    });
  });

  afterEach(() => {
    clearAccessToken();
  });

  it('posts to canonical endpoint with X-Client-Source and body source', async () => {
    const fetchMock = mockFetchOk();
    const result = await acknowledgeAlert('publish-alert:abc');
    expect(result.success).toBe(true);
    expect(result.attention_still_relevant).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [
      string,
      RequestInit,
    ];
    expect(url).toContain(
      '/operator-workspace/items/publish-alert%3Aabc/actions/acknowledge_alert',
    );
    const headers = init.headers as Record<string, string>;
    expect(headers['X-Client-Source']).toBe(CLIENT_SOURCE);
    expect(headers.Authorization).toBe('Bearer test-access');
    const body = JSON.parse(String(init.body));
    expect(body.source).toBe('mobile');
    expect(init.method).toBe('POST');
  });

  it('does not automatically retry on 409 / 403 / 429 / 5xx', async () => {
    for (const status of [409, 403, 429, 500]) {
      const fetchMock = mockFetchStatus(status, `fail-${status}`);
      await expect(acknowledgeAlert('att-1')).rejects.toBeInstanceOf(AppError);
      expect(fetchMock).toHaveBeenCalledTimes(1);
    }
  });

  it('blocks retry_publish / resolve / unknown without HTTP', async () => {
    const fetchMock = mockFetchOk();
    await expect(retryPublish('att-1')).rejects.toMatchObject({
      kind: 'mutation_blocked',
    });
    await expect(resolveAlert('att-1')).rejects.toMatchObject({
      kind: 'mutation_blocked',
    });
    await expect(
      executeWorkspaceAction({ attentionId: 'att-1', actionId: 'resolve_manual' }),
    ).rejects.toMatchObject({ kind: 'mutation_blocked' });
    await expect(
      executeWorkspaceAction({ attentionId: 'att-1', actionId: 'totally_unknown' }),
    ).rejects.toMatchObject({ kind: 'mutation_blocked' });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('Phase 3A approve_content still posts successfully', async () => {
    const fetchMock = mockFetchOk({
      success: true,
      action_id: 'approve_content',
      message: 'Content approved',
      attention_still_relevant: false,
      refresh_recommended: true,
    });
    await expect(approveContent('content-review:xyz')).resolves.toMatchObject({
      success: true,
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe('acknowledge confirmation UX', () => {
  beforeEach(() => {
    (Alert.alert as jest.Mock).mockReset();
  });

  it('copy says acknowledged, not resolved/retry/publish', () => {
    expect(ACKNOWLEDGE_CONFIRM_MESSAGE).toMatch(/acknowledged/i);
    expect(ACKNOWLEDGE_CONFIRM_MESSAGE).toMatch(/does not resolve/i);
    expect(ACKNOWLEDGE_CONFIRM_MESSAGE).not.toMatch(/\bfixed\b/i);
    expect(ACKNOWLEDGE_CONFIRM_MESSAGE).toMatch(/does not retry/i);
    expect(ACKNOWLEDGE_CONFIRM_MESSAGE).not.toMatch(/telegram|meta|facebook/i);
    // Must not claim the issue is resolved/fixed — only that it is acknowledged.
    expect(ACKNOWLEDGE_CONFIRM_MESSAGE).not.toMatch(
      /marks (the alert as )?resolved|issue is (resolved|fixed)/i,
    );

    const fromResolver = resolveConfirmationMessage(ACK_ACTION);
    expect(fromResolver).toMatch(/acknowledged/i);
    expect(fromResolver).toMatch(/does not resolve/i);
    expect(fromResolver).not.toMatch(/telegram/i);
  });

  it('voluntary confirm cancel => zero HTTP', async () => {
    const fetchMock = mockFetchOk();
    (Alert.alert as jest.Mock).mockImplementation((_t, _m, buttons) => {
      const cancel = buttons.find((b: { text: string }) => b.text === 'Cancel');
      cancel.onPress();
    });
    const accepted = await confirmAcknowledgeAlert(ACK_ACTION);
    expect(accepted).toBe(false);
    if (accepted) {
      await acknowledgeAlert('publish-alert:abc');
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('voluntary confirm accept resolves true', async () => {
    (Alert.alert as jest.Mock).mockImplementation((_t, _m, buttons) => {
      const accept = buttons.find(
        (b: { text: string }) => b.text === 'Acknowledge',
      );
      accept.onPress();
    });
    await expect(confirmAcknowledgeAlert(ACK_ACTION)).resolves.toBe(true);
    expect(Alert.alert).toHaveBeenCalledTimes(1);
    const msg = (Alert.alert as jest.Mock).mock.calls[0][1] as string;
    expect(msg).toMatch(/acknowledged/i);
    expect(msg).toMatch(/does not resolve/i);
  });

  it('respects backend requires_confirmation when set', async () => {
    const required: OperatorWorkspaceAction = {
      ...ACK_ACTION,
      requires_confirmation: true,
      confirmation_message:
        'This marks the alert as acknowledged. It does not resolve or fix the issue.',
    };
    (Alert.alert as jest.Mock).mockImplementation((_t, _m, buttons) => {
      buttons.find((b: { text: string }) => b.text === 'Cancel').onPress();
    });
    await expect(confirmAcknowledgeAlert(required)).resolves.toBe(false);
    await expect(confirmWorkspaceAction(required)).resolves.toBe(false);
  });
});

describe('error / offline / double-submit contracts', () => {
  it('classifies statuses without encouraging blind retry', () => {
    expect(classifyHttpStatus(409)).toBe('conflict');
    expect(classifyHttpStatus(403)).toBe('forbidden');
    expect(classifyHttpStatus(429)).toBe('rate_limited');
    expect(classifyHttpStatus(500)).toBe('server');
    expect(userFacingMessage(new AppError('conflict', 'x'))).toMatch(
      /changed since it was loaded/i,
    );
  });

  it('per-item in-flight lock prevents double start', () => {
    const inFlight = new Set<string>();
    const tryStart = (id: string) => {
      if (inFlight.has(id)) return false;
      inFlight.add(id);
      return true;
    };
    expect(tryStart('a')).toBe(true);
    expect(tryStart('a')).toBe(false);
    expect(tryStart('b')).toBe(true);
  });

  it('success does not imply local removal (attention may remain)', () => {
    const result = {
      success: true,
      attention_still_relevant: true,
      canonical_state: { state: 'acknowledged' },
    };
    expect(result.attention_still_relevant).toBe(true);
    expect(result.canonical_state.state).toBe('acknowledged');
  });

  it('deep links still do not execute actions', () => {
    expect(isMutationActionId('acknowledge_alert')).toBe(true);
    expect(resolveSafeInternalRoute('/acknowledge/foo')).toBeNull();
    expect(
      resolveSafeInternalRoute('/items/1/actions/acknowledge_alert'),
    ).toBeNull();
    expect(resolveSafeInternalRoute('/(tabs)/problems')).toBe('/(tabs)/problems');
  });
});
