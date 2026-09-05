/**
 * @jest-environment node
 *
 * Phase 3A: approve_content allowlist + fail-closed remaining mutations.
 */
import {
  MOBILE_ALLOWED_MUTATIONS,
  MOBILE_APPROVE_CONTENT_ENABLED,
  MOBILE_MUTATIONS_ENABLED,
  MOBILE_MUTATIONS_KILL_SWITCH,
  MOBILE_MUTATIONS_UNLOCK_ALL,
  CLIENT_SOURCE,
} from '../config/constants';
import {
  assertActionAllowed,
  assertMutationsEnabled,
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

const APPROVE_ACTION: OperatorWorkspaceAction = {
  action_id: 'approve_content',
  label: 'Approve',
  action_type: 'mutation',
  enabled: true,
  requires_confirmation: true,
  confirmation_message:
    'This marks internal approval and starts client review where configured. It does not publish or bypass client approval.',
  confirmation_tier: 'medium',
  destructive: false,
  external_side_effect: true,
  primary: true,
};

function mockFetchOk(body: unknown = {
  success: true,
  action_id: 'approve_content',
  message: 'Content approved — client review started where configured',
  canonical_state: { status: 'approved' },
  attention_still_relevant: false,
  refresh_recommended: true,
}) {
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

describe('Phase 3A feature gates', () => {
  it('keeps unlock-all false; Phase 3A uses allowlist only', () => {
    expect(MOBILE_MUTATIONS_UNLOCK_ALL).toBe(false);
    expect(MOBILE_MUTATIONS_ENABLED).toBe(false); // deprecated alias
    expect(MOBILE_MUTATIONS_KILL_SWITCH).toBe(false);
  });

  it('allowlists only approve_content', () => {
    expect(MOBILE_ALLOWED_MUTATIONS).toEqual(['approve_content']);
    expect(MOBILE_APPROVE_CONTENT_ENABLED).toBe(true);
    expect(isMobileMutationAllowed('approve_content')).toBe(true);
    expect(isMobileMutationAllowed('retry_publish')).toBe(false);
    expect(isMobileMutationAllowed('acknowledge_alert')).toBe(false);
    expect(isMobileMutationAllowed('resolve_alert')).toBe(false);
    expect(isMobileMutationAllowed('resolve_manual')).toBe(false);
    expect(isMobileMutationAllowed('unknown_mutation')).toBe(false);
  });

  it('blocks approve when specific feature gate is off', () => {
    expect(
      evaluateMutationGate('approve_content', {
        killSwitch: false,
        allowlist: [],
      }),
    ).toBe(false);
    expect(
      evaluateMutationGate('approve_content', {
        killSwitch: true,
        allowlist: ['approve_content'],
      }),
    ).toBe(false);
  });

  it('assertMutationsEnabled reflects unlock-all (not allowlist)', () => {
    expect(() => assertMutationsEnabled('approve_content')).toThrow(AppError);
  });

  it('assertActionAllowed allows approve_content only', () => {
    expect(() => assertActionAllowed('approve_content')).not.toThrow();
    expect(() => assertActionAllowed('retry_publish')).toThrow(AppError);
    expect(() => assertActionAllowed('acknowledge_alert')).toThrow(AppError);
    expect(() => assertActionAllowed('resolve_alert')).toThrow(AppError);
    expect(() => assertActionAllowed('weird_action')).toThrow(AppError);
  });
});

describe('UI eligibility (backend actions[] + context)', () => {
  it('executes approve only when present/enabled on Approvals', () => {
    expect(
      canExecuteMobileAction({
        actionId: 'approve_content',
        enabled: true,
        executionContext: 'approvals',
      }),
    ).toBe(true);
  });

  it('blocks approve when not enabled in backend actions[]', () => {
    expect(
      canExecuteMobileAction({
        actionId: 'approve_content',
        enabled: false,
        executionContext: 'approvals',
      }),
    ).toBe(false);
  });

  it('blocks approve on Today/Problems (readonly context)', () => {
    expect(
      canExecuteMobileAction({
        actionId: 'approve_content',
        enabled: true,
        executionContext: 'readonly',
      }),
    ).toBe(false);
  });

  it('blocks other mutations even on Approvals', () => {
    for (const actionId of [
      'retry_publish',
      'acknowledge_alert',
      'resolve_alert',
      'resolve_manual',
    ]) {
      expect(
        canExecuteMobileAction({
          actionId,
          enabled: true,
          executionContext: 'approvals',
        }),
      ).toBe(false);
    }
  });
});

describe('approve_content HTTP behavior', () => {
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
    const result = await approveContent('content-review:abc');
    expect(result.success).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [
      string,
      RequestInit,
    ];
    expect(url).toContain(
      '/operator-workspace/items/content-review%3Aabc/actions/approve_content',
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
      await expect(approveContent('att-1')).rejects.toBeInstanceOf(AppError);
      expect(fetchMock).toHaveBeenCalledTimes(1);
    }
  });

  it('blocks retry_publish / acknowledge / resolve / unknown without HTTP', async () => {
    const fetchMock = mockFetchOk();
    await expect(retryPublish('att-1')).rejects.toMatchObject({
      kind: 'mutation_blocked',
    });
    await expect(acknowledgeAlert('att-1')).rejects.toMatchObject({
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
});

describe('confirmation gate', () => {
  beforeEach(() => {
    (Alert.alert as jest.Mock).mockReset();
  });

  it('external_side_effect=true produces explicit Telegram confirmation copy', () => {
    const msg = resolveConfirmationMessage(APPROVE_ACTION);
    expect(APPROVE_ACTION.external_side_effect).toBe(true);
    expect(msg).toMatch(/telegram/i);
    expect(msg).toMatch(/may send/i);
    expect(msg).toMatch(/review preview|notification/i);
    expect(msg).not.toMatch(/publishes? to (facebook|instagram|social)/i);
  });

  it('external_side_effect=false does not claim Telegram delivery', () => {
    const internalOnly: OperatorWorkspaceAction = {
      ...APPROVE_ACTION,
      external_side_effect: false,
      confirmation_message: undefined,
    };
    const msg = resolveConfirmationMessage(internalOnly);
    expect(msg).toMatch(/internal approval/i);
    expect(msg).not.toMatch(/telegram/i);
    expect(msg).not.toMatch(/publishes? to (facebook|instagram|social)/i);
  });

  it('required confirmation waits for accept before resolving true', async () => {
    (Alert.alert as jest.Mock).mockImplementation((_t, _m, buttons) => {
      const accept = buttons.find((b: { text: string }) => b.text === 'Approve');
      accept.onPress();
    });
    await expect(confirmWorkspaceAction(APPROVE_ACTION)).resolves.toBe(true);
    expect(Alert.alert).toHaveBeenCalledTimes(1);
    const msg = (Alert.alert as jest.Mock).mock.calls[0][1] as string;
    expect(msg).toMatch(/telegram/i);
    expect(msg).toMatch(/may send/i);
    expect(msg).not.toMatch(/publishes? to (facebook|instagram|social)/i);
  });

  it('cancel confirmation causes zero acceptance and zero HTTP mutation', async () => {
    const fetchMock = mockFetchOk();
    (Alert.alert as jest.Mock).mockImplementation((_t, _m, buttons) => {
      const cancel = buttons.find((b: { text: string }) => b.text === 'Cancel');
      cancel.onPress();
    });
    const accepted = await confirmWorkspaceAction(APPROVE_ACTION);
    expect(accepted).toBe(false);
    // Mirrors useApproveContent: cancel returns before any mutation HTTP.
    if (accepted) {
      await approveContent('content-review:abc');
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('skips dialog when requires_confirmation is false', async () => {
    const noConfirm = { ...APPROVE_ACTION, requires_confirmation: false };
    await expect(confirmWorkspaceAction(noConfirm)).resolves.toBe(true);
    expect(Alert.alert).not.toHaveBeenCalled();
  });

  it('respects confirmation_tier for dialog title', async () => {
    (Alert.alert as jest.Mock).mockImplementation((_t, _m, buttons) => {
      buttons.find((b: { text: string }) => b.text === 'Cancel').onPress();
    });
    await confirmWorkspaceAction({
      ...APPROVE_ACTION,
      confirmation_tier: 'high',
    });
    expect((Alert.alert as jest.Mock).mock.calls[0][0]).toBe('Confirm Approve');

    (Alert.alert as jest.Mock).mockReset();
    (Alert.alert as jest.Mock).mockImplementation((_t, _m, buttons) => {
      buttons.find((b: { text: string }) => b.text === 'Cancel').onPress();
    });
    await confirmWorkspaceAction({
      ...APPROVE_ACTION,
      confirmation_tier: 'medium',
    });
    expect((Alert.alert as jest.Mock).mock.calls[0][0]).toBe('Approve');
  });
});

describe('error semantics for mutations', () => {
  it('classifies statuses without encouraging blind retry', () => {
    expect(classifyHttpStatus(409)).toBe('conflict');
    expect(classifyHttpStatus(403)).toBe('forbidden');
    expect(classifyHttpStatus(429)).toBe('rate_limited');
    expect(classifyHttpStatus(500)).toBe('server');
    expect(userFacingMessage(new AppError('conflict', 'x'))).toMatch(
      /changed since it was loaded/i,
    );
  });

  it('mutation_blocked is not retryable', () => {
    try {
      assertActionAllowed('retry_publish');
    } catch (err) {
      expect(err).toBeInstanceOf(AppError);
      expect((err as AppError).retryable).toBe(false);
    }
  });
});

describe('double-submit lock helper', () => {
  it('tracks per-item in-flight set (no duplicate concurrent start)', () => {
    const inFlight = new Set<string>();
    const tryStart = (id: string) => {
      if (inFlight.has(id)) return false;
      inFlight.add(id);
      return true;
    };
    expect(tryStart('a')).toBe(true);
    expect(tryStart('a')).toBe(false);
    expect(tryStart('b')).toBe(true);
    inFlight.delete('a');
    expect(tryStart('a')).toBe(true);
  });
});

describe('Phase 2 invariants retained', () => {
  it('mutation action id classifier unchanged', () => {
    expect(isMutationActionId('approve_content')).toBe(true);
    expect(isMutationActionId('open')).toBe(false);
  });

  it('deep links still do not execute actions', () => {
    expect(resolveSafeInternalRoute('/approve/foo')).toBeNull();
    expect(resolveSafeInternalRoute('/items/1/actions/approve_content')).toBeNull();
    expect(resolveSafeInternalRoute('/(tabs)/approvals')).toBe('/(tabs)/approvals');
  });
});
