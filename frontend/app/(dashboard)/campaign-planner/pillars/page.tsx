"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Plus, Settings2 } from "lucide-react";
import toast from "react-hot-toast";
import {
  CAMPAIGN_PLANNER_QUERY_KEY,
  campaignPlannerApi,
  normalizeList,
  type ContentPillar,
  type ContentPillarCreateBody,
} from "@/lib/api";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import {
  DataTable,
  DataTableBody,
  DataTableHead,
  DataTableRow,
  DataTableTd,
  DataTableTh,
  PageHeader,
  PageShell,
  StatusBadge,
} from "@/components/ui/design-system";
import { toastCampaignError } from "@/lib/campaign-planner-ui";

export default function ContentPillarsPage() {
  const qc = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [weight, setWeight] = useState(1);

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: [...CAMPAIGN_PLANNER_QUERY_KEY, "pillars"],
    queryFn: () => campaignPlannerApi.listPillars().then((r) => r.data),
  });
  const pillars = normalizeList<ContentPillar>(data);

  const createMut = useMutation({
    mutationFn: (body: ContentPillarCreateBody) => campaignPlannerApi.createPillar(body),
    onSuccess: () => {
      toast.success("Pillar created");
      setShowCreate(false);
      setName("");
      setDescription("");
      setWeight(1);
      qc.invalidateQueries({ queryKey: [...CAMPAIGN_PLANNER_QUERY_KEY, "pillars"] });
    },
    onError: (err) => toastCampaignError(err, "Could not create pillar"),
  });

  const toggleMut = useMutation({
    mutationFn: ({ id, is_active }: { id: string; is_active: boolean }) =>
      campaignPlannerApi.updatePillar(id, { is_active }),
    onSuccess: () => {
      toast.success("Pillar updated");
      qc.invalidateQueries({ queryKey: [...CAMPAIGN_PLANNER_QUERY_KEY, "pillars"] });
    },
    onError: (err) => toastCampaignError(err, "Could not update pillar"),
  });

  return (
    <PageShell wide>
      <PageHeader
        title="Content pillars"
        subtitle="Reusable strategic themes for campaign planning. Pillars are not auto-inferred by AI."
        icon={Settings2}
        actions={
          <>
            <Link href="/campaign-planner" className="btn-secondary text-sm">
              <ArrowLeft size={15} /> Campaigns
            </Link>
            <button className="btn-primary text-sm" onClick={() => setShowCreate(true)}>
              <Plus size={15} /> New pillar
            </button>
          </>
        }
      />

      {isLoading ? (
        <LoadingState message="Loading pillars…" />
      ) : isError ? (
        <ErrorState error={error} onRetry={() => refetch()} />
      ) : pillars.length === 0 ? (
        <EmptyState
          title="No content pillars yet"
          description="Create pillars such as product education, customer proof, or lead generation."
          action={
            <button className="btn-primary text-sm mt-2" onClick={() => setShowCreate(true)}>
              <Plus size={14} /> New pillar
            </button>
          }
        />
      ) : (
        <DataTable>
          <DataTableHead>
            <DataTableRow>
              <DataTableTh>Name</DataTableTh>
              <DataTableTh>Slug</DataTableTh>
              <DataTableTh>Weight</DataTableTh>
              <DataTableTh>Status</DataTableTh>
              <DataTableTh className="text-right">Actions</DataTableTh>
            </DataTableRow>
          </DataTableHead>
          <DataTableBody>
            {pillars.map((p) => (
              <DataTableRow key={p.id}>
                <DataTableTd>
                  <p className="font-medium text-gray-900">{p.name}</p>
                  {p.description ? (
                    <p className="text-xs text-gray-500 mt-0.5 line-clamp-2">{p.description}</p>
                  ) : null}
                </DataTableTd>
                <DataTableTd className="text-xs text-gray-600 font-mono">{p.slug}</DataTableTd>
                <DataTableTd className="tabular-nums">{p.default_weight}</DataTableTd>
                <DataTableTd>
                  <StatusBadge variant={p.is_active ? "success" : "neutral"}>
                    {p.is_active ? "Active" : "Inactive"}
                  </StatusBadge>
                </DataTableTd>
                <DataTableTd className="text-right">
                  <button
                    className="btn-secondary text-xs py-1"
                    disabled={toggleMut.isPending}
                    onClick={() => toggleMut.mutate({ id: p.id, is_active: !p.is_active })}
                  >
                    {p.is_active ? "Deactivate" : "Activate"}
                  </button>
                </DataTableTd>
              </DataTableRow>
            ))}
          </DataTableBody>
        </DataTable>
      )}

      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="card w-full max-w-md p-5 space-y-4">
            <h2 className="text-lg font-semibold text-gray-900">New content pillar</h2>
            <label className="block text-sm">
              <span className="text-gray-700">Name</span>
              <input
                className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={160}
              />
            </label>
            <label className="block text-sm">
              <span className="text-gray-700">Description</span>
              <textarea
                className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                rows={3}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </label>
            <label className="block text-sm">
              <span className="text-gray-700">Default weight</span>
              <input
                type="number"
                min={1}
                max={100}
                className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                value={weight}
                onChange={(e) => setWeight(Number(e.target.value) || 1)}
              />
            </label>
            <div className="flex justify-end gap-2 pt-2">
              <button className="btn-secondary text-sm" onClick={() => setShowCreate(false)}>
                Cancel
              </button>
              <button
                className="btn-primary text-sm"
                disabled={!name.trim() || createMut.isPending}
                onClick={() =>
                  createMut.mutate({
                    name: name.trim(),
                    description: description.trim() || null,
                    default_weight: weight,
                  })
                }
              >
                Create
              </button>
            </div>
          </div>
        </div>
      )}
    </PageShell>
  );
}
