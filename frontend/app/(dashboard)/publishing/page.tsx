"use client";

import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { publishingApi, metaPublishingApi, Platform, PublishingAccount, normalizeList } from "@/lib/api";
import { PLATFORM_CONFIG, cn } from "@/lib/utils";
import Link from "next/link";
import { Plus, Trash2, Radio, Link2, Unlink, CalendarDays, ListOrdered, RefreshCw, ShieldCheck, AlertTriangle } from "lucide-react";
import toast from "react-hot-toast";

const ALL_PLATFORMS: Platform[] = ["telegram", "instagram", "facebook", "tiktok", "linkedin"];

const MOCK_LABELS: Record<Platform, string> = {
  telegram: "Telegram Channel Mock",
  instagram: "Instagram Mock",
  facebook: "Facebook Page Mock",
  tiktok: "TikTok Mock",
  linkedin: "LinkedIn Mock",
};

const STATUS_BADGE: Record<string, string> = {
  mock: "bg-amber-100 text-amber-800",
  connected: "bg-emerald-100 text-emerald-800",
  disconnected: "bg-gray-100 text-gray-600",
  expired: "bg-orange-100 text-orange-800",
  invalid: "bg-red-100 text-red-800",
  missing_permissions: "bg-purple-100 text-purple-800",
  blocked: "bg-red-100 text-red-800",
};

const IMPLEMENTATION_BADGE: Record<string, string> = {
  mock: "bg-amber-100 text-amber-800",
  blocked: "bg-red-100 text-red-800",
  live: "bg-emerald-100 text-emerald-800",
};

function implementationLabel(impl: string | undefined): string {
  if (impl === "live") return "live-ready";
  if (impl === "blocked") return "blocked";
  return "mock";
}

const HEALTH_BADGE: Record<string, string> = {
  healthy: "bg-emerald-100 text-emerald-800",
  mock: "bg-amber-100 text-amber-800",
  expired: "bg-orange-100 text-orange-800",
  missing_permissions: "bg-purple-100 text-purple-800",
  unhealthy: "bg-red-100 text-red-800",
  disconnected: "bg-gray-100 text-gray-600",
  not_configured: "bg-gray-100 text-gray-600",
};

const QUICK_MOCK_BUTTONS: { platform: Platform; label: string }[] = [
  { platform: "telegram", label: "Add Telegram Mock" },
  { platform: "instagram", label: "Add Instagram Mock" },
  { platform: "facebook", label: "Add Facebook Mock" },
  { platform: "tiktok", label: "Add TikTok Mock" },
  { platform: "linkedin", label: "Add LinkedIn Mock" },
];

