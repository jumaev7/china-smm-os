/**
 * @jest-environment node
 *
 * Remaining mutation hard-blocks after Phase 3B allowlist.
 */
import {
  MOBILE_ACKNOWLEDGE_ALERT_ENABLED,
  MOBILE_APPROVE_CONTENT_ENABLED,
  MOBILE_MUTATIONS_ENABLED,
  MOBILE_MUTATIONS_UNLOCK_ALL,
} from '../config/constants';
import {
  assertActionAllowed,
  assertMutationsEnabled,
  isMobileMutationAllowed,
} from '../api/guard';
import {
  executeWorkspaceAction,
  resolveAlert,
  retryPublish,
} from '../api/mutations';
import { AppError } from '../utils/errors';

describe('mutation hard-block (non-allowlisted)', () => {
  it('keeps unlock-all false while approve+ack are allowlisted', () => {
    expect(MOBILE_MUTATIONS_UNLOCK_ALL).toBe(false);
    expect(MOBILE_MUTATIONS_ENABLED).toBe(false);
    expect(MOBILE_APPROVE_CONTENT_ENABLED).toBe(true);
    expect(MOBILE_ACKNOWLEDGE_ALERT_ENABLED).toBe(true);
  });

  it('assertMutationsEnabled still throws (global suite flag off)', () => {
    expect(() => assertMutationsEnabled('approve_content')).toThrow(AppError);
    try {
      assertMutationsEnabled('approve');
    } catch (err) {
      expect(err).toBeInstanceOf(AppError);
      expect((err as AppError).kind).toBe('mutation_blocked');
    }
  });

  it('blocks retry / resolve / unknown without HTTP', async () => {
    const originalFetch = global.fetch;
    const fetchMock = jest.fn();
    global.fetch = fetchMock as unknown as typeof fetch;

    await expect(retryPublish('att-1')).rejects.toMatchObject({
      kind: 'mutation_blocked',
    });
    await expect(resolveAlert('att-1')).rejects.toMatchObject({
      kind: 'mutation_blocked',
    });
    await expect(
      executeWorkspaceAction({ attentionId: 'att-1', actionId: 'publish' }),
    ).rejects.toMatchObject({ kind: 'mutation_blocked' });
    expect(() => assertActionAllowed('retry_publish')).toThrow(AppError);
    expect(isMobileMutationAllowed('retry_publish')).toBe(false);
    expect(isMobileMutationAllowed('resolve_alert')).toBe(false);

    expect(fetchMock).not.toHaveBeenCalled();
    global.fetch = originalFetch;
  });
});
