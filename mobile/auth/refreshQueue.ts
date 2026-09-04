/**
 * Single-flight access-token refresh.
 * Concurrent waiters share one in-flight refresh promise.
 */

type RefreshFn = () => Promise<string | null>;

let inFlight: Promise<string | null> | null = null;

export async function runSingleFlightRefresh(fn: RefreshFn): Promise<string | null> {
  if (inFlight) {
    return inFlight;
  }
  inFlight = (async () => {
    try {
      return await fn();
    } finally {
      inFlight = null;
    }
  })();
  return inFlight;
}

/** Test helper — reset in-flight state between cases. */
export function __resetRefreshFlightForTests(): void {
  inFlight = null;
}

export function __hasRefreshInFlightForTests(): boolean {
  return inFlight != null;
}
