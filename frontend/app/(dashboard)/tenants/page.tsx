"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import { Building2, Check, Copy, Plus, UserPlus } from "lucide-react";
import { adminAuthApi, pilotOnboardingApi, normalizeList } from "@/lib/api";
import { AdminAuthGuard } from "@/components/auth/AdminAuthGuard";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";

const STATUS_STYLES: Record<string, string> = {
  active: "bg-emerald-100 text-emerald-800",
  pending: "bg-amber-100 text-amber-800",
  suspended: "bg-red-100 text-red-800",
  archived: "bg-gray-100 text-gray-700",
};

type PlatformTenant = {
  id: string;
  company_name: string;
  status: string;
  plan: string;
  created_at?: string;
};

type CreateClientForm = {
  company_name: string;
  owner_email: string;
  owner_name: string;
  phone: string;
  wechat: string;
  whatsapp: string;
  country: string;
  industry: string;
  plan: string;
  locale: string;
};

type CreatedClientResult = {
  tenant_id: string;
  user_id: string;
  company_name: string;
  login_email: string;
  temporary_password: string;
  login_url: string;
  message: string;
};

const EMPTY_FORM: CreateClientForm = {
  company_name: "",
  owner_email: "",
  owner_name: "",
  phone: "",
  wechat: "",
  whatsapp: "",
  country: "",
  industry: "",
  plan: "starter",
  locale: "en",
};

export default function TenantsPage() {
  return (
    <AdminAuthGuard requireAdmin>
      <TenantsPageContent />
    </AdminAuthGuard>
  );
}

