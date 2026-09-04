/**
 * @jest-environment node
 */
import { MOBILE_MUTATIONS_ENABLED } from '../config/constants';
import { assertMutationsEnabled } from '../api/guard';
import {
  acknowledgeAlert,
  approveContent,
  executeWorkspaceAction,
  resolveAlert,
  retryPublish,
} from '../api/mutations';
import { AppError } from '../utils/errors';

describe('mutation hard-block', () => {
  it('keeps MOBILE_MUTATIONS_ENABLED false in Phase 2', () => {
    expect(MOBILE_MUTATIONS_ENABLED).toBe(false);
  });

  it('assertMutationsEnabled throws before any work', () => {
    expect(() => assertMutationsEnabled('approve_content')).toThrow(AppError);
    try {
      assertMutationsEnabled('approve');
    } catch (err) {
      expect(err).toBeInstanceOf(AppError);
      expect((err as AppError).kind).toBe('mutation_blocked');
    }
  });

  it('blocks approve / retry / acknowledge / resolve without HTTP', async () => {
    const originalFetch = global.fetch;
    const fetchMock = jest.fn();
    global.fetch = fetchMock as unknown as typeof fetch;

    await expect(approveContent('att-1')).rejects.toMatchObject({
      kind: 'mutation_blocked',
    });
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
      executeWorkspaceAction({ attentionId: 'att-1', actionId: 'approve_content' }),
    ).rejects.toMatchObject({ kind: 'mutation_blocked' });

    expect(fetchMock).not.toHaveBeenCalled();
    global.fetch = originalFetch;
  });
});
