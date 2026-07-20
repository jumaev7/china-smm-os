"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarRange, Plus, Settings2, X } from "lucide-react";
import toast from "react-hot-toast";
import {
  CAMPAIGN_LOCALES,
  CAMPAIGN_PLANNER_QUERY_KEY,
  CAMPAIGN_PLATFORMS,
  CAMPAIGN_PLANNER_STATUSES,
  campaignPlannerApi,
  normalizeList,
  type CampaignCreateBody,
  type MarketingCampaign,
} from "@/lib/api";
import { cn, PLATFORM_CONFIG } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import {
  ActionBar,
  DataTable,
  DataTableBody,
  DataTableHead,
  DataTableRow,
  DataTableTd,
  DataTableTh,
  FilterBar,
  PageHeader,
  PageShell,
  StatusBadge,
} from "@/components/ui/design-system";
import { campaignStatusVariant, formatDate, titleCase, toastCampaignError } from "@/lib/campaign-planner-ui";

const STATUS_FILTERS = [
  { label: "All", value: "" },
  ...CAMPAIGN_PLANNER_STATUSES.filter((s) => s !== "archived").map((s) => ({ label: titleCase(s), value: s })),
  { label: "Archived", value: "archived" },
];

export default function CampaignPlannerListPage() {
  const qc = useQueryClient();
  const [statusFilter, setStatusFilter] = useState("");
  const [showCreate, setShowCreate] = useState(false);

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: [...CAMPAIGN_PLANNER_QUERY_KEY, "campaigns", statusFilter],
    queryFn: () =>
      campaignPlannerApi
        .listCampaigns({ status: statusFilter || undefined, limit: 100 })
        .then((r) => r.data),
  });

  const campaigns = normalizeList<MarketingCampaign>(data);

  return (
    <PageShell wide>
      <PageHeader
        title="Campaign Planner"
        subtitle="Plan multi-platform campaigns, generate calendars, and assign existing content."
        icon={CalendarRange}
        actions={
          <>
            <Link href="/campaign-planner/pillars" className="btn-secondary text-sm">
              <Settings2 size={15} /> Content pillars
            </Link>
            <button className="btn-primary text-sm" onClick={() => setShowCreate(true)}>
              <Plus size={15} /> New campaign
            </button>
          </>
        }
      />

      <ActionBar>
        <FilterBar options={STATUS_FILTERS} value={statusFilter} onChange={setStatusFilter} />
      </ActionBar>

      {isLoading ? (
        <LoadingState message="Loading campaigns…" />
      ) : isError ? (
        <ErrorState error={error} onRetry={() => refetch()} />
      ) : campaigns.length === 0 ? (
        <EmptyState
          title={statusFilter ? "No campaigns with this status" : "No campaigns yet"}
          description="Create a campaign to plan a coordinated multi-platform content calendar."
          action={
            <button className="btn-primary text-sm mt-2" onClick={() => setShowCreate(true)}>
              <Plus size={14} /> New campaign
            </button>
          }
        />
      ) : (
        <DataTable>
          <DataTableHead>
            <DataTableRow>
              <DataTableTh>Campaign</DataTableTh>
              <DataTableTh>Status</DataTableTh>
              <DataTableTh>Platforms</DataTableTh>
              <DataTableTh>Timezone</DataTableTh>
              <DataTableTh>Dates</DataTableTh>
              <DataTableTh className="text-right">Updated</DataTableTh>
            </DataTableRow>
          </DataTableHead>
          <DataTableBody>
            {campaigns.map((c) => (
              <CampaignRow key={c.id} campaign={c} />
            ))}
          </DataTableBody>
        </DataTable>
      )}

      {showCreate && (
        <CreateCampaignModal
          onClose={() => setShowCreate(false)}
          onCreated={() => {
            setShowCreate(false);
            qc.invalidateQueries({ queryKey: CAMPAIGN_PLANNER_QUERY_KEY });
          }}
        />
      )}
    </PageShell>
  );
}

