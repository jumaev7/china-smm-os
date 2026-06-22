"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import {
  AlertCircle,
  CheckCircle2,
  CreditCard,
  Loader2,
  PauseCircle,
  Shield,
  TrendingUp,
  XCircle,
  Zap,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  SubscriptionInvoice,
  SubscriptionPlan,
  SubscriptionRecord,
  adminAuthApi,
  normalizeList,
  pilotOnboardingApi,
  subscriptionBillingApi,
} from "@/lib/api";
import { useAdminAuth } from "@/lib/admin-auth-store";
import { useAuth } from "@/lib/auth-store";
import { resolveNavAudience } from "@/lib/nav-access";
import { computeSessionAwareAuthReady } from "@/lib/session-sync";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import {
  ExecutiveKpiBar,
  PageHeader,
  PageShell,
  PageSection,
  SectionCard,
  StatTile,
  StatusBadge,
} from "@/components/ui/design-system";

type BillingTab = "overview" | "plans" | "licenses";

const STATUS_VARIANT: Record<string, "success" | "warning" | "danger" | "info" | "neutral"> = {
  trial: "info",
  active: "success",
  suspended: "warning",
  expired: "neutral",
  cancelled: "danger",
};

const INVOICE_VARIANT: Record<string, "success" | "warning" | "danger" | "neutral"> = {
  draft: "neutral",
  unpaid: "warning",
  paid: "success",
  cancelled: "danger",
};

/** Admin billing table — unchanged light styles */
const ADMIN_STATUS_STYLES: Record<string, string> = {
  trial: "bg-sky-100 text-sky-800 border-sky-200",
  active: "bg-emerald-100 text-emerald-800 border-emerald-200",
  suspended: "bg-amber-100 text-amber-800 border-amber-200",
  expired: "bg-gray-100 text-gray-700 border-gray-200",
  cancelled: "bg-red-100 text-red-800 border-red-200",
};

const TABS: { id: BillingTab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "plans", label: "Plans" },
  { id: "licenses", label: "Licenses" },
];

function fmtMoney(val: number | null | undefined): string {
  if (val == null) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(val);
}

function resolveTab(raw: string | null): BillingTab {
  if (raw === "plans" || raw === "licenses") return raw;
  return "overview";
}

function UsageBar({
  label,
  metric,
}: {
  label: string;
  metric: { current: number; limit: number | null; utilization_pct: number | null };
}) {
  const pct = metric.utilization_pct;
  const nearLimit = pct != null && pct >= 80;
  return (
    <div className="space-y-1.5">
      <div className="flex justify-between text-xs">
        <span className="text-gray-600 dark-tenant:text-slate-400">{label}</span>
        <span className="tabular-nums text-gray-800 dark-tenant:text-slate-200">
          {metric.current}
          {metric.limit != null ? ` / ${metric.limit}` : " / ∞"}
          {pct != null ? ` (${pct}%)` : ""}
        </span>
      </div>
      {pct != null ? (
        <div className="h-1.5 rounded-full bg-gray-200 dark-tenant:bg-white/[0.06] overflow-hidden">
          <div
            className={cn(
              "h-full rounded-full transition-all",
              nearLimit
                ? "bg-orange-500 dark-tenant:bg-orange-400"
                : "bg-brand-600 dark-tenant:bg-violet-500",
            )}
            style={{ width: `${Math.min(100, pct)}%` }}
          />
        </div>
      ) : (
        <div className="h-1.5 rounded-full bg-gray-100 dark-tenant:bg-white/[0.04]" />
      )}
    </div>
  );
}

