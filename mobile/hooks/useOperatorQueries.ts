import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useCallback } from 'react';
import { AppState } from 'react-native';
import { useEffect } from 'react';

import { fetchMobileHome, fetchMobileSystem, fetchWorkspaceItems } from '@/api/mobileControl';
import { QUERY_STALE_TIME_MS } from '@/config/constants';
import type { AttentionCategory } from '@/types/workspace';
import { APPROVAL_CATEGORIES, PROBLEM_CATEGORIES } from '@/types/workspace';

export const queryKeys = {
  home: ['mobile-control', 'home'] as const,
  system: ['mobile-control', 'system'] as const,
  approvals: ['operator-workspace', 'approvals'] as const,
  problems: ['operator-workspace', 'problems'] as const,
};

export function useMobileHome() {
  return useQuery({
    queryKey: queryKeys.home,
    queryFn: () => fetchMobileHome(10),
    staleTime: QUERY_STALE_TIME_MS,
  });
}

export function useMobileSystem() {
  return useQuery({
    queryKey: queryKeys.system,
    queryFn: () => fetchMobileSystem(),
    staleTime: QUERY_STALE_TIME_MS,
  });
}

async function fetchByCategories(categories: AttentionCategory[]) {
  const pages = await Promise.all(
    categories.map((category) => fetchWorkspaceItems({ category, pageSize: 50 })),
  );
  const items = pages.flatMap((p) => p.items);
  // Preserve backend priority ordering within merged list.
  const order: Record<string, number> = {
    critical: 0,
    high: 1,
    medium: 2,
    low: 3,
  };
  items.sort((a, b) => (order[a.priority] ?? 9) - (order[b.priority] ?? 9));
  return {
    items,
    total: items.length,
    summary: pages[0]?.summary,
  };
}

export function useApprovals() {
  return useQuery({
    queryKey: queryKeys.approvals,
    queryFn: () => fetchByCategories(APPROVAL_CATEGORIES),
    staleTime: QUERY_STALE_TIME_MS,
  });
}

export function useProblems() {
  return useQuery({
    queryKey: queryKeys.problems,
    queryFn: () => fetchByCategories(PROBLEM_CATEGORIES),
    staleTime: QUERY_STALE_TIME_MS,
  });
}

/** Refresh operator queries when app returns to foreground. */
export function useRefreshOnForeground(): void {
  const client = useQueryClient();

  useEffect(() => {
    const sub = AppState.addEventListener('change', (state) => {
      if (state === 'active') {
        void client.invalidateQueries({ queryKey: ['mobile-control'] });
        void client.invalidateQueries({ queryKey: ['operator-workspace'] });
      }
    });
    return () => sub.remove();
  }, [client]);
}

export function usePullToRefresh(keys: readonly unknown[]) {
  const client = useQueryClient();
  return useCallback(async () => {
    await client.invalidateQueries({ queryKey: [...keys] });
  }, [client, keys]);
}