function TenantsPageContent() {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [form, setForm] = useState<CreateClientForm>(EMPTY_FORM);
  const [created, setCreated] = useState<CreatedClientResult | null>(null);
  const [copied, setCopied] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const { data: listData, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["admin-platform-tenants"],
    queryFn: () => adminAuthApi.platformTenants({ limit: 200 }).then((r) => r.data),
  });

  const { data: pilotOnboardingApps } = useQuery({
    queryKey: ["pilot-onboarding-applications-tenants"],
    queryFn: () => pilotOnboardingApi.applications({ limit: 200 }).then((r) => r.data),
  });

  const createMutation = useMutation({
    mutationFn: () =>
      adminAuthApi
        .createClientAccount({
          company_name: form.company_name.trim(),
          owner_email: form.owner_email.trim(),
          owner_name: form.owner_name.trim() || undefined,
          phone: form.phone.trim() || undefined,
          wechat: form.wechat.trim() || undefined,
          whatsapp: form.whatsapp.trim() || undefined,
          country: form.country.trim() || undefined,
          industry: form.industry.trim() || undefined,
          plan: form.plan || "starter",
          locale: form.locale || "en",
        })
        .then((r) => r.data),
    onSuccess: (data) => {
      setCreated({
        tenant_id: data.tenant_id,
        user_id: data.user_id,
        company_name: data.company_name,
        login_email: data.login_email,
        temporary_password: data.temporary_password,
        login_url: data.login_url,
        message: data.message,
      });
      setShowCreateForm(false);
      setForm(EMPTY_FORM);
      setFormError(null);
      setSelectedId(data.tenant_id);
      queryClient.invalidateQueries({ queryKey: ["admin-platform-tenants"] });
    },
    onError: (err: unknown) => {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Failed to create client account";
      setFormError(typeof detail === "string" ? detail : "Failed to create client account");
    },
  });

  const items = normalizeList(listData?.items ?? listData) as PlatformTenant[];
  const selected = items.find((t) => t.id === selectedId);
  const tenantOnboarding = pilotOnboardingApps?.items.find((a) => a.tenant_id === selectedId);

  const loginDetailsText = created
    ? [
        "Client account created",
        `Company: ${created.company_name}`,
        `Login: ${created.login_email}`,
        `Temporary password: ${created.temporary_password}`,
        `Login URL: ${created.login_url}`,
      ].join("\n")
    : "";

  const copyLoginDetails = async () => {
    if (!loginDetailsText) return;
    await navigator.clipboard.writeText(loginDetailsText);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (isLoading) return <LoadingState message="Loading tenants…" />;
  if (isError) {
    return <ErrorState error={error} onRetry={() => refetch()} />;
  }

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
            <Building2 size={22} className="text-indigo-600" />
            Platform Tenants
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Manage factory tenants — create client accounts directly or via the factory partner workflow
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            setShowCreateForm((v) => !v);
            setFormError(null);
          }}
          className="btn-primary text-sm inline-flex items-center gap-2"
        >
          {showCreateForm ? <Plus size={16} className="rotate-45" /> : <UserPlus size={16} />}
          {showCreateForm ? "Cancel" : "Create Client"}
        </button>
      </div>

      {created && (
        <section className="card p-4 border-emerald-200 bg-emerald-50/50 space-y-3">
          <p className="text-sm font-semibold text-emerald-900">Client account created</p>
          <dl className="grid gap-2 text-sm">
            <div className="flex gap-2">
              <dt className="text-gray-500 w-36 shrink-0">Company</dt>
              <dd className="font-medium text-gray-900">{created.company_name}</dd>
            </div>
            <div className="flex gap-2">
              <dt className="text-gray-500 w-36 shrink-0">Login</dt>
              <dd className="font-mono text-gray-900">{created.login_email}</dd>
            </div>
            <div className="flex gap-2">
              <dt className="text-gray-500 w-36 shrink-0">Temporary password</dt>
              <dd className="font-mono text-gray-900">{created.temporary_password}</dd>
            </div>
            <div className="flex gap-2">
              <dt className="text-gray-500 w-36 shrink-0">Login URL</dt>
              <dd>
                <a href={created.login_url} className="text-brand-700 hover:underline font-mono text-sm">
                  {created.login_url}
                </a>
              </dd>
            </div>
          </dl>
          <p className="text-xs text-amber-700">
            Save these credentials now — the temporary password is only shown once.
          </p>
          <button
            type="button"
            onClick={copyLoginDetails}
            className="btn-secondary text-sm inline-flex items-center gap-2"
          >
            {copied ? <Check size={16} className="text-emerald-600" /> : <Copy size={16} />}
            {copied ? "Copied" : "Copy login details"}
          </button>
        </section>
      )}

      {showCreateForm && (
        <section className="card p-4 space-y-4">
          <p className="text-sm font-semibold text-gray-900">Create client account</p>
          <p className="text-xs text-gray-500">
            Provisions a tenant, owner login (auto-generated password), and a minimal demo workspace.
          </p>
          <div className="grid sm:grid-cols-2 gap-4">
            <label className="block space-y-1 sm:col-span-2">
              <span className="text-xs font-medium text-gray-700">
                Company name <span className="text-red-500">*</span>
              </span>
              <input
                type="text"
                value={form.company_name}
                onChange={(e) => setForm((f) => ({ ...f, company_name: e.target.value }))}
                className="input w-full"
                placeholder="Acme Manufacturing Ltd"
              />
            </label>
            <label className="block space-y-1">
              <span className="text-xs font-medium text-gray-700">
                Owner email <span className="text-red-500">*</span>
              </span>
              <input
                type="email"
                value={form.owner_email}
                onChange={(e) => setForm((f) => ({ ...f, owner_email: e.target.value }))}
                className="input w-full"
                placeholder="owner@company.com"
              />
            </label>
            <label className="block space-y-1">
              <span className="text-xs font-medium text-gray-700">Owner name</span>
              <input
                type="text"
                value={form.owner_name}
                onChange={(e) => setForm((f) => ({ ...f, owner_name: e.target.value }))}
                className="input w-full"
                placeholder="Jane Smith"
              />
            </label>
            <label className="block space-y-1">
              <span className="text-xs font-medium text-gray-700">Phone</span>
              <input
                type="text"
                value={form.phone}
                onChange={(e) => setForm((f) => ({ ...f, phone: e.target.value }))}
                className="input w-full"
              />
            </label>
            <label className="block space-y-1">
              <span className="text-xs font-medium text-gray-700">WeChat</span>
              <input
                type="text"
                value={form.wechat}
                onChange={(e) => setForm((f) => ({ ...f, wechat: e.target.value }))}
                className="input w-full"
              />
            </label>
            <label className="block space-y-1">
              <span className="text-xs font-medium text-gray-700">WhatsApp</span>
              <input
                type="text"
                value={form.whatsapp}
                onChange={(e) => setForm((f) => ({ ...f, whatsapp: e.target.value }))}
                className="input w-full"
              />
            </label>
            <label className="block space-y-1">
              <span className="text-xs font-medium text-gray-700">Country</span>
              <input
                type="text"
                value={form.country}
                onChange={(e) => setForm((f) => ({ ...f, country: e.target.value }))}
                className="input w-full"
              />
            </label>
            <label className="block space-y-1">
              <span className="text-xs font-medium text-gray-700">Industry</span>
              <input
                type="text"
                value={form.industry}
                onChange={(e) => setForm((f) => ({ ...f, industry: e.target.value }))}
                className="input w-full"
                placeholder="manufacturing"
              />
            </label>
            <label className="block space-y-1">
              <span className="text-xs font-medium text-gray-700">Plan</span>
              <select
                value={form.plan}
                onChange={(e) => setForm((f) => ({ ...f, plan: e.target.value }))}
                className="input w-full"
              >
                <option value="starter">starter</option>
                <option value="growth">growth</option>
                <option value="enterprise">enterprise</option>
                <option value="trial">trial</option>
              </select>
            </label>
            <label className="block space-y-1">
              <span className="text-xs font-medium text-gray-700">Locale</span>
              <select
                value={form.locale}
                onChange={(e) => setForm((f) => ({ ...f, locale: e.target.value }))}
                className="input w-full"
              >
                <option value="en">en</option>
                <option value="zh">zh</option>
                <option value="ru">ru</option>
              </select>
            </label>
          </div>
          {formError && <p className="text-sm text-red-600">{formError}</p>}
          <button
            type="button"
            disabled={createMutation.isPending || !form.company_name.trim() || !form.owner_email.trim()}
            onClick={() => createMutation.mutate()}
            className="btn-primary text-sm disabled:opacity-50"
          >
            {createMutation.isPending ? "Creating…" : "Create client account"}
          </button>
        </section>
      )}

      <div className="grid lg:grid-cols-2 gap-6">
        <section className="space-y-3">
          <p className="text-sm font-semibold text-gray-900">Tenant list</p>
          {items.length === 0 ? (
            <EmptyState
              title="No tenants yet"
              description="Create a client account above or approve a factory partner application."
            />
          ) : (
            <ul className="card divide-y divide-gray-100">
              {items.map((t) => (
                <li key={t.id}>
                  <button
                    type="button"
                    onClick={() => setSelectedId(t.id)}
                    className={cn(
                      "w-full text-left px-4 py-3 hover:bg-gray-50 transition",
                      selectedId === t.id && "bg-brand-50",
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium text-gray-900">{t.company_name}</span>
                      <span
                        className={cn(
                          "text-xs px-2 py-0.5 rounded-full",
                          STATUS_STYLES[t.status] ?? STATUS_STYLES.active,
                        )}
                      >
                        {t.status}
                      </span>
                    </div>
                    <p className="text-xs text-gray-500 mt-1">
                      {t.plan}
                      {t.created_at ? ` · ${format(parseISO(t.created_at), "dd MMM yyyy")}` : ""}
                    </p>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        <div className="space-y-6">
          {!selected ? (
            <EmptyState title="Select a tenant" description="Choose a tenant from the list to view details." />
          ) : (
            <section className="card p-4 space-y-3">
              <p className="text-sm font-semibold text-gray-900">Tenant detail</p>
              <h2 className="text-lg font-semibold">{selected.company_name}</h2>
              <p className="text-sm text-gray-600">
                Plan: {selected.plan} · Status: {selected.status}
              </p>
              <p className="text-xs text-gray-400 font-mono">ID: {selected.id}</p>
              {tenantOnboarding ? (
                <div className="pt-3 border-t border-violet-100">
                  <p className="text-xs font-semibold text-violet-800">Onboarding status</p>
                  <p className="text-sm text-gray-700 mt-1">
                    {tenantOnboarding.readiness_score}% ·{" "}
                    <span className="capitalize">{tenantOnboarding.status.replace("_", " ")}</span>
                  </p>
                  <Link href="/pilot-onboarding" className="text-xs text-brand-700 hover:underline">
                    View pilot onboarding →
                  </Link>
                </div>
              ) : (
                <p className="text-xs text-gray-400">No linked factory application onboarding track</p>
              )}
              <div className="flex flex-wrap gap-3 pt-2">
                <Link href="/billing?tab=licenses" className="text-xs text-brand-700 hover:underline">
                  View licenses →
                </Link>
                <Link href="/billing?tab=overview" className="text-xs text-brand-700 hover:underline">
                  Platform billing →
                </Link>
              </div>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
