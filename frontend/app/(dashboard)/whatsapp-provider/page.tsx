"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import {
  CheckCircle2,
  Loader2,
  MessageCircle,
  Plug,
  RefreshCw,
  Server,
  Shield,
  Webhook,
  XCircle,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  whatsappProviderApi,
  WhatsAppProvider,
  WhatsAppProviderConfiguration,
  WhatsAppProviderHealthItem,
  WhatsAppProviderType,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";

const PROVIDER_TYPE_LABELS: Record<WhatsAppProviderType, string> = {
  meta_cloud_api: "Meta Cloud API",
  whatsapp_business_api: "WhatsApp Business API",
  third_party_connector: "Third-Party Connector",
  custom_provider: "Custom Provider",
};

const CAPABILITY_LABELS: Record<string, string> = {
  contact_sync: "Contact Sync",
  conversation_sync: "Conversation Sync",
  message_send: "Message Send",
  media_upload: "Media Upload",
  webhook_support: "Webhook Support",
  template_messages: "Template Messages",
};

function formatDt(iso?: string | null): string {
  if (!iso) return "—";
  try {
    return format(parseISO(iso), "yyyy-MM-dd HH:mm");
  } catch {
    return iso;
  }
}

function StatusBadge({ status }: { status: string }) {
  const style =
    status === "active" || status === "ok" || status === "validated"
      ? "bg-emerald-50 text-emerald-800"
      : status === "error" || status === "unavailable"
        ? "bg-red-50 text-red-800"
        : status === "degraded"
          ? "bg-amber-50 text-amber-800"
          : "bg-gray-100 text-gray-600";
  return (
    <span className={cn("text-[10px] font-medium px-2 py-0.5 rounded-full uppercase", style)}>
      {status}
    </span>
  );
}

