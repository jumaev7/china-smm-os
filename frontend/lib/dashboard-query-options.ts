/** Shared React Query defaults for dashboard widgets — avoid focus refetch storms. */
export const DASHBOARD_CORE_QUERY_OPTIONS = {
  refetchOnWindowFocus: false,
  refetchOnReconnect: false,
} as const;

export const DASHBOARD_OPTIONAL_WIDGET_OPTIONS = {
  refetchOnWindowFocus: false,
  refetchOnReconnect: false,
  retry: false,
} as const;
