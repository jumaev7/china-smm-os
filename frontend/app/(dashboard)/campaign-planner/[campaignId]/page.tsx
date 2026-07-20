"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  CalendarRange,
  ClipboardCheck,
  Copy,
  Sparkles,
  Wand2,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  CAMPAIGN_PLANNER_QUERY_KEY,
  campaignPlannerApi,
  normalizeList,
  type CampaignAIPlanRequest,
  type CampaignAudience,
  type CampaignGoal,
  type CampaignKpi,
  type CampaignPhase,
  type CampaignPillarLink,
  type CampaignReview,
  type MarketingCampaign,
  type PlanVersion,
} from "@/lib/api";
import { cn, PLATFORM_CONFIG } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import {
  PageHeader,
  PageSection,
  PageShell,
  StatusBadge,
} from "@/components/ui/design-system";
import {
  campaignStatusVariant,
  formatDate,
  generationMethodLabel,
  isPlanReadOnly,
  planStatusVariant,
  titleCase,
  toastCampaignError,
} from "@/lib/campaign-planner-ui";

type TabKey =
  | "overview"
  | "goals"
  | "audience"
  | "structure"
  | "plans"
  | "review"
  | "ai";

const TABS: { key: TabKey; label: string }[] = [
  { key: "overview", label: "Overview" },
  { key: "goals", label: "Goals & KPIs" },
  { key: "audience", label: "Audience" },
  { key: "structure", label: "Pillars & phases" },
  { key: "plans", label: "Plan history" },
  { key: "review", label: "Review" },
  { key: "ai", label: "AI proposal" },
];