function PlanCard({
  plan,
  currentCode,
  onSelect,
  selecting,
  readOnly,
}: {
  plan: SubscriptionPlan;
  currentCode?: string | null;
  onSelect?: (code: string) => void;
  selecting?: boolean;
  readOnly?: boolean;
}) {
  const isCurrent = currentCode === plan.code;
  return (
    <div
      className={cn(
        "card-premium p-5 flex flex-col border-2 transition-all duration-200",
        isCurrent
          ? "border-brand-500 bg-brand-50/30 dark-tenant:border-violet-500/40 dark-tenant:bg-violet-500/10 dark-tenant:shadow-glow"
          : "border-transparent hover:border-gray-200 dark-tenant:hover:border-white/[0.08]",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3 className="font-semibold text-gray-900 dark-tenant:text-slate-100">{plan.name}</h3>
          <p className="text-xs text-gray-500 dark-tenant:text-slate-500 uppercase tracking-wide mt-0.5">
            {plan.code}
          </p>
        </div>
        {isCurrent && (
          <StatusBadge variant="info" className="text-[10px]">
            Current
          </StatusBadge>
        )}
      </div>
      <p className="text-2xl font-semibold text-gray-900 dark-tenant:text-slate-100 mt-3 tabular-nums">
        {fmtMoney(plan.monthly_price)}
        <span className="text-sm font-normal text-gray-500 dark-tenant:text-slate-500">/mo</span>
      </p>
      <p className="text-xs text-gray-500 dark-tenant:text-slate-500 mt-1">
        {fmtMoney(plan.yearly_price)}/yr billed annually
      </p>
      <ul className="mt-4 space-y-1.5 text-xs text-gray-600 dark-tenant:text-slate-400 flex-1">
        <li>Users: {plan.max_users ?? "Unlimited"}</li>
        <li>Leads: {plan.max_leads ?? "Unlimited"}</li>
        <li>Buyers: {plan.max_buyers ?? "Unlimited"}</li>
        <li>Deals: {plan.max_deals ?? "Unlimited"}</li>
      </ul>
      {!readOnly && !isCurrent && onSelect && (
        <button
          type="button"
          className="btn-primary text-sm mt-4 w-full flex items-center justify-center gap-1"
          disabled={selecting}
          onClick={() => onSelect(plan.code)}
        >
          {selecting ? <Loader2 size={14} className="animate-spin" /> : <Zap size={14} />}
          Upgrade
        </button>
      )}
    </div>
  );
}

function BillingTabs({ tab, isAdmin }: { tab: BillingTab; isAdmin: boolean }) {
  const router = useRouter();
  return (
    <div
      className={cn(
        "inline-flex flex-wrap gap-1 rounded-xl border border-gray-200/90 bg-white p-1",
        "dark-tenant:border-white/[0.08] dark-tenant:bg-surface-dark-elevated/60",
      )}
      role="tablist"
    >
      {TABS.map(({ id, label }) => {
        const href = id === "overview" ? "/billing" : `/billing?tab=${id}`;
        const active = tab === id;
        return (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => router.push(href)}
            className={cn(
              "px-3 py-1.5 text-sm font-medium rounded-lg transition-all duration-150",
              active
                ? "bg-brand-600 text-white shadow-sm dark-tenant:bg-violet-600 dark-tenant:shadow-glow"
                : "text-gray-600 hover:bg-gray-50 hover:text-gray-900 dark-tenant:text-slate-400 dark-tenant:hover:bg-white/[0.04] dark-tenant:hover:text-slate-200",
            )}
          >
            {label}
            {isAdmin && id === "plans" ? " (platform)" : null}
          </button>
        );
      })}
    </div>
  );
}

export default function BillingPage() {
  return (
    <Suspense fallback={<LoadingState message="Loading subscription billing…" />}>
      <BillingPageContent />
    </Suspense>
  );
}

function BillingPageContent() {
  const searchParams = useSearchParams();
  const tab = resolveTab(searchParams.get("tab"));
  const { user: tenantUser, isAuthenticated: isTenant, loading: tenantLoading } = useAuth();
  const { isAuthenticated: isAdmin, loading: adminLoading } = useAdminAuth();
  const authReady = computeSessionAwareAuthReady(tenantLoading, adminLoading);
  const audience = authReady
    ? resolveNavAudience({ authReady, isTenantAuthenticated: isTenant, isAdminAuthenticated: isAdmin })
    : "loading";
  const isAdminMode = audience === "admin";

  if (!authReady) {
    return <LoadingState message="Loading subscription billing…" />;
  }

  if (isAdminMode) {
    return <AdminBillingPage tab={tab} />;
  }

  return <TenantBillingPage tab={tab} tenantId={tenantUser?.tenant_id ?? ""} />;
}

function AdminBillingPage({ tab }: { tab: BillingTab }) {
  const { data: platformBilling, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["admin-platform-billing-page"],
    queryFn: () => adminAuthApi.platformBilling().then((r) => r.data),
  });

  const { data: subscriptions } = useQuery({
    queryKey: ["admin-platform-subscriptions"],
    queryFn: () => adminAuthApi.platformSubscriptions({ limit: 200 }).then((r) => r.data),
    enabled: tab === "licenses" || tab === "overview",
  });

  const { data: tenantsData } = useQuery({
    queryKey: ["admin-platform-tenants-billing"],
    queryFn: () => adminAuthApi.platformTenants({ limit: 200 }).then((r) => r.data),
    enabled: tab === "licenses",
  });

  const planItems = useMemo(
    () => normalizeList(platformBilling?.plans ?? []) as SubscriptionPlan[],
    [platformBilling],
  );
  const subItems = useMemo(
    () => normalizeList(subscriptions?.items ?? subscriptions) as SubscriptionRecord[],
    [subscriptions],
  );
  const tenantNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const t of tenantsData?.items ?? []) {
      map.set(t.id, t.company_name);
    }
    return map;
  }, [tenantsData]);

  if (isLoading) return <LoadingState message="Loading platform billing…" />;
  if (isError) {
    return (
      <ErrorState
        error={error}
        onRetry={() => refetch()}
      />
    );
  }

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
          <CreditCard size={20} className="text-amber-600" />
          Platform Billing
        </h1>
        <p className="text-sm text-gray-500 mt-1">
          Subscription plans and tenant licenses — architecture only, no payment processing.
        </p>
      </div>

      <BillingTabs tab={tab} isAdmin />

      <div className="card p-3 border-amber-100 bg-amber-50/50 text-xs text-amber-900 flex items-start gap-2">
        <AlertCircle size={14} className="shrink-0 mt-0.5" />
        <span>
          Platform admin view. Manage global plans and review tenant subscriptions. No real payment providers.
        </span>
      </div>

      {tab === "overview" && platformBilling && (
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="card p-4">
            <p className="text-[10px] uppercase text-gray-400">Total tenants</p>
            <p className="text-2xl font-semibold tabular-nums">{platformBilling.total_tenants}</p>
          </div>
          <div className="card p-4">
            <p className="text-[10px] uppercase text-gray-400">Active subscriptions</p>
            <p className="text-2xl font-semibold tabular-nums">{platformBilling.active_subscriptions}</p>
          </div>
          <div className="card p-4">
            <p className="text-[10px] uppercase text-gray-400">Trial subscriptions</p>
            <p className="text-2xl font-semibold tabular-nums">{platformBilling.trial_subscriptions}</p>
          </div>
          <div className="card p-4">
            <p className="text-[10px] uppercase text-gray-400">Available plans</p>
            <p className="text-2xl font-semibold tabular-nums">{planItems.length}</p>
          </div>
        </div>
      )}

      {tab === "plans" && (
        <section className="space-y-3">
          <h2 className="text-sm font-semibold text-gray-900">Subscription Plans</h2>
          {planItems.length === 0 ? (
            <EmptyState
              title="No plans configured"
              description="Seed subscription plans in the database to manage platform pricing tiers."
            />
          ) : (
            <div className="grid sm:grid-cols-3 gap-4">
              {planItems.map((plan) => (
                <PlanCard key={plan.id} plan={plan} readOnly />
              ))}
            </div>
          )}
        </section>
      )}

      {tab === "licenses" && (
        <section className="card overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-100">
            <h2 className="text-sm font-semibold text-gray-800 flex items-center gap-2">
              <Shield size={16} className="text-brand-600" />
              Tenant Licenses
            </h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50 text-xs text-gray-500">
                  <th className="text-left px-4 py-2.5">Tenant</th>
                  <th className="text-left px-4 py-2.5">Plan</th>
                  <th className="text-left px-4 py-2.5">Status</th>
                  <th className="text-left px-4 py-2.5">Started</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {subItems.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="px-4 py-8 text-center text-gray-400 text-sm">
                      No tenant subscriptions yet.
                    </td>
                  </tr>
                ) : (
                  subItems.map((s) => (
                    <tr key={s.id} className="hover:bg-gray-50">
                      <td className="px-4 py-3 text-xs">
                        {tenantNameById.get(s.tenant_id) ?? s.tenant_id.slice(0, 8)}
                      </td>
                      <td className="px-4 py-3 text-xs">{s.plan_name ?? s.plan_code}</td>
                      <td className="px-4 py-3">
                        <span className={cn("text-[10px] px-2 py-0.5 rounded-full border font-medium", ADMIN_STATUS_STYLES[s.status])}>
                          {s.status}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-xs">
                        {format(parseISO(s.starts_at), "dd MMM yyyy")}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}

function TenantBillingPage({ tab, tenantId }: { tab: BillingTab; tenantId: string }) {
  const qc = useQueryClient();

  const { data: plans, isLoading: plansLoading } = useQuery({
    queryKey: ["billing-plans"],
    queryFn: () => subscriptionBillingApi.plans().then((r) => r.data),
    enabled: tab === "plans" || tab === "overview",
  });

  const { data: summary, isLoading: summaryLoading, isError: summaryError, error: summaryErr, refetch: refetchSummary } = useQuery({
    queryKey: ["billing-summary", tenantId],
    queryFn: () => subscriptionBillingApi.summary(tenantId).then((r) => r.data),
    enabled: !!tenantId && tab === "overview",
  });

  const { data: subscriptions } = useQuery({
    queryKey: ["billing-subscriptions", tenantId],
    queryFn: () => subscriptionBillingApi.subscriptions({ tenant_id: tenantId, limit: 20 }).then((r) => r.data),
    enabled: !!tenantId && (tab === "licenses" || tab === "overview"),
  });

  const { data: invoices } = useQuery({
    queryKey: ["billing-invoices", tenantId],
    queryFn: () => subscriptionBillingApi.invoices({ tenant_id: tenantId, limit: 20 }).then((r) => r.data),
    enabled: !!tenantId && tab === "overview",
  });

  const { data: pilotOnboardingApps } = useQuery({
    queryKey: ["pilot-onboarding-billing"],
    queryFn: () => pilotOnboardingApi.applications({ limit: 200 }).then((r) => r.data),
    enabled: tab === "overview" && !!tenantId,
  });

  const pilotBilling = useMemo(() => {
    const match = pilotOnboardingApps?.items.find((a) => a.tenant_id === tenantId);
    if (!match) return null;
    const billingReady = match.blockers.every((b) => b.blocker !== "billing" && b.blocker !== "subscription");
    return { ...match, billing_ready: billingReady };
  }, [pilotOnboardingApps, tenantId]);

  const activeSub = useMemo(() => {
    const items = normalizeList(subscriptions?.items ?? subscriptions) as SubscriptionRecord[];
    return items.find((s) => ["trial", "active", "suspended"].includes(s.status)) ?? items[0];
  }, [subscriptions]);

  const upgradeMutation = useMutation({
    mutationFn: (planCode: string) =>
      subscriptionBillingApi
        .createSubscription({ tenant_id: tenantId, plan_code: planCode, status: "trial" })
        .then((r) => r.data),
    onSuccess: () => {
      toast.success("Subscription created (architecture only — no payment charged)");
      qc.invalidateQueries({ queryKey: ["billing-summary", tenantId] });
      qc.invalidateQueries({ queryKey: ["billing-subscriptions", tenantId] });
      qc.invalidateQueries({ queryKey: ["billing-invoices", tenantId] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const activateMutation = useMutation({
    mutationFn: (id: string) => subscriptionBillingApi.activate(id).then((r) => r.data),
    onSuccess: () => {
      toast.success("Subscription activated");
      qc.invalidateQueries({ queryKey: ["billing-summary", tenantId] });
      qc.invalidateQueries({ queryKey: ["billing-subscriptions", tenantId] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const suspendMutation = useMutation({
    mutationFn: (id: string) => subscriptionBillingApi.suspend(id).then((r) => r.data),
    onSuccess: () => {
      toast.success("Subscription suspended");
      qc.invalidateQueries({ queryKey: ["billing-summary", tenantId] });
      qc.invalidateQueries({ queryKey: ["billing-subscriptions", tenantId] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const cancelMutation = useMutation({
    mutationFn: (id: string) => subscriptionBillingApi.cancel(id).then((r) => r.data),
    onSuccess: () => {
      toast.success("Subscription cancelled");
      qc.invalidateQueries({ queryKey: ["billing-summary", tenantId] });
      qc.invalidateQueries({ queryKey: ["billing-subscriptions", tenantId] });
      qc.invalidateQueries({ queryKey: ["billing-invoices", tenantId] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  if (!tenantId) {
    return (
      <PageShell>
        <ErrorState error={new Error("Tenant session required")} />
      </PageShell>
    );
  }

  if ((tab === "overview" && summaryLoading) || (tab === "plans" && plansLoading)) {
    return <LoadingState message="Loading subscription billing…" />;
  }

  const planItems = normalizeList(plans?.items ?? plans) as SubscriptionPlan[];
  const invoiceItems = normalizeList(invoices?.items ?? invoices) as SubscriptionInvoice[];
  const subItems = normalizeList(subscriptions?.items ?? subscriptions) as SubscriptionRecord[];
  const usage = summary?.usage_summary;

  return (
    <PageShell>
      <PageHeader
        title="Subscription & Billing"
        subtitle="Plan management, usage limits, and invoice records — architecture only, no payment processing."
        icon={CreditCard}
        iconClassName="text-amber-400"
      />

      <BillingTabs tab={tab} isAdmin={false} />

      <div className="rounded-xl border border-amber-200/80 bg-amber-50/40 px-4 py-3 text-xs text-amber-900 dark-tenant:border-amber-500/20 dark-tenant:bg-amber-500/10 dark-tenant:text-amber-200 flex items-start gap-2">
        <AlertCircle size={14} className="shrink-0 mt-0.5 text-amber-600 dark-tenant:text-amber-400" />
        <span>
          No real payment providers, card storage, or automatic charges. Invoices are draft records only.
          {" "}
          <Link href="/billing/legacy" className="underline hover:text-amber-950 dark-tenant:hover:text-amber-100">
            Legacy client post billing
          </Link>
        </span>
      </div>

      {tab === "overview" && pilotBilling && (
        <div
          className={cn(
            "card-premium p-3 text-xs flex items-center justify-between gap-2 border",
            pilotBilling.billing_ready
              ? "border-emerald-200/80 bg-emerald-50/40 text-emerald-900 dark-tenant:border-emerald-500/20 dark-tenant:bg-emerald-500/10 dark-tenant:text-emerald-200"
              : "border-amber-200/80 bg-amber-50/40 text-amber-900 dark-tenant:border-amber-500/20 dark-tenant:bg-amber-500/10 dark-tenant:text-amber-200",
          )}
        >
          <div className="flex items-center gap-2">
            {pilotBilling.billing_ready ? (
              <CheckCircle2 size={14} className="text-emerald-600" />
            ) : (
              <AlertCircle size={14} className="text-amber-600" />
            )}
            <span>
              Pilot billing readiness:{" "}
              {pilotBilling.billing_ready ? "Ready" : "Needs subscription setup"} · Pilot onboarding{" "}
              {pilotBilling.readiness_score}%
            </span>
          </div>
          <Link href="/pilot-onboarding" className="text-brand-700 hover:underline dark-tenant:text-violet-400 whitespace-nowrap">
            Open onboarding →
          </Link>
        </div>
      )}

      {tab === "plans" && (
        <PageSection title="Available plans" description="Choose a subscription tier for your factory workspace">
          {planItems.length === 0 ? (
            <EmptyState title="No plans available" description="Contact your platform administrator." />
          ) : (
            <div className="grid sm:grid-cols-3 gap-4">
              {planItems.map((plan) => (
                <PlanCard
                  key={plan.id}
                  plan={plan}
                  currentCode={summary?.plan?.code}
                  onSelect={(code) => upgradeMutation.mutate(code)}
                  selecting={upgradeMutation.isPending}
                />
              ))}
            </div>
          )}
        </PageSection>
      )}

      {tab === "licenses" && (
        <SectionCard title="Your subscription" icon={Shield} iconClassName="text-violet-400">
          {activeSub ? (
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div>
                <p className="text-sm font-medium text-gray-900 dark-tenant:text-slate-100">
                  {activeSub.plan_name ?? activeSub.plan_code} — {activeSub.billing_cycle}
                </p>
                <p className="text-xs text-gray-500 dark-tenant:text-slate-500">
                  Started {format(parseISO(activeSub.starts_at), "dd MMM yyyy")}
                  {activeSub.expires_at && ` · Expires ${format(parseISO(activeSub.expires_at), "dd MMM yyyy")}`}
                </p>
                <StatusBadge variant={STATUS_VARIANT[activeSub.status] ?? "neutral"} className="mt-1 text-[10px]">
                  {activeSub.status}
                </StatusBadge>
              </div>
              <div className="flex flex-wrap gap-2">
                {activeSub.status !== "active" && activeSub.status !== "cancelled" && (
                  <button
                    type="button"
                    className="btn-secondary text-xs flex items-center gap-1"
                    disabled={activateMutation.isPending}
                    onClick={() => activateMutation.mutate(activeSub.id)}
                  >
                    <CheckCircle2 size={12} /> Activate
                  </button>
                )}
                {activeSub.status === "active" && (
                  <button
                    type="button"
                    className="btn-secondary text-xs flex items-center gap-1"
                    disabled={suspendMutation.isPending}
                    onClick={() => suspendMutation.mutate(activeSub.id)}
                  >
                    <PauseCircle size={12} /> Suspend
                  </button>
                )}
                {activeSub.status !== "cancelled" && (
                  <button
                    type="button"
                    className="btn-secondary text-xs flex items-center gap-1 text-red-700 border-red-200"
                    disabled={cancelMutation.isPending}
                    onClick={() => cancelMutation.mutate(activeSub.id)}
                  >
                    <XCircle size={12} /> Cancel
                  </button>
                )}
              </div>
            </div>
          ) : (
            <EmptyState
              title="No active subscription"
              description="Choose a plan on the Plans tab to start a trial subscription."
            />
          )}
        </SectionCard>
      )}

      {tab === "overview" && (
        summaryError ? (
          <ErrorState error={summaryErr} onRetry={() => refetchSummary()} />
        ) : summary ? (
          <>
            {summary.status && (
              <ExecutiveKpiBar
                items={[
                  { label: "Plan", value: summary.plan?.name ?? "Free" },
                  { label: "Monthly", value: fmtMoney(summary.monthly_price) },
                  { label: "Status", value: summary.status },
                  {
                    label: "Renewal",
                    value: summary.next_renewal
                      ? format(parseISO(summary.next_renewal), "dd MMM yyyy")
                      : "—",
                  },
                ]}
              />
            )}

            <SectionCard title="Current plan" icon={CreditCard} iconClassName="text-amber-400">
              <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
                <StatTile label="Plan" value={summary.plan?.name ?? "Free"} tone="brand" />
                <StatTile label="Monthly price" value={fmtMoney(summary.monthly_price)} tone="neutral" />
                <div>
                  <p className="text-[10px] uppercase tracking-wide text-gray-400 dark-tenant:text-slate-500 mb-1">
                    Status
                  </p>
                  {summary.status ? (
                    <StatusBadge variant={STATUS_VARIANT[summary.status] ?? "neutral"}>
                      {summary.status}
                    </StatusBadge>
                  ) : (
                    <p className="text-sm text-gray-500 dark-tenant:text-slate-500">No active subscription</p>
                  )}
                </div>
                <StatTile
                  label="Next renewal"
                  value={
                    summary.next_renewal
                      ? format(parseISO(summary.next_renewal), "dd MMM yyyy")
                      : "—"
                  }
                  tone="info"
                />
              </div>
            </SectionCard>

            {usage && (
              <SectionCard title="Usage summary" icon={TrendingUp} iconClassName="text-emerald-400">
                <div className="grid sm:grid-cols-2 gap-4">
                  <UsageBar label="Users" metric={usage.users} />
                  <UsageBar label="Leads" metric={usage.leads} />
                  <UsageBar label="Buyers" metric={usage.buyers} />
                  <UsageBar label="Deals" metric={usage.deals} />
                </div>
              </SectionCard>
            )}

            <PageSection title="Plan comparison" description="Upgrade or switch subscription tiers">
              <div className="grid sm:grid-cols-3 gap-4">
                {planItems.map((plan) => (
                  <PlanCard
                    key={plan.id}
                    plan={plan}
                    currentCode={summary.plan?.code}
                    onSelect={(code) => upgradeMutation.mutate(code)}
                    selecting={upgradeMutation.isPending}
                  />
                ))}
              </div>
            </PageSection>

            <SectionCard title="Invoice history" icon={CreditCard} iconClassName="text-sky-400">
              <div className="overflow-x-auto -mx-1">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-100 dark-tenant:border-white/[0.06] bg-gray-50/80 dark-tenant:bg-surface-dark-elevated/80 text-xs text-gray-500 dark-tenant:text-slate-400">
                      <th className="text-left px-4 py-2.5">Date</th>
                      <th className="text-left px-4 py-2.5">Due</th>
                      <th className="text-right px-4 py-2.5">Amount</th>
                      <th className="text-left px-4 py-2.5">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50 dark-tenant:divide-white/[0.04]">
                    {invoiceItems.length === 0 ? (
                      <tr>
                        <td colSpan={4} className="px-4 py-8 text-center text-gray-400 dark-tenant:text-slate-500 text-sm">
                          No invoices yet.
                        </td>
                      </tr>
                    ) : (
                      invoiceItems.map((inv) => (
                        <tr key={inv.id} className="hover:bg-gray-50/60 dark-tenant:hover:bg-white/[0.02]">
                          <td className="px-4 py-3 text-xs text-gray-800 dark-tenant:text-slate-300">
                            {format(parseISO(inv.invoice_date), "dd MMM yyyy")}
                          </td>
                          <td className="px-4 py-3 text-xs text-gray-800 dark-tenant:text-slate-300">
                            {format(parseISO(inv.due_date), "dd MMM yyyy")}
                          </td>
                          <td className="px-4 py-3 text-xs text-right tabular-nums text-gray-900 dark-tenant:text-slate-100">
                            {fmtMoney(inv.amount)} {inv.currency}
                          </td>
                          <td className="px-4 py-3">
                            <StatusBadge variant={INVOICE_VARIANT[inv.status] ?? "neutral"} className="text-[10px]">
                              {inv.status}
                            </StatusBadge>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </SectionCard>

            <SectionCard title="Upgrade plan" icon={TrendingUp} iconClassName="text-violet-400">
              <p className="text-sm text-gray-600 dark-tenant:text-slate-400 -mt-2">
                Select a plan in the comparison above or open the Plans tab. Upgrades create a trial subscription and draft invoice.
              </p>
            </SectionCard>
          </>
        ) : null
      )}
    </PageShell>
  );
}
