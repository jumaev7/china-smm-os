"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import { Megaphone, Plus, ChevronRight } from "lucide-react";
import toast from "react-hot-toast";
import {
  campaignsApi,
  clientsApi,
  Client,
  Campaign,
  CampaignStatus,
  CAMPAIGN_OBJECTIVES,
  normalizeList,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import { useTranslation } from "@/lib/I18nProvider";

const STATUS_STYLES: Record<CampaignStatus, string> = {
  draft: "bg-gray-100 text-gray-700 border-gray-200",
  active: "bg-emerald-100 text-emerald-800 border-emerald-200",
  completed: "bg-sky-100 text-sky-800 border-sky-200",
  archived: "bg-stone-100 text-stone-600 border-stone-200",
};

function formatDate(val: string | null | undefined): string {
  if (!val) return "—";
  try {
    return format(parseISO(val), "MMM d, yyyy");
  } catch {
    return val;
  }
}

function CampaignRow({ campaign }: { campaign: Campaign }) {
  return (
    <Link
      href={`/campaigns/${campaign.id}`}
      className="card p-0 overflow-hidden hover:ring-1 hover:ring-brand-200 transition-shadow block"
    >
      <div className="grid grid-cols-[1fr_auto] sm:grid-cols-[2fr_1.2fr_1fr_0.6fr_0.8fr_0.8fr_0.8fr_auto] gap-3 items-center px-4 py-3 text-sm">
        <p className="font-semibold text-gray-900 truncate">{campaign.name}</p>
        <p className="text-gray-600 truncate hidden sm:block">{campaign.client_name ?? "—"}</p>
        <p className="text-gray-600 truncate hidden sm:block">{campaign.objective ?? "—"}</p>
        <p className="text-gray-900 tabular-nums hidden sm:block">{campaign.posts_count}</p>
        <span
          className={cn(
            "text-[10px] px-2 py-0.5 rounded-full border font-medium capitalize hidden sm:inline-flex w-fit",
            STATUS_STYLES[campaign.status],
          )}
        >
          {campaign.status}
        </span>
        <p className="text-xs text-gray-500 hidden sm:block">{formatDate(campaign.start_date)}</p>
        <p className="text-xs text-gray-500 hidden sm:block">{formatDate(campaign.end_date)}</p>
        <ChevronRight size={16} className="text-gray-400 shrink-0" />
      </div>
      <div className="sm:hidden px-4 pb-3 flex flex-wrap gap-2 text-xs text-gray-500">
        <span>{campaign.client_name}</span>
        <span>·</span>
        <span>{campaign.posts_count} posts</span>
        <span>·</span>
        <span className="capitalize">{campaign.status}</span>
      </div>
    </Link>
  );
}

export default function CampaignsPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [statusFilter, setStatusFilter] = useState("");
  const [clientId, setClientId] = useState("");
  const [name, setName] = useState("");
  const [objective, setObjective] = useState("");
  const [description, setDescription] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");

  const { data: clients } = useQuery({
    queryKey: ["clients"],
    queryFn: () => clientsApi.list({ limit: 200 }).then((r) => r.data),
  });
  const clientOptions = normalizeList<Client>(clients);

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["campaigns", statusFilter, clientId],
    queryFn: () =>
      campaignsApi
        .list({
          status: (statusFilter as CampaignStatus) || undefined,
          client_id: clientId || undefined,
          limit: 200,
        })
        .then((r) => r.data),
  });

  const createMutation = useMutation({
    mutationFn: () =>
      campaignsApi
        .create({
          client_id: clientId,
          name: name.trim(),
          objective: objective || null,
          description: description.trim() || null,
          start_date: startDate || null,
          end_date: endDate || null,
        })
        .then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["campaigns"] });
      setShowForm(false);
      setName("");
      setObjective("");
      setDescription("");
      setStartDate("");
      setEndDate("");
      toast.success("Campaign created");
    },
    onError: (err: Error) => toast.error(err.message || "Failed to create campaign"),
  });

  const campaigns = normalizeList<Campaign>(data);

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
            <Megaphone size={22} className="text-orange-600" />
            {t("campaigns.title")}
          </h1>
          <p className="text-sm text-gray-500 mt-1">{t("campaigns.subtitle")}</p>
        </div>
        <button type="button" onClick={() => setShowForm(!showForm)} className="btn-primary text-sm flex items-center gap-1.5">
          <Plus size={14} />
          {t("campaigns.newCampaign")}
        </button>
      </div>

      <div className="flex flex-wrap gap-3">
        <select className="input text-sm min-w-[160px]" value={clientId} onChange={(e) => setClientId(e.target.value)}>
          <option value="">{t("common.allClients")}</option>
          {clientOptions.map((c) => (
            <option key={c.id} value={c.id}>{c.company_name}</option>
          ))}
        </select>
        <select className="input text-sm min-w-[130px]" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="">All statuses</option>
          {(["draft", "active", "completed", "archived"] as CampaignStatus[]).map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </div>

      {showForm && (
        <div className="card p-4 space-y-3">
          <p className="text-sm font-semibold text-gray-900">New campaign</p>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-2">
            <select className="input text-sm" value={clientId} onChange={(e) => setClientId(e.target.value)} required>
              <option value="">Client *</option>
              {clientOptions.map((c) => (
                <option key={c.id} value={c.id}>{c.company_name}</option>
              ))}
            </select>
            <input className="input text-sm" placeholder="Campaign name *" value={name} onChange={(e) => setName(e.target.value)} />
            <select className="input text-sm" value={objective} onChange={(e) => setObjective(e.target.value)}>
              <option value="">Objective</option>
              {CAMPAIGN_OBJECTIVES.map((o) => (
                <option key={o} value={o}>{o}</option>
              ))}
            </select>
            <input className="input text-sm" type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
            <input className="input text-sm" type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
          </div>
          <textarea
            className="input text-sm min-h-[72px]"
            placeholder="Description (optional)"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
          <button
            type="button"
            disabled={!clientId || !name.trim() || createMutation.isPending}
            onClick={() => createMutation.mutate()}
            className="text-sm px-4 py-2 rounded-lg bg-brand-600 text-white disabled:opacity-50"
          >
            {createMutation.isPending ? "Creating…" : "Create campaign"}
          </button>
        </div>
      )}

      <div className="hidden sm:grid grid-cols-[2fr_1.2fr_1fr_0.6fr_0.8fr_0.8fr_0.8fr_auto] gap-3 px-4 text-[10px] uppercase tracking-wide text-gray-400 font-medium">
        <span>Name</span>
        <span>Client</span>
        <span>Objective</span>
        <span>Posts</span>
        <span>Status</span>
        <span>Start</span>
        <span>End</span>
        <span />
      </div>

      {isLoading && <LoadingState message={t("campaigns.loading")} />}
      {isError && (
        <ErrorState
          message={error instanceof Error ? error.message : t("campaigns.loadError")}
          onRetry={() => refetch()}
        />
      )}
      {!isLoading && !isError && campaigns.length === 0 && (
        <EmptyState title={t("campaigns.emptyTitle")} description={t("campaigns.emptyDescription")} />
      )}
      <div className="space-y-2">
        {campaigns.map((c) => (
          <CampaignRow key={c.id} campaign={c} />
        ))}
      </div>
    </div>
  );
}