export default function CampaignDetailPage() {
  const params = useParams();
  const campaignId = String(params.campaignId || "");
  const qc = useQueryClient();
  const [tab, setTab] = useState<TabKey>("overview");
  const [goalTitle, setGoalTitle] = useState("");
  const [kpiName, setKpiName] = useState("");
  const [kpiKey, setKpiKey] = useState("");
  const [audienceName, setAudienceName] = useState("");
  const [phaseName, setPhaseName] = useState("");
  const [pillarId, setPillarId] = useState("");

  const invalidate = () =>
    qc.invalidateQueries({ queryKey: [...CAMPAIGN_PLANNER_QUERY_KEY, campaignId] });

  const campaignQ = useQuery({
    queryKey: [...CAMPAIGN_PLANNER_QUERY_KEY, campaignId, "detail"],
    queryFn: () => campaignPlannerApi.getCampaign(campaignId).then((r) => r.data),
    enabled: Boolean(campaignId),
  });

  const plansQ = useQuery({
    queryKey: [...CAMPAIGN_PLANNER_QUERY_KEY, campaignId, "plans"],
    queryFn: () => campaignPlannerApi.listPlans(campaignId).then((r) => r.data),
    enabled: Boolean(campaignId),
  });

  const reviewQ = useQuery({
    queryKey: [...CAMPAIGN_PLANNER_QUERY_KEY, campaignId, "review"],
    queryFn: () => campaignPlannerApi.latestReview(campaignId).then((r) => r.data),
    enabled: Boolean(campaignId),
    retry: false,
  });

  const goalsQ = useQuery({
    queryKey: [...CAMPAIGN_PLANNER_QUERY_KEY, campaignId, "goals"],
    queryFn: () => campaignPlannerApi.listGoals(campaignId).then((r) => r.data),
    enabled: Boolean(campaignId) && tab === "goals",
  });
  const kpisQ = useQuery({
    queryKey: [...CAMPAIGN_PLANNER_QUERY_KEY, campaignId, "kpis"],
    queryFn: () => campaignPlannerApi.listKpis(campaignId).then((r) => r.data),
    enabled: Boolean(campaignId) && tab === "goals",
  });
  const audiencesQ = useQuery({
    queryKey: [...CAMPAIGN_PLANNER_QUERY_KEY, campaignId, "audiences"],
    queryFn: () => campaignPlannerApi.listAudiences(campaignId).then((r) => r.data),
    enabled: Boolean(campaignId) && tab === "audience",
  });
  const phasesQ = useQuery({
    queryKey: [...CAMPAIGN_PLANNER_QUERY_KEY, campaignId, "phases"],
    queryFn: () => campaignPlannerApi.listPhases(campaignId).then((r) => r.data),
    enabled: Boolean(campaignId) && (tab === "structure" || tab === "overview"),
  });
  const campPillarsQ = useQuery({
    queryKey: [...CAMPAIGN_PLANNER_QUERY_KEY, campaignId, "camp-pillars"],
    queryFn: () => campaignPlannerApi.listCampaignPillars(campaignId).then((r) => r.data),
    enabled: Boolean(campaignId) && (tab === "structure" || tab === "overview"),
  });
  const pillarsQ = useQuery({
    queryKey: [...CAMPAIGN_PLANNER_QUERY_KEY, "pillars"],
    queryFn: () => campaignPlannerApi.listPillars({ active_only: true }).then((r) => r.data),
    enabled: tab === "structure",
  });
  const aiQ = useQuery({
    queryKey: [...CAMPAIGN_PLANNER_QUERY_KEY, campaignId, "ai"],
    queryFn: () => campaignPlannerApi.listAiPlanRequests(campaignId).then((r) => r.data),
    enabled: Boolean(campaignId) && tab === "ai",
  });

  const campaign = campaignQ.data as MarketingCampaign | undefined;
  const plans = normalizeList<PlanVersion>(plansQ.data);
  const currentPlan = useMemo(() => {
    if (!campaign) return null;
    const id = campaign.current_plan_version_id || campaign.published_plan_version_id;
    return plans.find((p) => p.id === id) || plans[0] || null;
  }, [campaign, plans]);
  const review = reviewQ.data as CampaignReview | undefined;
  const goals = normalizeList<CampaignGoal>(goalsQ.data);
  const kpis = normalizeList<CampaignKpi>(kpisQ.data);
  const audiences = normalizeList<CampaignAudience>(audiencesQ.data);
  const phases = normalizeList<CampaignPhase>(phasesQ.data);
  const campPillars = normalizeList<CampaignPillarLink>(campPillarsQ.data);
  const pillars = normalizeList(pillarsQ.data);
  const aiRequests = normalizeList<CampaignAIPlanRequest>(aiQ.data);

  const generateMut = useMutation({
    mutationFn: () => campaignPlannerApi.generatePlan(campaignId),
    onSuccess: () => {
      toast.success("Draft plan generated (rule-based suggested times)");
      invalidate();
      plansQ.refetch();
    },
    onError: (err) => toastCampaignError(err, "Could not generate plan"),
  });
  const reviewMut = useMutation({
    mutationFn: (planId: string) => campaignPlannerApi.reviewPlan(campaignId, planId),
    onSuccess: () => {
      toast.success("Campaign review saved");
      reviewQ.refetch();
      plansQ.refetch();
    },
    onError: (err) => toastCampaignError(err, "Could not review plan"),
  });
  const publishMut = useMutation({
    mutationFn: (planId: string) => campaignPlannerApi.publishPlan(campaignId, planId),
    onSuccess: () => {
      toast.success("Plan published (immutable)");
      invalidate();
      plansQ.refetch();
    },
    onError: (err) => toastCampaignError(err, "Could not publish plan"),
  });
  const cloneMut = useMutation({
    mutationFn: (planId: string) => campaignPlannerApi.clonePlan(campaignId, planId),
    onSuccess: () => {
      toast.success("Draft plan cloned");
      plansQ.refetch();
      invalidate();
    },
    onError: (err) => toastCampaignError(err, "Could not clone plan"),
  });
  const archiveMut = useMutation({
    mutationFn: () => campaignPlannerApi.archiveCampaign(campaignId),
    onSuccess: () => {
      toast.success("Campaign archived");
      invalidate();
    },
    onError: (err) => toastCampaignError(err, "Could not archive"),
  });
  const aiMut = useMutation({
    mutationFn: () => campaignPlannerApi.requestAiPlan(campaignId, { quality_mode: "standard" }),
    onSuccess: () => {
      toast.success("AI-assisted campaign proposal requested");
      aiQ.refetch();
      setTab("ai");
    },
    onError: (err) => toastCampaignError(err, "AI proposal failed"),
  });
  const applyAiMut = useMutation({
    mutationFn: (requestId: string) => campaignPlannerApi.applyAiPlan(requestId),
    onSuccess: () => {
      toast.success("Proposal applied as a new draft plan (not published)");
      plansQ.refetch();
      aiQ.refetch();
      invalidate();
    },
    onError: (err) => toastCampaignError(err, "Could not apply proposal"),
  });
  const rejectAiMut = useMutation({
    mutationFn: (requestId: string) => campaignPlannerApi.rejectAiPlan(requestId),
    onSuccess: () => {
      toast.success("Proposal rejected");
      aiQ.refetch();
    },
    onError: (err) => toastCampaignError(err, "Could not reject proposal"),
  });

  const addGoalMut = useMutation({
    mutationFn: () => campaignPlannerApi.createGoal(campaignId, { title: goalTitle.trim(), goal_type: "other" }),
    onSuccess: () => {
      toast.success("Goal added");
      setGoalTitle("");
      goalsQ.refetch();
    },
    onError: (err) => toastCampaignError(err),
  });
  const addKpiMut = useMutation({
    mutationFn: () =>
      campaignPlannerApi.createKpi(campaignId, {
        name: kpiName.trim(),
        metric_key: kpiKey.trim() || kpiName.trim().toLowerCase().replace(/\s+/g, "_"),
      }),
    onSuccess: () => {
      toast.success("KPI target added (user goal, not a prediction)");
      setKpiName("");
      setKpiKey("");
      kpisQ.refetch();
    },
    onError: (err) => toastCampaignError(err),
  });
  const addAudienceMut = useMutation({
    mutationFn: () => campaignPlannerApi.createAudience(campaignId, { name: audienceName.trim() }),
    onSuccess: () => {
      toast.success("Audience segment added");
      setAudienceName("");
      audiencesQ.refetch();
    },
    onError: (err) => toastCampaignError(err),
  });
  const addPhaseMut = useMutation({
    mutationFn: () => campaignPlannerApi.createPhase(campaignId, { name: phaseName.trim(), phase_type: "custom" }),
    onSuccess: () => {
      toast.success("Phase added");
      setPhaseName("");
      phasesQ.refetch();
    },
    onError: (err) => toastCampaignError(err),
  });
  const addPillarMut = useMutation({
    mutationFn: () => campaignPlannerApi.addCampaignPillar(campaignId, { pillar_id: pillarId, weight: 1 }),
    onSuccess: () => {
      toast.success("Pillar linked");
      setPillarId("");
      campPillarsQ.refetch();
    },
    onError: (err) => toastCampaignError(err),
  });

  if (campaignQ.isLoading) return <LoadingState message="Loading campaign…" />;
  if (campaignQ.isError || !campaign) {
    return <ErrorState error={campaignQ.error} onRetry={() => campaignQ.refetch()} />;
  }

  const summary = (currentPlan?.summary || {}) as Record<string, unknown>;
  const coverage = typeof review?.coverage_score === "number" ? review.coverage_score : null;
  const readiness = typeof review?.readiness_score === "number" ? review.readiness_score : null;

  return (
    <PageShell wide>
      <PageHeader
        title={campaign.name}
        subtitle={`${formatDate(campaign.start_date)} → ${formatDate(campaign.end_date)} · Timezone ${campaign.timezone}`}
        icon={CalendarRange}
        actions={
          <>
            <Link href="/campaign-planner" className="btn-secondary text-sm">
              <ArrowLeft size={15} /> All campaigns
            </Link>
            <Link
              href={`/campaign-planner/${campaignId}/calendar`}
              className="btn-secondary text-sm"
            >
              Open calendar
            </Link>
            <button
              className="btn-primary text-sm"
              disabled={generateMut.isPending}
              onClick={() => generateMut.mutate()}
            >
              <Wand2 size={15} /> Generate plan
            </button>
          </>
        }
      />

      <div className="flex flex-wrap items-center gap-2 mb-4">
        <StatusBadge variant={campaignStatusVariant(campaign.status)}>
          {titleCase(campaign.status)}
        </StatusBadge>
        {(campaign.platforms || []).map((p) => (
          <span key={p} className="text-xs px-2 py-0.5 rounded border border-gray-200 text-gray-700">
            {PLATFORM_CONFIG[p as keyof typeof PLATFORM_CONFIG]?.label || p}
          </span>
        ))}
        <span className="text-xs text-gray-500">Locales: {(campaign.locales || []).join(", ") || "—"}</span>
      </div>

      <div className="flex flex-wrap gap-1 border-b border-gray-200 mb-5">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setTab(t.key)}
            className={cn(
              "px-3 py-2 text-sm font-medium border-b-2 -mb-px",
              tab === t.key
                ? "border-brand-600 text-brand-700"
                : "border-transparent text-gray-500 hover:text-gray-800",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "overview" && (
        <div className="space-y-5">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <MetricCard label="Plan quality" value={coverage != null ? `${coverage}` : "—"} hint="Advisory coverage score" />
            <MetricCard label="Campaign readiness" value={readiness != null ? `${readiness}` : "—"} hint="Advisory readiness" />
            <MetricCard
              label="Assigned slots"
              value={String(review?.assigned_slots ?? summary.slot_count ?? "—")}
            />
            <MetricCard
              label="Unassigned / blocked"
              value={`${review?.unassigned_slots ?? "—"} / ${review?.blocked_slots ?? "—"}`}
            />
          </div>

          <PageSection title="Campaign">
            <dl className="grid sm:grid-cols-2 gap-3 text-sm">
              <div>
                <dt className="text-gray-500">Objective</dt>
                <dd className="text-gray-900">{campaign.objective || "—"}</dd>
              </div>
              <div>
                <dt className="text-gray-500">Current plan</dt>
                <dd className="text-gray-900">
                  {currentPlan
                    ? `v${currentPlan.version} · ${titleCase(currentPlan.status)} · ${generationMethodLabel(currentPlan.generation_method) || ""}`
                    : "No plan yet"}
                </dd>
              </div>
              <div>
                <dt className="text-gray-500">Description</dt>
                <dd className="text-gray-900 whitespace-pre-wrap">{campaign.description || "—"}</dd>
              </div>
              <div>
                <dt className="text-gray-500">Pillars / phases</dt>
                <dd className="text-gray-900">
                  {campPillars.length} pillars · {phases.length} phases
                </dd>
              </div>
            </dl>
            <p className="mt-3 text-xs text-gray-500">
              Plan quality and Campaign Score are advisory. PublishSafety remains authoritative for publishing.
              Generating or assigning content does not schedule or publish posts.
            </p>
          </PageSection>

          {review && (
            <PageSection title="Top gaps & conflicts">
              <div className="grid md:grid-cols-2 gap-4 text-sm">
                <div>
                  <p className="font-medium text-gray-800 mb-2">Gaps ({review.gap_count ?? 0})</p>
                  <ul className="space-y-1 text-gray-600">
                    {Object.entries(
                      ((review.summary?.gap_types as Record<string, number> | undefined) || {}),
                    )
                      .slice(0, 5)
                      .map(([key, count]) => (
                        <li key={key}>
                          <span className="font-medium">{titleCase(key)}</span> · {count}
                        </li>
                      ))}
                    {!Object.keys((review.summary?.gap_types as object) || {}).length && (
                      <li>No open gaps in the latest review.</li>
                    )}
                  </ul>
                </div>
                <div>
                  <p className="font-medium text-gray-800 mb-2">
                    Conflicts ({review.conflict_count ?? 0})
                  </p>
                  <ul className="space-y-1 text-gray-600">
                    {(((review.summary?.conflicts as Array<{ conflict_key?: string; severity?: string }>) || [])
                      .slice(0, 5)
                      .map((c, idx) => (
                        <li key={`${c.conflict_key}-${idx}`}>
                          {titleCase(c.conflict_key || "conflict")}
                          {c.severity ? ` · ${c.severity}` : ""}
                        </li>
                      )))}
                    {!((review.summary?.conflicts as unknown[]) || []).length && (
                      <li>No conflicts detected in the latest review.</li>
                    )}
                  </ul>
                </div>
              </div>
            </PageSection>
          )}

          <div className="flex flex-wrap gap-2">
            {currentPlan && !isPlanReadOnly(currentPlan.status) && (
              <>
                <button
                  className="btn-secondary text-sm"
                  disabled={reviewMut.isPending}
                  onClick={() => reviewMut.mutate(currentPlan.id)}
                >
                  <ClipboardCheck size={14} /> Review plan
                </button>
                <button
                  className="btn-primary text-sm"
                  disabled={publishMut.isPending}
                  onClick={() => publishMut.mutate(currentPlan.id)}
                >
                  Publish plan version
                </button>
              </>
            )}
            {currentPlan && (
              <button
                className="btn-secondary text-sm"
                disabled={cloneMut.isPending}
                onClick={() => cloneMut.mutate(currentPlan.id)}
              >
                <Copy size={14} /> Clone plan
              </button>
            )}
            <button
              className="btn-secondary text-sm"
              disabled={aiMut.isPending}
              onClick={() => aiMut.mutate()}
            >
              <Sparkles size={14} /> AI-assisted proposal
            </button>
            {campaign.status !== "archived" && (
              <button
                className="btn-secondary text-sm text-red-700"
                disabled={archiveMut.isPending}
                onClick={() => archiveMut.mutate()}
              >
                Archive
              </button>
            )}
          </div>
        </div>
      )}

      {tab === "goals" && (
        <div className="grid md:grid-cols-2 gap-5">
          <PageSection title="Goals">
            <div className="flex gap-2 mb-3">
              <input
                className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm"
                placeholder="Goal title"
                value={goalTitle}
                onChange={(e) => setGoalTitle(e.target.value)}
              />
              <button
                className="btn-primary text-sm"
                disabled={!goalTitle.trim() || addGoalMut.isPending}
                onClick={() => addGoalMut.mutate()}
              >
                Add
              </button>
            </div>
            {goals.length === 0 ? (
              <EmptyState title="No goals" description="Add campaign goals. These are targets, not predictions." />
            ) : (
              <ul className="space-y-2 text-sm">
                {goals.map((g) => (
                  <li key={g.id} className="border border-gray-100 rounded-md px-3 py-2">
                    <p className="font-medium text-gray-900">{g.title}</p>
                    <p className="text-xs text-gray-500">{titleCase(g.goal_type)} · {g.priority}</p>
                  </li>
                ))}
              </ul>
            )}
          </PageSection>
          <PageSection title="KPI targets">
            <p className="text-xs text-gray-500 mb-2">User-defined targets only — not predicted outcomes.</p>
            <div className="flex flex-wrap gap-2 mb-3">
              <input
                className="flex-1 min-w-[8rem] rounded-md border border-gray-300 px-3 py-2 text-sm"
                placeholder="KPI name"
                value={kpiName}
                onChange={(e) => setKpiName(e.target.value)}
              />
              <input
                className="w-36 rounded-md border border-gray-300 px-3 py-2 text-sm"
                placeholder="metric_key"
                value={kpiKey}
                onChange={(e) => setKpiKey(e.target.value)}
              />
              <button
                className="btn-primary text-sm"
                disabled={!kpiName.trim() || addKpiMut.isPending}
                onClick={() => addKpiMut.mutate()}
              >
                Add
              </button>
            </div>
            {kpis.length === 0 ? (
              <EmptyState title="No KPIs" description="Optional KPI targets for this campaign." />
            ) : (
              <ul className="space-y-2 text-sm">
                {kpis.map((k) => (
                  <li key={k.id} className="border border-gray-100 rounded-md px-3 py-2">
                    <p className="font-medium text-gray-900">{k.name}</p>
                    <p className="text-xs text-gray-500 font-mono">{k.metric_key}
                      {k.target_value != null ? ` · target ${k.comparator} ${k.target_value}` : ""}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </PageSection>
        </div>
      )}

      {tab === "audience" && (
        <PageSection title="Audience segments">
          <div className="flex gap-2 mb-3">
            <input
              className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm"
              placeholder="Audience name"
              value={audienceName}
              onChange={(e) => setAudienceName(e.target.value)}
            />
            <button
              className="btn-primary text-sm"
              disabled={!audienceName.trim() || addAudienceMut.isPending}
              onClick={() => addAudienceMut.mutate()}
            >
              Add
            </button>
          </div>
          {audiences.length === 0 ? (
            <EmptyState title="No audiences" description="Define segments without storing unnecessary personal data." />
          ) : (
            <ul className="space-y-2 text-sm">
              {audiences.map((a) => (
                <li key={a.id} className="border border-gray-100 rounded-md px-3 py-2">
                  <p className="font-medium text-gray-900">{a.name}</p>
                  <p className="text-xs text-gray-500">{a.locale || "any locale"} · {(a.platforms || []).join(", ") || "any platform"}</p>
                </li>
              ))}
            </ul>
          )}
        </PageSection>
      )}

      {tab === "structure" && (
        <div className="grid md:grid-cols-2 gap-5">
          <PageSection title="Campaign pillars">
            <div className="flex gap-2 mb-3">
              <select
                className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm"
                value={pillarId}
                onChange={(e) => setPillarId(e.target.value)}
              >
                <option value="">Select pillar…</option>
                {pillars.map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
              <button
                className="btn-primary text-sm"
                disabled={!pillarId || addPillarMut.isPending}
                onClick={() => addPillarMut.mutate()}
              >
                Link
              </button>
            </div>
            <Link href="/campaign-planner/pillars" className="text-xs text-brand-600 hover:underline mb-2 inline-block">
              Manage tenant pillars
            </Link>
            {campPillars.length === 0 ? (
              <EmptyState title="No pillars linked" description="Link content pillars to weight calendar generation." />
            ) : (
              <ul className="space-y-2 text-sm">
                {campPillars.map((l) => {
                  const p = pillars.find((x) => x.id === l.pillar_id);
                  return (
                    <li key={l.id} className="border border-gray-100 rounded-md px-3 py-2 flex justify-between">
                      <span>{p?.name || l.pillar_id}</span>
                      <span className="text-gray-500">weight {l.weight}</span>
                    </li>
                  );
                })}
              </ul>
            )}
          </PageSection>
          <PageSection title="Phases">
            <div className="flex gap-2 mb-3">
              <input
                className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm"
                placeholder="Phase name"
                value={phaseName}
                onChange={(e) => setPhaseName(e.target.value)}
              />
              <button
                className="btn-primary text-sm"
                disabled={!phaseName.trim() || addPhaseMut.isPending}
                onClick={() => addPhaseMut.mutate()}
              >
                Add
              </button>
            </div>
            {phases.length === 0 ? (
              <EmptyState title="No phases" description="Optional teaser/launch/education windows." />
            ) : (
              <ul className="space-y-2 text-sm">
                {phases.map((p) => (
                  <li key={p.id} className="border border-gray-100 rounded-md px-3 py-2">
                    <p className="font-medium">{p.name}</p>
                    <p className="text-xs text-gray-500">
                      {titleCase(p.phase_type)} · {formatDate(p.start_date)} → {formatDate(p.end_date)}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </PageSection>
        </div>
      )}

      {tab === "plans" && (
        <PageSection title="Plan history">
          {plans.length === 0 ? (
            <EmptyState title="No plans" description="Generate a deterministic draft plan to get started." />
          ) : (
            <ul className="space-y-2">
              {plans.map((p) => (
                <li key={p.id} className="card p-3 flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <p className="font-medium text-gray-900">
                      Version {p.version}{" "}
                      <StatusBadge variant={planStatusVariant(p.status)}>{titleCase(p.status)}</StatusBadge>
                    </p>
                    <p className="text-xs text-gray-500 mt-1">
                      {generationMethodLabel(p.generation_method)} · {p.slot_count} slots · fingerprint {p.plan_fingerprint.slice(0, 12)}…
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Link
                      href={`/campaign-planner/${campaignId}/calendar?plan=${p.id}`}
                      className="btn-secondary text-xs py-1"
                    >
                      Calendar
                    </Link>
                    {!isPlanReadOnly(p.status) && (
                      <>
                        <button className="btn-secondary text-xs py-1" onClick={() => reviewMut.mutate(p.id)}>
                          Review
                        </button>
                        <button className="btn-primary text-xs py-1" onClick={() => publishMut.mutate(p.id)}>
                          Publish
                        </button>
                      </>
                    )}
                    <button className="btn-secondary text-xs py-1" onClick={() => cloneMut.mutate(p.id)}>
                      Clone
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </PageSection>
      )}

      {tab === "review" && (
        <PageSection title="Campaign review">
          {!review ? (
            <EmptyState
              title="No review yet"
              description="Run a deterministic review on a draft or published plan."
              action={
                currentPlan ? (
                  <button className="btn-primary text-sm mt-2" onClick={() => reviewMut.mutate(currentPlan.id)}>
                    Review current plan
                  </button>
                ) : undefined
              }
            />
          ) : (
            <div className="space-y-4 text-sm">
              <div className="grid sm:grid-cols-4 gap-3">
                <MetricCard label="Coverage" value={String(review.coverage_score ?? "—")} />
                <MetricCard label="Readiness" value={String(review.readiness_score ?? "—")} />
                <MetricCard label="Conflicts" value={String(review.conflict_count ?? 0)} />
                <MetricCard label="Gaps" value={String(review.gap_count ?? 0)} />
              </div>
              <p className="text-xs text-gray-500">
                Scores are explainable and advisory. They do not approve the plan or override PublishSafety.
              </p>
              {Object.keys((review.summary?.gap_types as object) || {}).length > 0 && (
                <div>
                  <p className="font-medium mb-2">Gaps</p>
                  <ul className="space-y-1 text-gray-700">
                    {Object.entries(
                      (review.summary?.gap_types as Record<string, number>) || {},
                    ).map(([key, count]) => (
                      <li key={key}>
                        {titleCase(key)} · {count}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </PageSection>
      )}

      {tab === "ai" && (
        <PageSection title="AI-assisted campaign proposal">
          <p className="text-sm text-gray-600 mb-3">
            Optional governed proposal. Applying creates a <strong>new draft plan</strong> only —
            it does not publish, schedule, or approve content.
          </p>
          <button
            className="btn-primary text-sm mb-4"
            disabled={aiMut.isPending}
            onClick={() => aiMut.mutate()}
          >
            <Sparkles size={14} /> Request AI proposal
          </button>
          {aiRequests.length === 0 ? (
            <EmptyState title="No AI proposals" description="Deterministic planning remains available when AI is disabled." />
          ) : (
            <ul className="space-y-3">
              {aiRequests.map((req) => {
                const usage = (req.usage || {}) as Record<string, unknown>;
                const warnings = req.proposal?.warnings || [];
                return (
                <li key={req.request_id} className="card p-3 text-sm">
                  <div className="flex flex-wrap justify-between gap-2">
                    <div>
                      <p className="font-medium text-gray-900">
                        {titleCase(req.status || "unknown")} · {req.prompt_version || "1.0.0"}
                      </p>
                      <p className="text-xs text-gray-500 mt-1">
                        Model alias: {req.model_alias || "—"} ·
                        tokens {String(usage.total_tokens ?? "—")} ·
                        est. cost {String(usage.estimated_cost_minor ?? "—")}
                      </p>
                      {warnings.length ? (
                        <p className="text-xs text-amber-700 mt-1">
                          Warnings: {warnings.slice(0, 3).join("; ")}
                        </p>
                      ) : null}
                    </div>
                    <div className="flex gap-2">
                      {req.status === "completed" && req.apply_status !== "applied" && (
                        <>
                          <button
                            className="btn-primary text-xs py-1"
                            onClick={() => applyAiMut.mutate(req.request_id)}
                          >
                            Apply as draft
                          </button>
                          <button
                            className="btn-secondary text-xs py-1"
                            onClick={() => rejectAiMut.mutate(req.request_id)}
                          >
                            Reject
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                </li>
                );
              })}
            </ul>
          )}
        </PageSection>
      )}
    </PageShell>
  );
}

function MetricCard({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="card p-3">
      <p className="text-xs text-gray-500">{label}</p>
      <p className="text-2xl font-semibold text-gray-900 tabular-nums mt-1">{value}</p>
      {hint ? <p className="text-[11px] text-gray-400 mt-1">{hint}</p> : null}
    </div>
  );
}