export default function WhatsAppProviderPage() {
  const qc = useQueryClient();
  const [selectedProviderId, setSelectedProviderId] = useState<string | null>(null);
  const [registerName, setRegisterName] = useState("");
  const [registerType, setRegisterType] = useState<WhatsAppProviderType>("meta_cloud_api");

  const {
    data: providersData,
    isLoading: providersLoading,
    isError: providersError,
    refetch: refetchProviders,
  } = useQuery({
    queryKey: ["whatsapp-provider-providers"],
    queryFn: () => whatsappProviderApi.listProviders().then((r) => r.data),
  });

  const { data: configurationsData, refetch: refetchConfigurations } = useQuery({
    queryKey: ["whatsapp-provider-configurations"],
    queryFn: () => whatsappProviderApi.listConfigurations().then((r) => r.data),
    enabled: !!providersData,
  });

  const { data: health, refetch: refetchHealth } = useQuery({
    queryKey: ["whatsapp-provider-health"],
    queryFn: () => whatsappProviderApi.health().then((r) => r.data),
    enabled: !!providersData,
  });

  const providers = providersData?.items ?? [];
  const configurations = configurationsData?.items ?? [];
  const activeProviderId = selectedProviderId ?? providers[0]?.id ?? null;

  const testConnectionMut = useMutation({
    mutationFn: (providerId: string) => whatsappProviderApi.testConnection(providerId),
    onSuccess: (res) => {
      if (res.data.ok) toast.success(res.data.message);
      else toast.error(res.data.message);
      qc.invalidateQueries({ queryKey: ["whatsapp-provider-health"] });
      qc.invalidateQueries({ queryKey: ["whatsapp-provider-configurations"] });
    },
    onError: (e: Error) => toast.error(e.message || "Connection test failed"),
  });

  const registerMut = useMutation({
    mutationFn: () =>
      whatsappProviderApi.registerProvider({
        provider_name: registerName.trim(),
        provider_type: registerType,
        config_json: { demo: true },
      }),
    onSuccess: (res) => {
      toast.success(res.data.message || "Provider registered");
      setRegisterName("");
      qc.invalidateQueries({ queryKey: ["whatsapp-provider-providers"] });
      qc.invalidateQueries({ queryKey: ["whatsapp-provider-configurations"] });
      qc.invalidateQueries({ queryKey: ["whatsapp-provider-health"] });
    },
    onError: (e: Error) => toast.error(e.message || "Registration failed"),
  });

  const busy = testConnectionMut.isPending || registerMut.isPending;

  const capabilityMatrix = useMemo(() => {
    return providers.map((p: WhatsAppProvider) => ({
      id: p.id,
      name: p.provider_name,
      type: p.provider_type,
      capabilities: p.capabilities,
    }));
  }, [providers]);

  if (providersLoading) return <LoadingState title="Loading WhatsApp Provider…" />;
  if (providersError) {
    return (
      <ErrorState
        title="Failed to load WhatsApp Provider"
        onRetry={() => refetchProviders()}
      />
    );
  }

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
            <Server size={22} className="text-green-600" />
            WhatsApp Provider
          </h1>
          <p className="text-sm text-gray-500 mt-1 max-w-xl">
            Production-grade provider architecture for Meta Cloud API, WhatsApp Business API, and
            third-party connectors. Configuration and health checks only — no message sending or
            live API calls in v1.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="btn-secondary text-sm flex items-center gap-1.5"
            disabled={busy}
            onClick={() => {
              refetchProviders();
              refetchConfigurations();
              refetchHealth();
            }}
          >
            <RefreshCw size={14} className={busy ? "animate-spin" : ""} />
            Refresh
          </button>
          <Link href="/whatsapp-sync" className="btn-secondary text-sm">
            WhatsApp Sync
          </Link>
          <Link href="/whatsapp" className="btn-secondary text-sm">
            WhatsApp Center
          </Link>
          <Link href="/unified-inbox" className="btn-secondary text-sm">
            Unified Inbox
          </Link>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="card p-4">
          <p className="text-[10px] uppercase text-gray-400 font-medium">Providers</p>
          <p className="text-2xl font-semibold tabular-nums mt-1">
            {health?.providers_active ?? 0}
            <span className="text-sm text-gray-400 font-normal">
              /{health?.providers_total ?? providers.length}
            </span>
          </p>
        </div>
        <div className="card p-4">
          <p className="text-[10px] uppercase text-gray-400 font-medium">Configurations</p>
          <p className="text-2xl font-semibold tabular-nums mt-1">
            {health?.configurations_validated ?? 0}
            <span className="text-sm text-gray-400 font-normal">
              /{health?.configurations_total ?? configurations.length}
            </span>
          </p>
        </div>
        <div className="card p-4">
          <p className="text-[10px] uppercase text-gray-400 font-medium">Connection Health</p>
          <p className="text-sm font-medium text-gray-900 mt-2 flex items-center gap-1.5">
            {health?.overall_status === "ok" ? (
              <CheckCircle2 size={14} className="text-emerald-600" />
            ) : (
              <XCircle size={14} className="text-amber-600" />
            )}
            {health?.overall_status ?? "—"}
          </p>
          <p className="text-[10px] text-gray-400 mt-1">
            Last test: {formatDt(health?.last_connection_test)}
          </p>
        </div>
        <div className="card p-4">
          <p className="text-[10px] uppercase text-gray-400 font-medium">Safety</p>
          <p className="text-xs text-gray-600 mt-2 leading-relaxed flex items-start gap-1.5">
            <Shield size={12} className="text-emerald-600 shrink-0 mt-0.5" />
            No send · No credentials · No external calls
          </p>
        </div>
      </div>

      <div className="card p-4 space-y-4">
        <p className="text-sm font-semibold text-gray-900">Register Provider</p>
        <div className="flex flex-wrap gap-2 items-end">
          <label className="text-xs text-gray-500 flex flex-col gap-1">
            Provider name
            <input
              className="input text-sm min-w-[200px]"
              value={registerName}
              onChange={(e) => setRegisterName(e.target.value)}
              placeholder="My Meta Cloud Provider"
            />
          </label>
          <label className="text-xs text-gray-500 flex flex-col gap-1">
            Type
            <select
              className="input text-sm min-w-[180px]"
              value={registerType}
              onChange={(e) => setRegisterType(e.target.value as WhatsAppProviderType)}
            >
              {Object.entries(PROVIDER_TYPE_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="btn-primary text-sm"
            disabled={busy || !registerName.trim()}
            onClick={() => registerMut.mutate()}
          >
            {registerMut.isPending ? "Registering…" : "Register Provider"}
          </button>
        </div>
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        <div className="card p-4 space-y-3">
          <p className="text-sm font-semibold text-gray-900 flex items-center gap-2">
            <Server size={16} />
            Provider Registry
          </p>
          {providers.length === 0 ? (
            <EmptyState title="No providers" description="Demo providers seed on first load." />
          ) : (
            <ul className="space-y-2">
              {providers.map((p: WhatsAppProvider) => (
                <li
                  key={p.id}
                  className={cn(
                    "border rounded-lg p-3 text-sm",
                    p.id === activeProviderId ? "border-brand-200 bg-brand-50/30" : "border-gray-100",
                  )}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-gray-900">{p.provider_name}</span>
                    <StatusBadge status={p.status} />
                  </div>
                  <p className="text-xs text-gray-500 mt-1">
                    {PROVIDER_TYPE_LABELS[p.provider_type] ?? p.provider_type}
                  </p>
                  <p className="text-[10px] text-gray-400 mt-1">
                    Created: {formatDt(p.created_at)}
                  </p>
                  <button
                    type="button"
                    className="btn-secondary text-xs mt-2 flex items-center gap-1"
                    disabled={busy}
                    onClick={() => {
                      setSelectedProviderId(p.id);
                      testConnectionMut.mutate(p.id);
                    }}
                  >
                    {testConnectionMut.isPending && activeProviderId === p.id ? (
                      <Loader2 size={12} className="animate-spin" />
                    ) : (
                      <Plug size={12} />
                    )}
                    Test Connection
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="card p-4 space-y-3">
          <p className="text-sm font-semibold text-gray-900">Configurations</p>
          {configurations.length === 0 ? (
            <EmptyState title="No configurations" description="Register a provider to create one." />
          ) : (
            <ul className="space-y-2 max-h-[360px] overflow-y-auto">
              {configurations.map((c: WhatsAppProviderConfiguration) => (
                <li key={c.id} className="border border-gray-100 rounded-lg p-3 text-xs">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-gray-800">{c.provider_name ?? "—"}</span>
                    <StatusBadge status={c.config_status} />
                  </div>
                  <p className="text-gray-500 mt-1">
                    Phone: {c.phone_number ?? "—"} · WABA: {c.business_account_id ?? "—"}
                  </p>
                  <p className="text-gray-500">
                    Tenant: {c.tenant_id ?? "global demo"} · Provider status: {c.provider_status}
                  </p>
                  <p className="text-[10px] text-gray-400 mt-1">
                    Last test: {formatDt(c.last_connection_test)} · Updated: {formatDt(c.updated_at)}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div className="card p-4 space-y-3">
        <p className="text-sm font-semibold text-gray-900">Capabilities</p>
        {capabilityMatrix.length === 0 ? (
          <EmptyState title="No capabilities" description="Providers will show capability matrix." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-gray-400 border-b">
                  <th className="py-2 pr-4 font-medium">Provider</th>
                  {Object.keys(CAPABILITY_LABELS).map((key) => (
                    <th key={key} className="py-2 px-2 font-medium text-center">
                      {CAPABILITY_LABELS[key]}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {capabilityMatrix.map((row) => (
                  <tr key={row.id} className="border-b border-gray-50">
                    <td className="py-2 pr-4 font-medium text-gray-800">{row.name}</td>
                    {Object.keys(CAPABILITY_LABELS).map((key) => (
                      <td key={key} className="py-2 px-2 text-center">
                        {row.capabilities[key as keyof typeof row.capabilities] ? (
                          <CheckCircle2 size={14} className="inline text-emerald-600" />
                        ) : (
                          <span className="text-gray-300">—</span>
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="text-[10px] text-gray-400">
          Message Send and Template Messages are tracked but disabled in v1 — operators send manually
          from WhatsApp Center.
        </p>
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        <div className="card p-4 space-y-3">
          <p className="text-sm font-semibold text-gray-900 flex items-center gap-2">
            <Plug size={16} />
            Connection Health
          </p>
          {(health?.provider_health ?? []).length === 0 ? (
            <EmptyState title="No health data" description="Run a connection test." />
          ) : (
            <ul className="space-y-2">
              {(health?.provider_health ?? []).map((item: WhatsAppProviderHealthItem) => (
                <li key={item.provider_id} className="border border-gray-100 rounded-lg p-3 text-xs">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-gray-800">{item.provider_name}</span>
                    {item.connection_ok ? (
                      <CheckCircle2 size={14} className="text-emerald-600" />
                    ) : (
                      <XCircle size={14} className="text-amber-600" />
                    )}
                  </div>
                  <p className="text-gray-500 mt-1">{item.message}</p>
                  <p className="text-[10px] text-gray-400 mt-1">
                    {PROVIDER_TYPE_LABELS[item.provider_type]} · Phone: {item.phone_number ?? "—"} ·
                    Last test: {formatDt(item.last_connection_test)}
                  </p>
                </li>
              ))}
            </ul>
          )}
          {(health?.integration_checks ?? []).length > 0 && (
            <div className="pt-2 border-t border-gray-100">
              <p className="text-[10px] uppercase text-gray-400 font-medium mb-2">
                Integration Checks
              </p>
              <ul className="space-y-1">
                {(health?.integration_checks ?? []).map((check) => (
                  <li key={check.module} className="flex items-center justify-between text-xs">
                    <span className="text-gray-600">{check.module}</span>
                    <StatusBadge status={check.status} />
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        <div className="card p-4 space-y-3">
          <p className="text-sm font-semibold text-gray-900 flex items-center gap-2">
            <Webhook size={16} />
            Webhook Status
          </p>
          {(health?.webhook_status ?? []).length === 0 ? (
            <EmptyState title="No webhooks" description="Webhook framework seeds on first load." />
          ) : (
            <ul className="space-y-2">
              {(health?.webhook_status ?? []).map((hook) => (
                <li key={hook.event_type} className="border border-gray-100 rounded-lg p-3 text-xs">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-gray-800">{hook.event_type}</span>
                    <StatusBadge status={hook.status} />
                  </div>
                  <p className="text-gray-500 mt-1">{hook.message}</p>
                  <p className="text-[10px] text-gray-400 mt-1">
                    Processing: {hook.processing_enabled ? "enabled" : "disabled (v1)"}
                  </p>
                </li>
              ))}
            </ul>
          )}
          <p className="text-[10px] text-gray-400 flex items-start gap-1.5">
            <MessageCircle size={12} className="shrink-0 mt-0.5" />
            Webhook handlers (inbound_message, contact_update, conversation_update,
            delivery_status_update, template_status_update) are registered for architecture only — no
            live processing in v1.
          </p>
        </div>
      </div>
    </div>
  );
}
