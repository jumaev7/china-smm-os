"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { publishingApi, Platform, PublishingAccount, normalizeList } from "@/lib/api";
import { PLATFORM_CONFIG, cn } from "@/lib/utils";
import Link from "next/link";
import { Plus, Trash2, Radio, Link2, Unlink, CalendarDays, ListOrdered } from "lucide-react";
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
  const [showAdd, setShowAdd] = useState(false);
  const [newPlatform, setNewPlatform] = useState<Platform>("telegram");
  const [tgName, setTgName] = useState("");
  const [tgChannel, setTgChannel] = useState("");

  const { data, isLoading } = useQuery({
    queryKey: ["publishing-accounts"],
    queryFn: () => publishingApi.listAccounts().then((r) => r.data),
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

  const accounts = normalizeList<PublishingAccount>(data);

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
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  {account.status === "disconnected" ? (
                    <button
                      type="button"
                      className="btn-secondary text-xs py-1"
                      title="Connect"
                      onClick={() => toggleMutation.mutate({ id: account.id, status: "mock" })}
                    >
                      <Link2 size={13} />
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="btn-secondary text-xs py-1"
                      title="Disconnect"
                      onClick={() => toggleMutation.mutate({ id: account.id, status: "disconnected" })}
                    >
                      <Unlink size={13} />
                    </button>
                  )}
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
