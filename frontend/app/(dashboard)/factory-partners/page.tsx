"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Building2,
  Check,
  ExternalLink,
  Loader2,
  UserPlus,
  Rocket,
  X,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  factoryPartnerPortalApi,
  pilotOnboardingApi,
  realFactoryPilotApi,
  FactoryPartnerApplication,
  FactoryPartnerApplicationStatus,
  normalizeList,
} from "@/lib/api";
import { AdminAuthGuard } from "@/components/auth/AdminAuthGuard";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";

const STATUS_FILTERS: { label: string; value: string }[] = [
  { label: "All", value: "" },
  { label: "Submitted", value: "submitted" },
  { label: "Under review", value: "under_review" },
  { label: "Approved", value: "approved" },
  { label: "Rejected", value: "rejected" },
  { label: "Draft", value: "draft" },
];

const STATUS_STYLES: Record<FactoryPartnerApplicationStatus, string> = {
  draft: "bg-gray-100 text-gray-700",
  submitted: "bg-sky-100 text-sky-800",
  under_review: "bg-amber-100 text-amber-800",
  approved: "bg-emerald-100 text-emerald-800",
  rejected: "bg-red-100 text-red-800",
};

export default function FactoryPartnersPage() {
  return (
    <AdminAuthGuard requireAdmin>
      <FactoryPartnersPageContent />
    </AdminAuthGuard>
  );
}

