"use client";

import { useMemo, useState, useEffect } from "react";
import Link from "next/link";
import { useSearchParams, useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import {
  AlertTriangle,
  Briefcase,
  ChevronRight,
  FileText,
  Globe,
  Loader2,
  RefreshCw,
  Shield,
  Sparkles,
  Target,
  TrendingUp,
  Users,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  dealRoomApi,
  dealRoomV2Api,
  DealRoomV2ListItem,
  DealRoomV2Workspace,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PartialErrorsBanner,
} from "@/components/ui/PageStates";
import { PageHeader, PageShell } from "@/components/ui/design-system";
import { useTranslation } from "@/lib/I18nProvider";

const V2_STAGE_STYLES: Record<string, string> = {
  inquiry: "bg-gray-100 text-gray-700 border-gray-200",
  qualification: "bg-sky-100 text-sky-800 border-sky-200",
  quotation: "bg-indigo-100 text-indigo-800 border-indigo-200",
  negotiation: "bg-violet-100 text-violet-800 border-violet-200",
  sample: "bg-purple-100 text-purple-800 border-purple-200",
  contract: "bg-amber-100 text-amber-800 border-amber-200",
  payment: "bg-orange-100 text-orange-800 border-orange-200",
  closed_won: "bg-emerald-100 text-emerald-800 border-emerald-200",
  closed_lost: "bg-red-100 text-red-800 border-red-200",
};

const RISK_COLORS: Record<string, string> = {
  high: "text-red-600",
  medium: "text-amber-600",
  low: "text-emerald-600",
};

function formatValue(val: number | string | null | undefined): string {
  if (val == null || val === "") return "—";
  const n = typeof val === "string" ? parseFloat(val) : val;
  if (Number.isNaN(n)) return String(val);
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(n);
}

function probColor(score: number): string {
  if (score >= 70) return "text-emerald-600";
  if (score >= 40) return "text-amber-600";
  return "text-red-600";
}

function DealOverviewPanel({ ws }: { ws: DealRoomV2Workspace }) {
  const { t } = useTranslation();
  const ov = ws.deal_overview;
  if (!ov) return null;
  return (
    <div className="card p-4 space-y-3">
      <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
        <Target size={16} className="text-violet-600" />
        {t("deal.sectionOverview")}
      </p>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        <div>
          <p className="text-[10px] text-gray-500 uppercase">{t("deal.healthScore")}</p>
          <p className={cn("text-xl font-bold tabular-nums", probColor(ov.deal_health_score))}>
            {ov.deal_health_score}
          </p>
        </div>
        <div>
          <p className="text-[10px] text-gray-500 uppercase">{t("deal.dealValue")}</p>
          <p className="text-lg font-semibold tabular-nums">{formatValue(ov.deal_value)} {ov.currency}</p>
        </div>
        <div>
          <p className="text-[10px] text-gray-500 uppercase">{t("deal.expectedRevenue")}</p>
          <p className="text-lg font-semibold tabular-nums text-emerald-700">
            {formatValue(ov.expected_revenue)} {ov.currency}
          </p>
        </div>
        <div>
          <p className="text-[10px] text-gray-500 uppercase">{t("deal.closeProbability")}</p>
          <p className={cn("text-lg font-semibold tabular-nums", probColor(ov.close_probability))}>
            {ov.close_probability}%
          </p>
        </div>
        <div>
          <p className="text-[10px] text-gray-500 uppercase">{t("deal.estCloseDate")}</p>
          <p className="text-sm font-medium">
            {ov.estimated_close_date
              ? format(parseISO(ov.estimated_close_date), "MMM d, yyyy")
              : "—"}
          </p>
        </div>
        <div>
          <p className="text-[10px] text-gray-500 uppercase">{t("deal.dealOwner")}</p>
          <p className="text-sm font-medium">{ov.deal_owner || "—"}</p>
        </div>
      </div>
    </div>
  );
}

function PipelinePanel({ ws }: { ws: DealRoomV2Workspace }) {
  const { t } = useTranslation();
  const pipe = ws.pipeline;
  if (!pipe) return null;
  return (
    <div className="card p-4 space-y-3">
      <p className="text-sm font-semibold text-gray-900">{t("deal.sectionPipeline")}</p>
      <p className="text-xs text-gray-500">
        {t("deal.currentStage")}{" "}
        <span className="font-medium text-gray-800">{pipe.current_stage_label}</span>
      </p>
      <div className="flex flex-wrap gap-1">
        {pipe.stages.map((s) => (
          <span
            key={s.stage}
            className={cn(
              "text-[9px] px-2 py-1 rounded-full border capitalize",
              s.status === "current"
                ? V2_STAGE_STYLES[s.stage] + " ring-2 ring-violet-300 font-semibold"
                : s.status === "completed"
                  ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                  : "bg-gray-50 text-gray-400 border-gray-100",
            )}
          >
            {s.label}
          </span>
        ))}
      </div>
    </div>
  );
}

function BuyerPanel({ ws }: { ws: DealRoomV2Workspace }) {
  const { t } = useTranslation();
  const buyer = ws.buyer_information;
  if (!buyer) return null;
  return (
    <div className="card p-4 space-y-3">
      <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
        <Users size={16} className="text-brand-600" />
        {t("deal.sectionBuyerInfo")}
      </p>
      <div className="space-y-1 text-sm">
        <p className="font-medium">{buyer.company_name || "—"}</p>
        {buyer.contact_name && <p className="text-gray-600">{buyer.contact_name}</p>}
        <div className="grid grid-cols-2 gap-2 text-xs text-gray-600 mt-2">
          <p>
            {t("deal.buyerCountry")}: {buyer.country || "—"}
          </p>
          <p>
            {t("deal.buyerIndustry")}: {buyer.industry || "—"}
          </p>
          <p className="capitalize">
            {t("deal.buyerRelationship")}: {buyer.relationship_strength}
          </p>
          <p className="capitalize">
            {t("deal.buyerSource")}: {buyer.acquisition_source}
          </p>
          {buyer.match_score != null && (
            <p>
              {t("deal.matchScore")}: {buyer.match_score}
            </p>
          )}
        </div>
      </div>
      <Link href="/buyer-acquisition-engine" className="text-xs text-brand-700 hover:underline">
        {t("deal.openBuyerEngine")}
      </Link>
    </div>
  );
}

function RevenuePanel({ ws }: { ws: DealRoomV2Workspace }) {
  const { t } = useTranslation();
  const rev = ws.revenue_integration;
  if (!rev) return null;
  return (
    <div className="card p-4 space-y-3">
      <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
        <TrendingUp size={16} className="text-emerald-600" />
        {t("deal.sectionRevenue")}
      </p>
      <div className="grid grid-cols-2 gap-2 text-xs">
        <div>
          <p className="text-gray-500">{t("deal.expectedRevenue")}</p>
          <p className="font-semibold">{formatValue(rev.expected_revenue)} {rev.currency}</p>
        </div>
        <div>
          <p className="text-gray-500">{t("deal.weighted")}</p>
          <p className="font-semibold">{formatValue(rev.weighted_revenue)} {rev.currency}</p>
        </div>
        <div>
          <p className="text-gray-500">{t("dashboard.forecast")}</p>
          <p className="font-semibold capitalize">{rev.revenue_forecast_impact.replace(/_/g, " ")}</p>
        </div>
        <div>
          <p className="text-gray-500">{t("deal.pipeline")}</p>
          <p className="font-semibold">{formatValue(rev.pipeline_contribution)} {rev.currency}</p>
        </div>
      </div>
      <Link href="/revenue-engine" className="text-xs text-brand-700 hover:underline">
        {t("deal.openRevenueEngine")}
      </Link>
    </div>
  );
}

function RiskPanel({ ws }: { ws: DealRoomV2Workspace }) {
  const { t } = useTranslation();
  const risk = ws.risk_assessment;
  if (!risk) return null;
  const dims = [
    { label: t("deal.riskCommercial"), score: risk.commercial_risk, level: risk.commercial_risk_level },
    { label: t("deal.riskPayment"), score: risk.payment_risk, level: risk.payment_risk_level },
    { label: t("deal.riskLogistics"), score: risk.logistics_risk, level: risk.logistics_risk_level },
    { label: t("deal.riskCompliance"), score: risk.compliance_risk, level: risk.compliance_risk_level },
  ];
  return (
    <div className="card p-4 space-y-3 border-red-50">
      <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
        <Shield size={16} className="text-red-500" />
        {t("deal.sectionRisk")}
      </p>
      <div className="flex items-center justify-between">
        <p className="text-xs text-gray-600">{t("deal.healthScore")}</p>
        <p className={cn("text-lg font-bold tabular-nums", RISK_COLORS[risk.overall_risk_level])}>
          {risk.overall_risk_score}/100
        </p>
      </div>
      <div className="grid grid-cols-2 gap-2">
        {dims.map((d) => (
          <div key={d.label} className="text-xs border border-gray-100 rounded-lg p-2">
            <p className="text-gray-500">{d.label}</p>
            <p className={cn("font-semibold capitalize", RISK_COLORS[d.level])}>
              {d.score} · {d.level}
            </p>
          </div>
        ))}
      </div>
      {(risk.risk_factors?.length ?? 0) > 0 && (
        <ul className="text-[10px] text-orange-700 space-y-0.5">
          {risk.risk_factors.slice(0, 4).map((f) => (
            <li key={f}>• {f.replace(/_/g, " ")}</li>
          ))}
        </ul>
      )}
      <Link href="/deal-risk" className="text-xs text-brand-700 hover:underline">
        {t("deal.openDealRisk")}
      </Link>
    </div>
  );
}

function DocumentsPanel({ ws }: { ws: DealRoomV2Workspace }) {
  const { t } = useTranslation();
  const docs = ws.documents;
  if (!docs) return null;
  const cats: Record<string, string> = {
    quotation: t("deal.docQuotations"),
    contract: t("deal.docContracts"),
    certificate: t("deal.docCertificates"),
    shipping_document: t("deal.docShipping"),
    payment_confirmation: t("deal.docPayments"),
  };
  return (
    <div className="card p-4 space-y-3">
      <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
        <FileText size={16} className="text-indigo-600" />
        {t("deal.sectionDocuments")}
      </p>
      <div className="flex flex-wrap gap-2 text-[10px]">
        <span className="px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-800">
          {t("deal.docQuotations")}: {docs.quotation_count}
        </span>
        <span className="px-2 py-0.5 rounded-full bg-amber-50 text-amber-800">
          {t("deal.docContracts")}: {docs.contract_count}
        </span>
        <span className="px-2 py-0.5 rounded-full bg-teal-50 text-teal-800">
          {t("deal.docCertificates")}: {docs.certificate_count}
        </span>
        <span className="px-2 py-0.5 rounded-full bg-cyan-50 text-cyan-800">
          {t("deal.docShipping")}: {docs.shipping_count}
        </span>
        <span className="px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-800">
          {t("deal.docPayments")}: {docs.payment_count}
        </span>
      </div>
      {docs.items.length === 0 ? (
        <EmptyState title={t("deal.noDocuments")} description={t("deal.noDocumentsHint")} />
      ) : (
        <ul className="space-y-2 max-h-48 overflow-y-auto">
          {docs.items.slice(0, 12).map((d) => (
            <li key={d.id} className="flex justify-between gap-2 text-xs border-b border-gray-50 pb-1">
              <div>
                <p className="font-medium text-gray-900">{d.title}</p>
                <p className="text-[10px] text-gray-500 capitalize">
                  {cats[d.category] || d.category} · {d.status}
                </p>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function TimelinePanel({ ws }: { ws: DealRoomV2Workspace }) {
  const { t } = useTranslation();
  const tl = ws.activity_timeline;
  if (!tl) return null;
  return (
    <div className="card p-4 space-y-3">
      <p className="text-sm font-semibold text-gray-900">{t("deal.sectionTimeline")}</p>
      {tl.items.length === 0 ? (
        <EmptyState title={t("deal.noActivity")} description={t("deal.noActivityHint")} />
      ) : (
        <ul className="space-y-2 max-h-64 overflow-y-auto">
          {tl.items.map((ev) => (
            <li key={ev.id} className="text-xs border-l-2 border-violet-200 pl-3 py-1">
              <p className="font-medium text-gray-900">{ev.title}</p>
              <p className="text-[10px] text-gray-500 capitalize">
                {ev.category.replace(/_/g, " ")}
                {ev.occurred_at && ` · ${format(parseISO(ev.occurred_at), "MMM d, HH:mm")}`}
              </p>
              {ev.description && (
                <p className="text-[10px] text-gray-600 mt-0.5 line-clamp-2">{ev.description}</p>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function WorkspaceView({ ws }: { ws: DealRoomV2Workspace }) {
  const { t } = useTranslation();
  return (
    <div className="space-y-4">
      <PartialErrorsBanner errors={ws.errors} />
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">{ws.deal_name}</h2>
          <div className="flex flex-wrap items-center gap-2 mt-1">
            {ws.deal_overview && (
              <span
                className={cn(
                  "text-[10px] px-2 py-0.5 rounded-full border font-medium",
                  V2_STAGE_STYLES[ws.deal_overview.current_stage] ?? V2_STAGE_STYLES.inquiry,
                )}
              >
                {ws.deal_overview.current_stage_label}
              </span>
            )}
            <span className="text-xs text-gray-500 capitalize">{ws.status}</span>
            {ws.client_name && <span className="text-xs text-gray-500">{ws.client_name}</span>}
          </div>
        </div>
        <p className="text-[10px] text-gray-400 flex items-center gap-1">
          <AlertTriangle size={10} />
          {t("deal.readOnlyFooter")}
        </p>
      </div>
      <DealOverviewPanel ws={ws} />
      <PipelinePanel ws={ws} />
      <div className="grid lg:grid-cols-2 gap-4">
        <BuyerPanel ws={ws} />
        <RevenuePanel ws={ws} />
        <RiskPanel ws={ws} />
        <DocumentsPanel ws={ws} />
        <div className="lg:col-span-2">
          <TimelinePanel ws={ws} />
        </div>
      </div>
      {(ws.guided_actions?.length ?? 0) > 0 && (
        <div className="card p-4 space-y-2">
          <p className="text-sm font-semibold text-gray-900">{t("deal.sectionGuidedActions")}</p>
          <div className="flex flex-wrap gap-2">
            {ws.guided_actions!.map((a) => (
              <Link
                key={a.action_id}
                href={a.route}
                className="text-xs px-3 py-1.5 rounded-lg border border-gray-200 hover:bg-gray-50"
              >
                {a.title}
              </Link>
            ))}
          </div>
          <p className="text-[10px] text-gray-400">{t("deal.hintsOnly")}</p>
        </div>
      )}
    </div>
  );
}

function DealListItem({
  item,
  selected,
  onSelect,
}: {
  item: DealRoomV2ListItem;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "w-full text-left p-3 rounded-lg border transition-colors",
        selected
          ? "border-violet-300 bg-violet-50/60 ring-1 ring-violet-200"
          : "border-gray-100 hover:border-gray-200 hover:bg-gray-50/50",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-medium text-gray-900 truncate">{item.deal_name}</p>
          {item.client_name && (
            <p className="text-[10px] text-gray-500 truncate">{item.client_name}</p>
          )}
        </div>
        <ChevronRight size={14} className="text-gray-300 shrink-0 mt-0.5" />
      </div>
      <div className="flex items-center gap-2 mt-2">
        <span
          className={cn(
            "text-[9px] px-1.5 py-0.5 rounded-full border",
            V2_STAGE_STYLES[item.v2_stage] ?? V2_STAGE_STYLES.inquiry,
          )}
        >
          {item.v2_stage_label}
        </span>
        <span className={cn("text-xs font-semibold tabular-nums", probColor(item.close_probability))}>
          {item.close_probability}%
        </span>
        {item.deal_value > 0 && (
          <span className="text-[10px] text-gray-500">{formatValue(item.deal_value)}</span>
        )}
      </div>
    </button>
  );
}

export default function DealRoomPage() {
  const { t } = useTranslation();
  const searchParams = useSearchParams();
  const router = useRouter();
  const queryClient = useQueryClient();
  const initialId = searchParams.get("id");
  const leadIdParam = searchParams.get("lead_id");
  const [selectedId, setSelectedId] = useState<string | null>(initialId);

  const leadBootstrapMutation = useMutation({
    mutationFn: () => dealRoomApi.findOrCreate({ crm_lead_id: leadIdParam! }).then((r) => r.data),
    onSuccess: (room) => {
      setSelectedId(room.id);
      router.replace(`/deal-room?id=${room.id}`);
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const refreshMutation = useMutation({
    mutationFn: () => dealRoomV2Api.refresh().then((r) => r.data),
    onSuccess: (data) => {
      toast.success(`Assessment refreshed — readiness ${data.readiness_score}%`);
      queryClient.invalidateQueries({ queryKey: ["deal-room-v2"] });
    },
    onError: () => toast.error(t("pilot.refreshFailed")),
  });

  const { data: overview } = useQuery({
    queryKey: ["deal-room-v2-overview"],
    queryFn: () => dealRoomV2Api.overview().then((r) => r.data),
  });

  const { data: listData, isLoading: listLoading, isError: listError, error: listErr, refetch: refetchList } =
    useQuery({
      queryKey: ["deal-room-v2-list"],
      queryFn: () => dealRoomV2Api.workspaces({ limit: 50 }).then((r) => r.data),
    });

  const activeId = selectedId ?? initialId ?? listData?.items?.[0]?.id ?? null;

  const { data: workspace, isLoading: wsLoading, isError: wsError, error: wsErr, refetch: refetchWs } =
    useQuery({
      queryKey: ["deal-room-v2-workspace", activeId],
      queryFn: () => dealRoomV2Api.workspace(activeId!).then((r) => r.data),
      enabled: !!activeId,
    });

  const items = useMemo(() => listData?.items ?? [], [listData]);

  useEffect(() => {
    if (leadIdParam && !initialId && !leadBootstrapMutation.isPending && !leadBootstrapMutation.isSuccess) {
      leadBootstrapMutation.mutate();
    }
  }, [leadIdParam, initialId]); // eslint-disable-line react-hooks/exhaustive-deps

  if (listLoading || (leadIdParam && !initialId && leadBootstrapMutation.isPending)) {
    return <LoadingState message={t("common.loading")} />;
  }
  if (listError) {
    return (
      <ErrorState
        message={listErr instanceof Error ? listErr.message : t("dashboard.loadError")}
        onRetry={() => refetchList()}
      />
    );
  }

  return (
    <PageShell wide>
      <PageHeader
        title={t("deal.title")}
        subtitle={t("deal.subtitle")}
        icon={Briefcase}
        actions={
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="btn-secondary text-sm inline-flex items-center gap-1.5"
              disabled={refreshMutation.isPending}
              onClick={() => refreshMutation.mutate()}
            >
              {refreshMutation.isPending ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <RefreshCw size={14} />
              )}
              {t("pilot.refresh")}
            </button>
            <Link href="/crm" className="btn-secondary text-sm inline-flex items-center gap-1">
              <Sparkles size={12} />
              {t("deal.crm")}
            </Link>
          </div>
        }
      />

      {overview && (
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 mb-4">
          <div className="card p-3 text-center">
            <p className="text-[10px] text-gray-500">{t("deal.readiness")}</p>
            <p className="text-lg font-bold text-violet-700">{overview.readiness_score}%</p>
          </div>
          <div className="card p-3 text-center">
            <p className="text-[10px] text-gray-500">{t("deal.activeDeals")}</p>
            <p className="text-lg font-bold">{overview.active_deal_rooms}</p>
          </div>
          <div className="card p-3 text-center">
            <p className="text-[10px] text-gray-500">{t("deal.pipeline")}</p>
            <p className="text-lg font-bold tabular-nums">{formatValue(overview.total_pipeline_value)}</p>
          </div>
          <div className="card p-3 text-center">
            <p className="text-[10px] text-gray-500">{t("deal.weighted")}</p>
            <p className="text-lg font-bold tabular-nums">{formatValue(overview.weighted_pipeline_value)}</p>
          </div>
          <div className="card p-3 text-center">
            <p className="text-[10px] text-gray-500">{t("deal.highRisk")}</p>
            <p className="text-lg font-bold text-red-600">{overview.high_risk_deals}</p>
          </div>
        </div>
      )}

      <div className="grid lg:grid-cols-12 gap-6">
        <div className="lg:col-span-4 space-y-3">
          <p className="text-sm font-semibold text-gray-900">
            {t("deal.dealsList", { total: listData?.total ?? 0 })}
          </p>
          {items.length === 0 ? (
            <EmptyState
              title={t("deal.noDealRooms")}
              description={t("deal.createHint")}
            />
          ) : (
            <div className="space-y-2 max-h-[70vh] overflow-y-auto pr-1">
              {items.map((item) => (
                <DealListItem
                  key={item.id}
                  item={item}
                  selected={item.id === activeId}
                  onSelect={() => setSelectedId(item.id)}
                />
              ))}
            </div>
          )}
        </div>

        <div className="lg:col-span-8">
          {!activeId ? (
            <EmptyState title={t("deal.selectDeal")} description={t("deal.selectDealHint")} />
          ) : wsLoading ? (
            <LoadingState message={t("common.loading")} />
          ) : wsError || !workspace ? (
            <ErrorState
              message={wsErr instanceof Error ? wsErr.message : t("dashboard.loadError")}
              onRetry={() => refetchWs()}
            />
          ) : (
            <WorkspaceView ws={workspace} />
          )}
        </div>
      </div>

      <p className="text-[10px] text-gray-400 flex items-center gap-1 mt-4">
        <Globe size={10} />
        {overview?.safety_notice || t("deal.safetyFooter")}
      </p>
    </PageShell>
  );
}