export default function PublishingPage() {
  const qc = useQueryClient();
  const searchParams = useSearchParams();
  const [showAdd, setShowAdd] = useState(false);
  const [newPlatform, setNewPlatform] = useState<Platform>("telegram");
  const [tgName, setTgName] = useState("");
  const [tgChannel, setTgChannel] = useState("");

  useEffect(() => {
    if (searchParams.get("meta_connected") === "1") {
      toast.success("Meta account connected");
      qc.invalidateQueries({ queryKey: ["meta-connection"] });
      qc.invalidateQueries({ queryKey: ["publishing-accounts"] });
    }
    const metaError = searchParams.get("meta_error");
    if (metaError) {
      toast.error(decodeURIComponent(metaError));
    }
  }, [searchParams, qc]);

  const { data, isLoading } = useQuery({
    queryKey: ["publishing-accounts"],
    queryFn: () => publishingApi.listAccounts().then((r) => r.data),
  });

  const { data: metaConnection, isLoading: metaLoading } = useQuery({
    queryKey: ["meta-connection"],
    queryFn: () => metaPublishingApi.getConnection().then((r) => r.data),
  });

  const createMutation = useMutation({
    mutationFn: (platform: Platform) =>
      publishingApi.createAccount({ platform, mock: true }),
    onSuccess: (_data, platform) => {
      qc.invalidateQueries({ queryKey: ["publishing-accounts"] });
      toast.success(`${MOCK_LABELS[platform]} created`);
      setShowAdd(false);
    },
    onError: (err: unknown) => {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail || "Failed to create account");
    },
  });

  const createRealTelegramMutation = useMutation({
    mutationFn: () =>
      publishingApi.createAccount({
        platform: "telegram",
        mock: false,
        status: "connected",
        account_name: tgName.trim(),
        account_id: tgChannel.trim(),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["publishing-accounts"] });
      toast.success("Telegram channel connected");
      setTgName("");
      setTgChannel("");
    },
    onError: (err: unknown) => {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail || "Failed to connect Telegram channel");
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => publishingApi.deleteAccount(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["publishing-accounts"] });
      toast.success("Account removed");
    },
    onError: () => toast.error("Failed to delete account"),
  });

  const toggleMutation = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      publishingApi.updateAccount(id, { status: status as PublishingAccount["status"] }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["publishing-accounts"] });
      toast.success("Account updated");
    },
    onError: () => toast.error("Failed to update account"),
  });

  const metaConnectMutation = useMutation({
    mutationFn: async () => {
      const { data: start } = await metaPublishingApi.oauthStart();
      if (start.mode === "demo" && start.demo_connect_url) {
        await metaPublishingApi.demoConnect();
        return { mode: "demo" as const };
      }
      if (start.authorize_url) {
        window.location.href = start.authorize_url;
        return { mode: "redirect" as const };
      }
      throw new Error("Meta OAuth is not configured");
    },
    onSuccess: (result) => {
      if (result?.mode === "demo") {
        qc.invalidateQueries({ queryKey: ["meta-connection"] });
        qc.invalidateQueries({ queryKey: ["publishing-accounts"] });
        toast.success("Demo Meta account connected");
      }
    },
    onError: (err: unknown) => {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail || "Failed to start Meta connection");
    },
  });

  const metaRefreshMutation = useMutation({
    mutationFn: () => metaPublishingApi.refresh(),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["meta-connection"] });
      qc.invalidateQueries({ queryKey: ["publishing-accounts"] });
      toast.success(res.data.message || "Meta tokens refreshed");
    },
    onError: (err: unknown) => {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail || "Failed to refresh Meta tokens");
    },
  });

  const metaDisconnectMutation = useMutation({
    mutationFn: () => metaPublishingApi.disconnect(),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["meta-connection"] });
      qc.invalidateQueries({ queryKey: ["publishing-accounts"] });
      toast.success(res.data.message || "Meta disconnected");
    },
    onError: () => toast.error("Failed to disconnect Meta"),
  });

  const accounts = normalizeList<PublishingAccount>(data);
  const metaHealth = metaConnection?.health ?? "not_configured";
  const metaPermissions = metaConnection?.permissions ?? [];
  const metaMissing = metaConnection?.missing_permissions ?? [];

  return (
    <div className="p-6 max-w-3xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Publishing Accounts</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            Connect mock or real publishing accounts.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link href="/publishing/calendar" className="btn-secondary flex items-center gap-1.5">
            <CalendarDays size={15} />
            Publish Calendar
          </Link>
          <Link href="/publishing/queue" className="btn-secondary flex items-center gap-1.5">
            <ListOrdered size={15} />
            Publishing Queue
          </Link>
          <button className="btn-primary" onClick={() => setShowAdd(true)}>
            <Plus size={15} /> Add mock account
          </button>
        </div>
      </div>

      <div className="card p-4 mb-4 border-indigo-100 bg-indigo-50/40">
        <div className="flex items-start justify-between gap-3 mb-2">
          <div>
            <h3 className="text-sm font-semibold text-gray-900">Connect Meta (Facebook + Instagram)</h3>
            <p className="text-xs text-indigo-900/80 mt-0.5">
              Facebook Page publishing is live-ready when connected with publish permissions.
              Instagram remains mock-only in this milestone.
            </p>
          </div>
          <span className={cn("text-[10px] px-2 py-0.5 rounded-full font-medium shrink-0", HEALTH_BADGE[metaHealth] ?? "bg-gray-100 text-gray-600")}>
            {metaHealth.replace(/_/g, " ")}
          </span>
        </div>

        {metaLoading ? (
          <div className="h-16 animate-pulse bg-indigo-100/50 rounded" />
        ) : (
          <div className="space-y-3">
            {metaConnection?.connected ? (
              <div className="text-xs text-gray-700 space-y-1">
                {metaConnection.facebook && (
                  <div className="flex items-center gap-2 flex-wrap">
                    <p>
                      <span className="font-medium">Facebook Page:</span>{" "}
                      {metaConnection.facebook.account_name}{" "}
                      <span className="font-mono text-gray-400">({metaConnection.facebook.facebook_page_id})</span>
                    </p>
                    <span className={cn(
                      "text-[10px] px-2 py-0.5 rounded-full font-medium",
                      IMPLEMENTATION_BADGE[metaConnection.facebook.implementation ?? "mock"] ?? "bg-gray-100 text-gray-600",
                    )}>
                      Facebook: {implementationLabel(metaConnection.facebook.implementation)}
                    </span>
                  </div>
                )}
                {metaConnection.instagram && (
                  <div className="flex items-center gap-2 flex-wrap">
                    <p>
                      <span className="font-medium">Instagram Business:</span>{" "}
                      {metaConnection.instagram.account_name}{" "}
                      <span className="font-mono text-gray-400">({metaConnection.instagram.instagram_business_account_id})</span>
                    </p>
                    <span className={cn(
                      "text-[10px] px-2 py-0.5 rounded-full font-medium",
                      IMPLEMENTATION_BADGE.mock,
                    )}>
                      Instagram: mock
                    </span>
                  </div>
                )}
                <p>
                  <span className="font-medium">Token expiry:</span>{" "}
                  {metaConnection.expires_at
                    ? new Date(metaConnection.expires_at).toLocaleString()
                    : "No expiry (long-lived page token)"}
                  {metaConnection.token_expired && (
                    <span className="ml-2 text-orange-700 font-medium">Expired</span>
                  )}
                </p>
              </div>
            ) : (
              <p className="text-xs text-gray-600">
                {metaConnection?.oauth_configured
                  ? "No Meta account connected yet. Authorize via Facebook Login to link your Page and Instagram Business account."
                  : "Meta OAuth credentials not configured on the server. Use demo connect when DEMO_MODE is enabled."}
              </p>
            )}

            {metaPermissions.length > 0 && (
              <div>
                <p className="text-[10px] text-gray-500 uppercase font-medium tracking-wide mb-1">Permissions</p>
                <div className="flex flex-wrap gap-1">
                  {metaPermissions.map((perm) => (
                    <span key={perm} className="text-[10px] px-1.5 py-0.5 rounded bg-white border border-indigo-100 text-indigo-800 font-mono">
                      {perm}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {metaMissing.length > 0 && (
              <div className="flex items-start gap-1.5 text-xs text-purple-800 bg-purple-50 border border-purple-100 rounded p-2">
                <AlertTriangle size={14} className="shrink-0 mt-0.5" />
                <span>Missing permissions: {metaMissing.join(", ")}</span>
              </div>
            )}

            {(metaConnection?.blockers?.length ?? 0) > 0 && (
              <div className="flex items-start gap-1.5 text-xs text-amber-800 bg-amber-50 border border-amber-100 rounded p-2">
                <ShieldCheck size={14} className="shrink-0 mt-0.5" />
                <ul className="list-disc list-inside">
                  {metaConnection!.blockers.map((b) => (
                    <li key={b}>{b}</li>
                  ))}
                </ul>
              </div>
            )}

            <div className="flex flex-wrap gap-2 pt-1">
              <button
                type="button"
                className="btn-primary text-xs"
                disabled={metaConnectMutation.isPending}
                onClick={() => metaConnectMutation.mutate()}
              >
                <Link2 size={13} />
                {metaConnectMutation.isPending
                  ? "Connecting…"
                  : metaConnection?.connected
                    ? "Reconnect Meta"
                    : "Connect Meta"}
              </button>
              {metaConnection?.connected && (
                <>
                  <button
                    type="button"
                    className="btn-secondary text-xs"
                    disabled={metaRefreshMutation.isPending}
                    onClick={() => metaRefreshMutation.mutate()}
                  >
                    <RefreshCw size={13} />
                    {metaRefreshMutation.isPending ? "Refreshing…" : "Refresh token"}
                  </button>
                  <button
                    type="button"
                    className="btn-secondary text-xs text-red-600 hover:bg-red-50"
                    disabled={metaDisconnectMutation.isPending}
                    onClick={() => {
                      if (confirm("Disconnect Meta and clear stored tokens?")) {
                        metaDisconnectMutation.mutate();
                      }
                    }}
                  >
                    <Unlink size={13} />
                    Disconnect
                  </button>
                </>
              )}
            </div>
          </div>
        )}
      </div>

      <div className="card p-4 mb-4 border-sky-100 bg-sky-50/40">
        <h3 className="text-sm font-semibold text-gray-900 mb-1">Connect Telegram channel</h3>
        <p className="text-xs text-sky-800 mb-3">
          Add your bot as admin to the Telegram channel before publishing.
        </p>
        <div className="space-y-2">
          <div>
            <label className="text-[10px] text-gray-500 uppercase font-medium tracking-wide">Account name</label>
            <input
              className="input text-xs mt-1"
              placeholder="My brand channel"
              value={tgName}
              onChange={(e) => setTgName(e.target.value)}
            />
          </div>
          <div>
            <label className="text-[10px] text-gray-500 uppercase font-medium tracking-wide">
              Channel username or chat ID
            </label>
            <input
              className="input text-xs mt-1 font-mono"
              placeholder="@my_channel or -1001234567890"
              value={tgChannel}
              onChange={(e) => setTgChannel(e.target.value)}
            />
          </div>
          <button
            type="button"
            className="btn-primary text-xs"
            disabled={createRealTelegramMutation.isPending || !tgName.trim() || !tgChannel.trim()}
            onClick={() => createRealTelegramMutation.mutate()}
          >
            {createRealTelegramMutation.isPending ? "Connecting…" : "Connect Telegram channel"}
          </button>
        </div>
      </div>

      <div className="card p-4 mb-4">
        <h3 className="text-sm font-semibold text-gray-900 mb-2">Quick add mock accounts</h3>
        <p className="text-xs text-gray-500 mb-3">
          One-click setup for each platform — no real API credentials required.
        </p>
        <div className="flex flex-wrap gap-2">
          {QUICK_MOCK_BUTTONS.map(({ platform, label }) => (
            <button
              key={platform}
              type="button"
              className="btn-secondary text-xs"
              disabled={createMutation.isPending}
              onClick={() => createMutation.mutate(platform)}
            >
              <Plus size={13} />
              {createMutation.isPending && createMutation.variables === platform
                ? "Creating…"
                : label}
            </button>
          ))}
        </div>
      </div>

      {showAdd && (
        <div className="card p-4 mb-4">
          <h3 className="text-sm font-semibold text-gray-900 mb-3">Add mock account</h3>
          <div className="flex flex-wrap gap-2 mb-3">
            {ALL_PLATFORMS.map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => setNewPlatform(p)}
                className={cn(
                  "text-xs px-3 py-1.5 rounded-lg border font-medium transition-colors",
                  newPlatform === p
                    ? "border-brand-500 bg-brand-50 text-brand-800"
                    : "border-gray-200 text-gray-600 hover:bg-gray-50",
                )}
              >
                {MOCK_LABELS[p]}
              </button>
            ))}
          </div>
          <div className="flex gap-2">
            <button
              className="btn-primary text-xs"
              disabled={createMutation.isPending}
              onClick={() => createMutation.mutate(newPlatform)}
            >
              {createMutation.isPending ? "Creating…" : `Create ${MOCK_LABELS[newPlatform]}`}
            </button>
            <button className="btn-secondary text-xs" onClick={() => setShowAdd(false)}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {isLoading ? (
        <div className="card p-8 animate-pulse">
          <div className="h-4 bg-gray-100 rounded w-48 mb-3" />
          <div className="h-3 bg-gray-100 rounded w-full" />
        </div>
      ) : accounts.length === 0 ? (
        <div className="card p-8 text-center">
          <Radio size={28} className="mx-auto text-gray-300 mb-3" />
          <p className="text-sm text-gray-500">No publishing accounts yet.</p>
          <p className="text-xs text-gray-400 mt-1">Add a mock account to test publishing from Content.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {accounts.map((account) => {
            const platformCfg = PLATFORM_CONFIG[account.platform];
            return (
              <div key={account.id} className="card p-4 flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className={cn("text-xs px-2 py-0.5 rounded-full font-medium", platformCfg?.color)}>
                      {platformCfg?.label ?? account.platform}
                    </span>
                    <span className={cn("text-[10px] px-2 py-0.5 rounded-full font-medium", STATUS_BADGE[account.status])}>
                      {account.status}
                    </span>
                  </div>
                  <p className="text-sm font-medium text-gray-900 mt-1.5">{account.account_name}</p>
                  <p className="text-xs text-gray-400 font-mono mt-0.5">{account.account_id}</p>
                  {(account.platform === "facebook" || account.platform === "instagram") && account.status !== "mock" && (
                    <div className="mt-2 space-y-0.5 text-[10px] text-gray-500">
                      {account.platform === "facebook" && (
                        <p>
                          Publish:{" "}
                          <span className={cn(
                            "font-medium px-1.5 py-0.5 rounded",
                            IMPLEMENTATION_BADGE[
                              (account.account_metadata as { demo?: boolean } | undefined)?.demo
                                ? "blocked"
                                : metaConnection?.facebook?.implementation ?? "blocked"
                            ] ?? "bg-gray-100 text-gray-600",
                          )}>
                            {(account.account_metadata as { demo?: boolean } | undefined)?.demo
                              ? "blocked (demo)"
                              : implementationLabel(metaConnection?.facebook?.implementation)}
                          </span>
                        </p>
                      )}
                      {account.platform === "instagram" && (
                        <p>
                          Publish: <span className="font-medium text-amber-700">mock</span>
                        </p>
                      )}
                      {account.expires_at && (
                        <p>
                          Token expires: {new Date(account.expires_at).toLocaleString()}
                          {account.token_expired && <span className="text-orange-600 ml-1">(expired)</span>}
                        </p>
                      )}
                      {account.health && (
                        <p>Health: <span className="font-medium">{account.health}</span></p>
                      )}
                      {(account.missing_permissions?.length ?? 0) > 0 && (
                        <p className="text-purple-700">Missing: {account.missing_permissions!.join(", ")}</p>
                      )}
                    </div>
                  )}
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  {account.platform !== "facebook" && account.platform !== "instagram" && account.status === "disconnected" ? (
                    <button
                      type="button"
                      className="btn-secondary text-xs py-1"
                      title="Connect"
                      onClick={() => toggleMutation.mutate({ id: account.id, status: "mock" })}
                    >
                      <Link2 size={13} />
                    </button>
                  ) : account.platform !== "facebook" && account.platform !== "instagram" ? (
                    <button
                      type="button"
                      className="btn-secondary text-xs py-1"
                      title="Disconnect"
                      onClick={() => toggleMutation.mutate({ id: account.id, status: "disconnected" })}
                    >
                      <Unlink size={13} />
                    </button>
                  ) : null}
                  <button
                    type="button"
                    className="btn-secondary text-xs py-1 text-red-600 hover:bg-red-50"
                    onClick={() => {
                      if (confirm(`Delete ${account.account_name}?`)) {
                        deleteMutation.mutate(account.id);
                      }
                    }}
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
