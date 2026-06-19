/** Fast-first overview pages: core widget loads first; heavy overview is optional. */
export const OVERVIEW_WIDGET_QUERY_OPTIONS = {
  retry: 1,
  staleTime: 60_000,
  refetchOnWindowFocus: false,
  refetchOnReconnect: false,
} as const;

export const OVERVIEW_HEAVY_QUERY_OPTIONS = {
  retry: false,
  staleTime: 120_000,
  refetchOnWindowFocus: false,
  refetchOnReconnect: false,
} as const;

export const OVERVIEW_SECTION_QUERY_OPTIONS = {
  retry: false,
  staleTime: 60_000,
  refetchOnWindowFocus: false,
  refetchOnReconnect: false,
} as const;

/**
 * SSR-safe initial loading gate for overview pages.
 * Prefer this over `isLoading`: on the server React Query v5 sets isFetching=false,
 * so isLoading is false while data is still undefined — causing hydration mismatches.
 */
export function isOverviewLoading<T>(data: T | undefined, isError: boolean): boolean {
  return data == null && !isError;
}
