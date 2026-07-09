"use client";

import { useQuery } from "@tanstack/react-query";
import { metaPublishingApi, publishingApi, tenantOnboardingApi } from "@/lib/api";
import { useOnboardingReadiness, useOnboardingTenantId } from "@/lib/onboarding-hooks";
import {
  computeIntegrationSummary,
  resolveAllIntegrations,
  type IntegrationDataContext,
  type ResolvedIntegration,
} from "@/lib/integration-center-ui";

export const INTEGRATION_ACCOUNTS_KEY = ["integration-center", "accounts"] as const;
export const INTEGRATION_META_KEY = ["integration-center", "meta"] as const;
export const INTEGRATION_CHANNELS_KEY = ["integration-center", "channels"] as const;

export function useIntegrationCenterData() {
  const tenantId = useOnboardingTenantId();
  const scopeParams = tenantId ? { tenant_id: tenantId } : undefined;
  const readinessQuery = useOnboardingReadiness();

  const accountsQuery = useQuery({
    queryKey: [...INTEGRATION_ACCOUNTS_KEY, tenantId],
    queryFn: () => publishingApi.listAccounts(scopeParams).then((r) => r.data),
    enabled: !!tenantId,
    staleTime: 30_000,
  });

  const metaQuery = useQuery({
    queryKey: [...INTEGRATION_META_KEY, tenantId],
    queryFn: () => metaPublishingApi.getConnection(scopeParams).then((r) => r.data),
    enabled: !!tenantId,
    staleTime: 30_000,
  });

  const channelsQuery = useQuery({
    queryKey: INTEGRATION_CHANNELS_KEY,
    queryFn: () => tenantOnboardingApi.channelStatus().then((r) => r.data),
    staleTime: 30_000,
  });

  const tg = channelsQuery.data?.telegram as
    | { connected?: boolean; group_title?: string | null }
    | undefined;

  const ctx: IntegrationDataContext = {
    accounts: accountsQuery.data?.items ?? [],
    meta: metaQuery.data,
    telegramConnected: !!tg?.connected,
    telegramGroupTitle: tg?.group_title,
    readinessSteps: readinessQuery.data?.platform_steps,
  };

  const integrations = resolveAllIntegrations(ctx);
  const summary = computeIntegrationSummary(integrations);

  const isLoading =
    readinessQuery.isLoading || accountsQuery.isLoading || metaQuery.isLoading || channelsQuery.isLoading;

  const isError = accountsQuery.isError || metaQuery.isError || channelsQuery.isError;

  const error =
    (accountsQuery.error as Error | undefined) ??
    (metaQuery.error as Error | undefined) ??
    (channelsQuery.error as Error | undefined);

  const refetch = () => {
    void readinessQuery.refetch();
    void accountsQuery.refetch();
    void metaQuery.refetch();
    void channelsQuery.refetch();
  };

  return {
    tenantId,
    integrations,
    summary,
    isLoading,
    isError,
    error,
    refetch,
    isFetching:
      readinessQuery.isFetching ||
      accountsQuery.isFetching ||
      metaQuery.isFetching ||
      channelsQuery.isFetching,
  };
}

export type IntegrationCenterData = {
  integrations: ResolvedIntegration[];
  summary: ReturnType<typeof computeIntegrationSummary>;
};
