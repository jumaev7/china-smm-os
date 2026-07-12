"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  NOTIFICATION_LIST_QUERY_KEY,
  NOTIFICATION_UNREAD_COUNT_QUERY_KEY,
  notificationApi,
} from "@/lib/api";
import { useTranslation } from "@/lib/I18nProvider";
import { useOnboardingTenantId } from "@/lib/onboarding-hooks";
import {
  computeNotificationSummary,
  DEFAULT_NOTIFICATION_FILTERS,
  filterNotificationsByTime,
  mapApiNotificationToApp,
  sortNotifications,
  type AppNotification,
  type NotificationFilters,
} from "@/lib/notification-center-ui";

const PAGE_SIZE = 20;

function buildListParams(filters: NotificationFilters, page: number) {
  return {
    page,
    page_size: PAGE_SIZE,
    category: filters.category,
    severity: filters.severity,
    is_read: filters.read === "unread" ? false : undefined,
    search: filters.search,
  };
}

export function useNotificationUnreadCount(enabled = true) {
  return useQuery({
    queryKey: NOTIFICATION_UNREAD_COUNT_QUERY_KEY,
    queryFn: () => notificationApi.getNotificationUnreadCount().then((r) => r.data),
    enabled,
    staleTime: 30_000,
    refetchOnWindowFocus: true,
  });
}

export function useNotificationCenter() {
  const tenantId = useOnboardingTenantId();
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [filters, setFilters] = useState<NotificationFilters>(DEFAULT_NOTIFICATION_FILTERS);
  const [page, setPage] = useState(1);
  const [accumulated, setAccumulated] = useState<AppNotification[]>([]);

  const listParams = useMemo(() => buildListParams(filters, page), [filters, page]);

  const listQuery = useQuery({
    queryKey: [...NOTIFICATION_LIST_QUERY_KEY, tenantId, listParams],
    queryFn: () => notificationApi.getNotifications(listParams).then((r) => r.data),
    enabled: Boolean(tenantId),
  });

  const unreadCountQuery = useNotificationUnreadCount(Boolean(tenantId));

  useEffect(() => {
    setPage(1);
    setAccumulated([]);
  }, [tenantId, filters.category, filters.severity, filters.read, filters.search]);

  useEffect(() => {
    if (!listQuery.data) return;
    const mapped = listQuery.data.items.map((item) => mapApiNotificationToApp(item, t));
    setAccumulated((prev) => {
      if (page === 1) return mapped;
      const seen = new Set(prev.map((n) => n.id));
      const merged = [...prev];
      for (const item of mapped) {
        if (!seen.has(item.id)) merged.push(item);
      }
      return sortNotifications(merged);
    });
  }, [listQuery.data, page, t]);

  const invalidateNotifications = useCallback(async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: NOTIFICATION_LIST_QUERY_KEY }),
      queryClient.invalidateQueries({ queryKey: NOTIFICATION_UNREAD_COUNT_QUERY_KEY }),
    ]);
  }, [queryClient]);

  const markReadMutation = useMutation({
    mutationFn: (id: string) => notificationApi.markNotificationRead(id),
    onSuccess: async () => {
      await invalidateNotifications();
    },
  });

  const markAllReadMutation = useMutation({
    mutationFn: () => notificationApi.markAllNotificationsRead(),
    onSuccess: async () => {
      await invalidateNotifications();
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => notificationApi.deleteNotification(id),
    onSuccess: async () => {
      await invalidateNotifications();
    },
  });

  const updateFilters = useCallback((patch: Partial<NotificationFilters>) => {
    setFilters((prev) => ({ ...prev, ...patch }));
  }, []);

  const resetFilters = useCallback(() => {
    setFilters(DEFAULT_NOTIFICATION_FILTERS);
  }, []);

  const filtered = useMemo(
    () => sortNotifications(filterNotificationsByTime(accumulated, filters.time)),
    [accumulated, filters.time],
  );

  const summary = useMemo(() => {
    const local = computeNotificationSummary(accumulated);
    return {
      ...local,
      unreadCount: unreadCountQuery.data?.unread_count ?? local.unreadCount,
    };
  }, [accumulated, unreadCountQuery.data?.unread_count]);

  const hasActiveFilters =
    filters.category !== "all" ||
    filters.severity !== "all" ||
    filters.read !== "all" ||
    filters.time !== "all" ||
    filters.search.trim().length > 0;

  const loadMore = useCallback(() => {
    if (listQuery.data && page < listQuery.data.pages) {
      setPage((p) => p + 1);
    }
  }, [listQuery.data, page]);

  const markAsRead = useCallback(
    (id: string) => {
      setAccumulated((prev) => prev.map((n) => (n.id === id ? { ...n, read: true } : n)));
      markReadMutation.mutate(id);
    },
    [markReadMutation],
  );

  const markAllAsRead = useCallback(() => {
    setAccumulated((prev) => prev.map((n) => ({ ...n, read: true })));
    markAllReadMutation.mutate();
  }, [markAllReadMutation]);

  const dismissNotification = useCallback(
    (id: string) => {
      setAccumulated((prev) => prev.filter((n) => n.id !== id));
      deleteMutation.mutate(id);
    },
    [deleteMutation],
  );

  const retry = useCallback(() => {
    void listQuery.refetch();
    void unreadCountQuery.refetch();
  }, [listQuery, unreadCountQuery]);

  return {
    tenantId,
    notifications: accumulated,
    filtered,
    filters,
    summary,
    isLoading: listQuery.isLoading && page === 1,
    isLoadingMore: listQuery.isFetching && page > 1,
    isError: listQuery.isError,
    error: listQuery.error,
    hasActiveFilters,
    hasMore: Boolean(listQuery.data && page < listQuery.data.pages),
    total: listQuery.data?.total ?? 0,
    updateFilters,
    resetFilters,
    markAsRead,
    markAllAsRead,
    dismissNotification,
    loadMore,
    retry,
    isMutating:
      markReadMutation.isPending || markAllReadMutation.isPending || deleteMutation.isPending,
  };
}