function CampaignRow({ campaign }: { campaign: MarketingCampaign }) {
  const dateRange =
    campaign.start_date || campaign.end_date
      ? `${formatDate(campaign.start_date)} → ${formatDate(campaign.end_date)}`
      : "—";
  return (
    <DataTableRow>
      <DataTableTd>
        <Link
          href={`/campaign-planner/${campaign.id}`}
          className="font-medium text-navy-900 hover:text-brand-700 dark-tenant:text-slate-100 dark-tenant:hover:text-violet-300"
        >
          {campaign.name}
        </Link>
        {campaign.objective && (
          <p className="text-xs text-gray-500 dark-tenant:text-slate-500 mt-0.5 line-clamp-1">
            {campaign.objective}
          </p>
        )}
      </DataTableTd>
      <DataTableTd>
        <StatusBadge variant={campaignStatusVariant(campaign.status)} dot>
          {titleCase(campaign.status)}
        </StatusBadge>
      </DataTableTd>
      <DataTableTd>
        <div className="flex flex-wrap gap-1">
          {campaign.platforms.length === 0 ? (
            <span className="text-xs text-gray-400">None</span>
          ) : (
            campaign.platforms.map((p) => (
              <span
                key={p}
                className={cn("text-[10px] px-1.5 py-0.5 rounded-md font-medium", PLATFORM_CONFIG[p]?.color)}
              >
                {PLATFORM_CONFIG[p]?.label ?? p}
              </span>
            ))
          )}
        </div>
      </DataTableTd>
      <DataTableTd>
        <span className="text-xs text-gray-600 dark-tenant:text-slate-400">{campaign.timezone}</span>
      </DataTableTd>
      <DataTableTd>
        <span className="text-xs text-gray-600 dark-tenant:text-slate-400 whitespace-nowrap">{dateRange}</span>
      </DataTableTd>
      <DataTableTd className="text-right">
        <span className="text-xs text-gray-500 dark-tenant:text-slate-500 whitespace-nowrap">
          {formatDate(campaign.updated_at)}
        </span>
      </DataTableTd>
    </DataTableRow>
  );
}

// Common IANA timezones — free-form entry also allowed by the backend.
const TIMEZONE_OPTIONS = [
  "UTC",
  "Asia/Shanghai",
  "Asia/Hong_Kong",
  "Asia/Tashkent",
  "Asia/Dubai",
  "Europe/Moscow",
  "Europe/London",
  "America/New_York",
  "America/Los_Angeles",
];

function CreateCampaignModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const [name, setName] = useState("");
  const [objective, setObjective] = useState("");
  const [description, setDescription] = useState("");
  const [timezone, setTimezone] = useState("UTC");
  const [primaryLocale, setPrimaryLocale] = useState<string>("en");
  const [locales, setLocales] = useState<string[]>(["en"]);
  const [platforms, setPlatforms] = useState<string[]>([]);
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");

  const createMutation = useMutation({
    mutationFn: (body: CampaignCreateBody) => campaignPlannerApi.createCampaign(body),
    onSuccess: () => {
      toast.success("Campaign created");
      onCreated();
    },
    onError: (err) => toastCampaignError(err, "Failed to create campaign"),
  });

  const toggle = (value: string, list: string[], setter: (v: string[]) => void) => {
    setter(list.includes(value) ? list.filter((v) => v !== value) : [...list, value]);
  };

  const canSubmit = name.trim().length > 0 && !createMutation.isPending;

  const handleSubmit = () => {
    if (!canSubmit) return;
    if (startDate && endDate && endDate < startDate) {
      toast.error("End date must be on or after start date");
      return;
    }
    const mergedLocales = locales.includes(primaryLocale) ? locales : [primaryLocale, ...locales];
    createMutation.mutate({
      name: name.trim(),
      objective: objective.trim() || undefined,
      description: description.trim() || undefined,
      timezone,
      primary_locale: primaryLocale,
      locales: mergedLocales,
      platforms,
      start_date: startDate || undefined,
      end_date: endDate || undefined,
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={onClose}>
      <div
        className="card-premium w-full max-w-2xl max-h-[90vh] overflow-y-auto p-6 space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-navy-900 dark-tenant:text-slate-100">New campaign</h2>
          <button onClick={onClose} className="p-1 text-gray-400 hover:text-gray-700">
            <X size={18} />
          </button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="label text-xs">Name *</label>
            <input
              className="input text-sm"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Spring launch campaign"
              autoFocus
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="label text-xs">Objective</label>
              <input
                className="input text-sm"
                value={objective}
                onChange={(e) => setObjective(e.target.value)}
                placeholder="Awareness, launch, retention…"
              />
            </div>
            <div>
              <label className="label text-xs">Timezone</label>
              <input
                className="input text-sm"
                list="cp-timezones"
                value={timezone}
                onChange={(e) => setTimezone(e.target.value)}
              />
              <datalist id="cp-timezones">
                {TIMEZONE_OPTIONS.map((tz) => (
                  <option key={tz} value={tz} />
                ))}
              </datalist>
            </div>
          </div>

          <div>
            <label className="label text-xs">Description</label>
            <textarea
              className="input text-sm min-h-[64px]"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="label text-xs">Start date</label>
              <input
                type="date"
                className="input text-sm"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
              />
            </div>
            <div>
              <label className="label text-xs">End date</label>
              <input
                type="date"
                className="input text-sm"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
              />
            </div>
          </div>

          <div>
            <label className="label text-xs">Platforms</label>
            <div className="flex flex-wrap gap-2 mt-1">
              {CAMPAIGN_PLATFORMS.map((p) => (
                <button
                  type="button"
                  key={p}
                  onClick={() => toggle(p, platforms, setPlatforms)}
                  className={cn(
                    "text-xs px-2.5 py-1 rounded-lg border transition-colors",
                    platforms.includes(p)
                      ? "bg-brand-600 text-white border-brand-600"
                      : "bg-white text-gray-600 border-gray-200 hover:border-brand-300 dark-tenant:bg-white/[0.04] dark-tenant:text-slate-300 dark-tenant:border-white/[0.08]",
                  )}
                >
                  {PLATFORM_CONFIG[p]?.label ?? p}
                </button>
              ))}
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="label text-xs">Primary locale</label>
              <select
                className="input text-sm"
                value={primaryLocale}
                onChange={(e) => setPrimaryLocale(e.target.value)}
              >
                {CAMPAIGN_LOCALES.map((l) => (
                  <option key={l} value={l}>
                    {l.toUpperCase()}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="label text-xs">Additional locales</label>
              <div className="flex flex-wrap gap-2 mt-1">
                {CAMPAIGN_LOCALES.map((l) => (
                  <button
                    type="button"
                    key={l}
                    onClick={() => toggle(l, locales, setLocales)}
                    disabled={l === primaryLocale}
                    className={cn(
                      "text-xs px-2.5 py-1 rounded-lg border transition-colors",
                      locales.includes(l) || l === primaryLocale
                        ? "bg-brand-600 text-white border-brand-600"
                        : "bg-white text-gray-600 border-gray-200 hover:border-brand-300 dark-tenant:bg-white/[0.04] dark-tenant:text-slate-300 dark-tenant:border-white/[0.08]",
                      l === primaryLocale && "opacity-60 cursor-not-allowed",
                    )}
                  >
                    {l.toUpperCase()}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>

        <div className="flex justify-end gap-2 pt-2 border-t border-gray-100 dark-tenant:border-white/[0.06]">
          <button className="btn-secondary text-sm" onClick={onClose}>
            Cancel
          </button>
          <button className="btn-primary text-sm" disabled={!canSubmit} onClick={handleSubmit}>
            {createMutation.isPending ? "Creating…" : "Create campaign"}
          </button>
        </div>
      </div>
    </div>
  );
}
