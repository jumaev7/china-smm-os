"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  customerSuccessApi,
  customerSuccessJourneyApi,
  tenantOnboardingApi,
  type CustomerSuccessJourneyDashboard,
} from "@/lib/api";

export const JOURNEY_QUERY_KEY = ["customer-success", "journey"] as const;

export function useCustomerSuccessJourney() {
  return useQuery({
    queryKey: JOURNEY_QUERY_KEY,
    queryFn: () => customerSuccessJourneyApi.journey().then((r) => r.data),
    staleTime: 30_000,
  });
}

export function useCustomerSuccessSummary() {
  return useQuery({
    queryKey: ["customer-success", "summary"],
    queryFn: () => customerSuccessApi.summary().then((r) => r.data),
    staleTime: 30_000,
  });
}

export function useOnboardingReadinessForJourney() {
  return useQuery({
    queryKey: ["tenant-onboarding-readiness"],
    queryFn: () => tenantOnboardingApi.readiness().then((r) => r.data),
    staleTime: 60_000,
  });
}

export function useJourneyRefresh() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => customerSuccessJourneyApi.refresh().then((r) => r.data),
    onSuccess: (res) => {
      qc.setQueryData<CustomerSuccessJourneyDashboard>(JOURNEY_QUERY_KEY, res.journey);
    },
  });
}

export function useDismissJourneyRecommendation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (recommendationId: string) =>
      customerSuccessJourneyApi.dismissRecommendation(recommendationId).then((r) => r.data),
    onSuccess: (res) => {
      qc.setQueryData<CustomerSuccessJourneyDashboard>(JOURNEY_QUERY_KEY, res.journey);
    },
  });
}
