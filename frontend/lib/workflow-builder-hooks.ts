"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  WORKFLOWS_CATALOG_QUERY_KEY,
  WORKFLOWS_LIST_QUERY_KEY,
  workflowsApi,
  type WorkflowDetail,
  type WorkflowStatus,
} from "@/lib/api";

export function useWorkflowCatalog() {
  return useQuery({
    queryKey: WORKFLOWS_CATALOG_QUERY_KEY,
    queryFn: async () => (await workflowsApi.getCatalog()).data,
  });
}

export function useWorkflowsList(status?: WorkflowStatus) {
  return useQuery({
    queryKey: [...WORKFLOWS_LIST_QUERY_KEY, status ?? "all"],
    queryFn: async () => (await workflowsApi.list({ page_size: 50, status })).data,
  });
}

export function useWorkflowDetail(id: string | undefined) {
  return useQuery({
    queryKey: [...WORKFLOWS_LIST_QUERY_KEY, "detail", id],
    queryFn: async () => (await workflowsApi.get(id!)).data,
    enabled: Boolean(id),
  });
}

export function useWorkflowMutations(workflowId?: string) {
  const qc = useQueryClient();
  const invalidate = async () => {
    await qc.invalidateQueries({ queryKey: WORKFLOWS_LIST_QUERY_KEY });
    if (workflowId) {
      await qc.invalidateQueries({ queryKey: [...WORKFLOWS_LIST_QUERY_KEY, "detail", workflowId] });
    }
  };

  const create = useMutation({
    mutationFn: async (body: { name: string; description?: string; definition?: Record<string, unknown> }) =>
      (await workflowsApi.create(body)).data,
    onSuccess: invalidate,
  });

  const update = useMutation({
    mutationFn: async (body: {
      id: string;
      draft_revision: number;
      name?: string;
      description?: string;
      definition?: Record<string, unknown>;
    }) => {
      const { id, ...rest } = body;
      return (await workflowsApi.update(id, rest)).data as WorkflowDetail;
    },
    onSuccess: invalidate,
  });

  const publish = useMutation({
    mutationFn: async (id: string) => (await workflowsApi.publish(id)).data,
    onSuccess: invalidate,
  });

  const pause = useMutation({
    mutationFn: async (id: string) => (await workflowsApi.pause(id)).data,
    onSuccess: invalidate,
  });

  const resume = useMutation({
    mutationFn: async (id: string) => (await workflowsApi.resume(id)).data,
    onSuccess: invalidate,
  });

  const archive = useMutation({
    mutationFn: async (id: string) => (await workflowsApi.archive(id)).data,
    onSuccess: invalidate,
  });

  const clone = useMutation({
    mutationFn: async (id: string) => (await workflowsApi.clone(id)).data,
    onSuccess: invalidate,
  });

  const validate = useMutation({
    mutationFn: async (args: { id: string; definition?: Record<string, unknown> }) =>
      (await workflowsApi.validate(args.id, args.definition)).data,
  });

  const test = useMutation({
    mutationFn: async (args: {
      id: string;
      synthetic_payload?: Record<string, unknown>;
      version_id?: string;
    }) =>
      (
        await workflowsApi.test(args.id, {
          mode: "evaluate_only",
          synthetic_payload: args.synthetic_payload,
          version_id: args.version_id,
        })
      ).data,
  });

  return { create, update, publish, pause, resume, archive, clone, validate, test, invalidate };
}
