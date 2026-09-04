/**
 * @jest-environment node
 */
import {
  __hasRefreshInFlightForTests,
  __resetRefreshFlightForTests,
  runSingleFlightRefresh,
} from '../auth/refreshQueue';

describe('refresh stampede prevention', () => {
  beforeEach(() => {
    __resetRefreshFlightForTests();
  });

  it('shares a single in-flight refresh across concurrent callers', async () => {
    let calls = 0;
    const fn = async () => {
      calls += 1;
      await new Promise((r) => setTimeout(r, 40));
      return 'token-a';
    };

    const p1 = runSingleFlightRefresh(fn);
    expect(__hasRefreshInFlightForTests()).toBe(true);
    const p2 = runSingleFlightRefresh(fn);
    const p3 = runSingleFlightRefresh(fn);

    const [a, b, c] = await Promise.all([p1, p2, p3]);
    expect(calls).toBe(1);
    expect(a).toBe('token-a');
    expect(b).toBe('token-a');
    expect(c).toBe('token-a');
    expect(__hasRefreshInFlightForTests()).toBe(false);
  });

  it('allows a new refresh after the previous one settles', async () => {
    let calls = 0;
    const fn = async () => {
      calls += 1;
      return `t-${calls}`;
    };
    await runSingleFlightRefresh(fn);
    const second = await runSingleFlightRefresh(fn);
    expect(calls).toBe(2);
    expect(second).toBe('t-2');
  });
});