function FactoryPartnersPageContent() {
  const qc = useQueryClient();
  const [statusFilter, setStatusFilter] = useState("");
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const { data: listData, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["factory-partner-applications", statusFilter, search],
    queryFn: () =>
      factoryPartnerPortalApi
        .list({
          status: statusFilter || undefined,
          search: search || undefined,
          limit: 100,
        })
        .then((r) => r.data),
  });

  const { data: detail } = useQuery({
    queryKey: ["factory-partner-application", selectedId],
    queryFn: () => factoryPartnerPortalApi.get(selectedId!).then((r) => r.data),
    enabled: !!selectedId,
  });

  const { data: pilotReadiness } = useQuery({
    queryKey: ["pilot-onboarding-detail", selectedId],
    queryFn: () => pilotOnboardingApi.get(selectedId!).then((r) => r.data),
    enabled: !!selectedId,
  });

  const { data: pilotCandidate } = useQuery({
    queryKey: ["real-factory-pilot-candidate", selectedId],
    queryFn: () => realFactoryPilotApi.candidateIndicator(selectedId!).then((r) => r.data),
    enabled: !!selectedId,
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["factory-partner-applications"] });
    qc.invalidateQueries({ queryKey: ["factory-partner-application"] });
    qc.invalidateQueries({ queryKey: ["factory-partner-summary"] });
    qc.invalidateQueries({ queryKey: ["pilot-onboarding"] });
  };

  const approveMutation = useMutation({
    mutationFn: (id: string) => factoryPartnerPortalApi.approve(id).then((r) => r.data),
    onSuccess: (d) => {
      toast.success(d.message);
      invalidate();
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const rejectMutation = useMutation({
    mutationFn: (id: string) => factoryPartnerPortalApi.reject(id).then((r) => r.data),
    onSuccess: (d) => {
      toast.success(d.message);
      invalidate();
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const createClientMutation = useMutation({
    mutationFn: (id: string) => factoryPartnerPortalApi.createClient(id).then((r) => r.data),
    onSuccess: (d) => {
      toast.success(d.message);
      invalidate();
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const createPortalMutation = useMutation({
    mutationFn: (id: string) => factoryPartnerPortalApi.createPortalAccount(id).then((r) => r.data),
    onSuccess: (d) => {
      toast.success(d.message);
      invalidate();
      qc.invalidateQueries({ queryKey: ["customer-portal-accounts"] });
      qc.invalidateQueries({ queryKey: ["customer-portal-summary"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const createTenantMutation = useMutation({
    mutationFn: (id: string) => factoryPartnerPortalApi.createTenant(id).then((r) => r.data),
    onSuccess: (d) => {
      toast.success(d.message);
      invalidate();
      qc.invalidateQueries({ queryKey: ["tenants"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const reviewMutation = useMutation({
    mutationFn: (id: string) =>
      factoryPartnerPortalApi.update(id, { status: "under_review" }).then((r) => r.data),
    onSuccess: () => {
      toast.success("Marked under review");
      invalidate();
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const items = normalizeList(listData?.items ?? listData);
  const selected = detail ?? items.find((a: FactoryPartnerApplication) => a.id === selectedId);

  if (isLoading) return <LoadingState message="Loading factory applications…" />;
  if (isError) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "Failed to load applications"}
        onRetry={() => refetch()}
      />
    );
  }

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
            <Building2 size={22} className="text-indigo-600" />
            Factory Partners
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Review onboarding applications — manual approve/reject only
          </p>
        </div>
        <Link href="/factory-apply" className="text-sm text-brand-700 hover:underline flex items-center gap-1">
          Public apply form <ExternalLink size={14} />
        </Link>
        <Link href="/pilot-onboarding" className="text-sm text-violet-700 hover:underline flex items-center gap-1">
          Pilot onboarding <Rocket size={14} />
        </Link>
      </div>

      <section className="space-y-3">
        <p className="text-sm font-semibold text-gray-900">1. Applications list</p>
        <div className="flex flex-wrap gap-2 items-end">
          <div className="flex flex-wrap gap-1">
            {STATUS_FILTERS.map((f) => (
              <button
                key={f.value}
                type="button"
                onClick={() => setStatusFilter(f.value)}
                className={cn(
                  "px-3 py-1 rounded-full text-xs border",
                  statusFilter === f.value
                    ? "bg-indigo-100 border-indigo-200 text-indigo-800"
                    : "bg-white border-gray-200 text-gray-600",
                )}
              >
                {f.label}
              </button>
            ))}
          </div>
          <input
            className="input max-w-xs"
            placeholder="Search company…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        {items.length === 0 ? (
          <EmptyState title="No applications" description="Adjust filters or share the apply link." />
        ) : (
          <div className="card overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-left text-xs text-gray-500">
                <tr>
                  <th className="px-4 py-2">Company</th>
                  <th className="px-4 py-2">Country</th>
                  <th className="px-4 py-2">Status</th>
                  <th className="px-4 py-2">Submitted</th>
                </tr>
              </thead>
              <tbody>
                {items.map((app: FactoryPartnerApplication) => (
                  <tr
                    key={app.id}
                    onClick={() => setSelectedId(app.id)}
                    className={cn(
                      "border-t cursor-pointer hover:bg-gray-50",
                      selectedId === app.id && "bg-indigo-50/50",
                    )}
                  >
                    <td className="px-4 py-2 font-medium">
                      <span className="inline-flex items-center gap-1.5">
                        {app.company_name}
                        {app.status !== "rejected" &&
                          !app.company_description?.includes("[PILOT_LAUNCH_DEMO_V1]") &&
                          !app.company_name?.includes("(Pilot)") && (
                            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-indigo-100 text-indigo-800 font-normal">
                              Pilot candidate
                            </span>
                          )}
                      </span>
                    </td>
                    <td className="px-4 py-2">{app.country ?? "—"}</td>
                    <td className="px-4 py-2">
                      <span className={cn("text-xs px-2 py-0.5 rounded-full", STATUS_STYLES[app.status])}>
                        {app.status}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-gray-500 text-xs">
                      {app.submitted_at ? new Date(app.submitted_at).toLocaleDateString() : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {selected && pilotCandidate?.is_selected_factory && (
        <section className="card p-4 space-y-2 border-indigo-200 bg-indigo-50/30">
          <p className="text-sm font-semibold text-indigo-900 flex items-center gap-1.5">
            <Rocket size={16} />
            Real Pilot candidate — selected factory
          </p>
          <p className="text-xs text-indigo-800">
            Readiness {pilotCandidate.readiness_score}% · Status:{" "}
            {pilotCandidate.status.replace(/_/g, " ")}
          </p>
          <Link href="/real-factory-pilot" className="text-xs text-brand-700 hover:underline">
            Open real factory pilot workspace →
          </Link>
        </section>
      )}

      {selected && pilotReadiness && (
        <section className="card p-5 space-y-3 border-violet-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Rocket size={16} className="text-violet-600" />
              Pilot readiness
            </p>
            <Link href="/pilot-onboarding" className="text-xs text-brand-700 hover:underline">
              Full onboarding workspace →
            </Link>
          </div>
          <div className="flex items-center gap-4">
            <span className="text-2xl font-bold text-violet-800 tabular-nums">
              {pilotReadiness.readiness_score}%
            </span>
            <span className="text-xs px-2 py-0.5 rounded-full bg-violet-100 text-violet-800 capitalize">
              {pilotReadiness.status.replace("_", " ")}
            </span>
          </div>
          {pilotReadiness.next_best_action && (
            <p className="text-xs text-gray-600">
              Next: {pilotReadiness.next_best_action.label}
            </p>
          )}
          {pilotReadiness.blockers.length > 0 && (
            <ul className="text-xs text-red-700 space-y-1">
              {pilotReadiness.blockers.slice(0, 3).map((b) => (
                <li key={b.blocker}>• {b.label}</li>
              ))}
            </ul>
          )}
        </section>
      )}

      {selected && (
        <section className="card p-5 space-y-4">
          <p className="text-sm font-semibold text-gray-900">3. Application detail</p>
          <div className="grid sm:grid-cols-2 gap-3 text-sm">
            <div><span className="text-gray-500">Company</span><p className="font-medium">{selected.company_name}</p></div>
            <div><span className="text-gray-500">Status</span><p className="font-medium capitalize">{selected.status}</p></div>
            <div><span className="text-gray-500">Contact</span><p>{selected.contact_name ?? "—"}</p></div>
            <div><span className="text-gray-500">Email</span><p>{selected.contact_email ?? "—"}</p></div>
            <div><span className="text-gray-500">Industry</span><p>{selected.industry ?? "—"}</p></div>
            <div><span className="text-gray-500">Commission</span><p>{selected.commission_model ?? "—"}</p></div>
          </div>
          {selected.company_description && (
            <p className="text-sm text-gray-600">{selected.company_description}</p>
          )}
          {selected.product_categories?.length > 0 && (
            <p className="text-xs text-gray-500">
              Products: {selected.product_categories.join(", ")}
            </p>
          )}
          {selected.target_markets?.length > 0 && (
            <p className="text-xs text-gray-500">
              Markets: {selected.target_markets.join(", ")}
            </p>
          )}

          <div className="flex flex-wrap gap-2 pt-2 border-t">
            {selected.status === "submitted" && (
              <button
                type="button"
                className="btn-secondary text-sm"
                disabled={reviewMutation.isPending}
                onClick={() => reviewMutation.mutate(selected.id)}
              >
                Mark under review
              </button>
            )}
            {(selected.status === "submitted" || selected.status === "under_review") && (
              <>
                <button
                  type="button"
                  className="btn-primary text-sm flex items-center gap-1"
                  disabled={approveMutation.isPending}
                  onClick={() => {
                    if (confirm("Approve this factory application?")) {
                      approveMutation.mutate(selected.id);
                    }
                  }}
                >
                  {approveMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
                  Approve
                </button>
                <button
                  type="button"
                  className="btn-secondary text-sm text-red-700 border-red-200 flex items-center gap-1"
                  disabled={rejectMutation.isPending}
                  onClick={() => {
                    if (confirm("Reject this application?")) {
                      rejectMutation.mutate(selected.id);
                    }
                  }}
                >
                  <X size={14} /> Reject
                </button>
              </>
            )}
            {selected.status === "approved" && !selected.tenant_id && (
              <button
                type="button"
                className="btn-secondary text-sm flex items-center gap-1"
                disabled={createTenantMutation.isPending}
                onClick={() => {
                  if (
                    confirm(
                      "Create SaaS tenant for this factory? Links approved application to isolated company scope.",
                    )
                  ) {
                    createTenantMutation.mutate(selected.id);
                  }
                }}
              >
                {createTenantMutation.isPending ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <UserPlus size={14} />
                )}
                Create Tenant
              </button>
            )}
            {selected.status === "approved" && !selected.created_client_id && (
              <button
                type="button"
                className="btn-primary text-sm flex items-center gap-1"
                disabled={createClientMutation.isPending}
                onClick={() => {
                  if (
                    confirm(
                      "Create CRM client profile from this application? This is a manual admin action only.",
                    )
                  ) {
                    createClientMutation.mutate(selected.id);
                  }
                }}
              >
                {createClientMutation.isPending ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <UserPlus size={14} />
                )}
                Create Client from Application
              </button>
            )}
            {selected.created_client_id && (
              <>
                <Link
                  href={`/clients/${selected.created_client_id}`}
                  className="text-sm text-brand-700 flex items-center gap-1"
                >
                  View client <ExternalLink size={14} />
                </Link>
                {selected.status === "approved" && (
                  <button
                    type="button"
                    className="btn-primary text-sm flex items-center gap-1"
                    disabled={createPortalMutation.isPending}
                    onClick={() => {
                      if (
                        confirm(
                          "Create customer portal account for this factory? Read-only company-scoped access only.",
                        )
                      ) {
                        createPortalMutation.mutate(selected.id);
                      }
                    }}
                  >
                    {createPortalMutation.isPending ? (
                      <Loader2 size={14} className="animate-spin" />
                    ) : (
                      <UserPlus size={14} />
                    )}
                    Create Portal Account
                  </button>
                )}
              </>
            )}
          </div>
        </section>
      )}
    </div>
  );
}
