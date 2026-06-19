"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import { MessageCircle, Plus } from "lucide-react";
import toast from "react-hot-toast";
import { WeChatSubNav } from "@/components/wechat/WeChatSubNav";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import {
  DataTable,
  DataTableBody,
  DataTableHead,
  DataTableRow,
  DataTableTd,
  DataTableTh,
} from "@/components/ui/design-system/DataTable";
import { PageHeader, PageShell, StatusBadge } from "@/components/ui/design-system";
import {
  wechatApi,
  type WeChatAccount,
  type WeChatAccountStatus,
  type WeChatAccountType,
} from "@/lib/api";
import { useTranslation } from "@/lib/I18nProvider";

const STATUS_VARIANT: Record<string, "success" | "warning" | "danger" | "neutral"> = {
  connected: "success",
  not_connected: "neutral",
  sync_error: "danger",
  disabled: "warning",
};

export default function WeChatAccountsPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({
    account_name: "",
    account_type: "personal_wechat" as WeChatAccountType,
    provider: "demo",
  });

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["wechat-accounts"],
    queryFn: () => wechatApi.listAccounts().then((r) => r.data),
  });

  const createMutation = useMutation({
    mutationFn: () =>
      wechatApi.createAccount({
        account_name: form.account_name.trim(),
        account_type: form.account_type,
        provider: form.provider || "demo",
      }).then((r) => r.data),
    onSuccess: () => {
      setShowCreate(false);
      setForm({ account_name: "", account_type: "personal_wechat", provider: "demo" });
      qc.invalidateQueries({ queryKey: ["wechat-accounts"] });
      qc.invalidateQueries({ queryKey: ["wechat-dashboard"] });
      toast.success(t("wechat.accountCreated"));
    },
    onError: (err: Error) => toast.error(err.message || "Failed to create account"),
  });

  const updateStatusMutation = useMutation({
    mutationFn: ({ id, status }: { id: string; status: WeChatAccountStatus }) =>
      wechatApi.updateAccount(id, { status }).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["wechat-accounts"] });
      qc.invalidateQueries({ queryKey: ["wechat-dashboard"] });
      toast.success(t("wechat.accountUpdated"));
    },
    onError: (err: Error) => toast.error(err.message || "Update failed"),
  });

  if (isLoading) {
    return (
      <PageShell>
        <LoadingState message={t("common.loading")} />
      </PageShell>
    );
  }

  if (isError || !data) {
    return (
      <PageShell>
        <ErrorState message={t("wechat.loadError")} onRetry={() => refetch()} />
      </PageShell>
    );
  }

  const accounts = data.items;

  return (
    <PageShell>
      <PageHeader
        title={t("wechat.nav.accounts")}
        subtitle={t("wechat.accountsSubtitle")}
        icon={MessageCircle}
        actions={
          <button
            type="button"
            className="btn-primary text-sm inline-flex items-center gap-1.5"
            onClick={() => setShowCreate(true)}
          >
            <Plus size={14} />
            {t("wechat.addAccount")}
          </button>
        }
      />
      <WeChatSubNav />

      {accounts.length === 0 ? (
        <div className="mt-4">
          <EmptyState message={t("wechat.noAccounts")} />
        </div>
      ) : (
        <div className="mt-4">
          <DataTable>
            <DataTableHead>
              <DataTableRow>
                <DataTableTh>{t("wechat.colAccountName")}</DataTableTh>
                <DataTableTh>{t("wechat.colAccountType")}</DataTableTh>
                <DataTableTh>{t("wechat.colStatus")}</DataTableTh>
                <DataTableTh>{t("wechat.colConnected")}</DataTableTh>
                <DataTableTh>{t("wechat.colLastSync")}</DataTableTh>
                <DataTableTh />
              </DataTableRow>
            </DataTableHead>
            <DataTableBody>
              {accounts.map((row: WeChatAccount) => (
                <DataTableRow key={row.id}>
                  <DataTableTd>{row.account_name}</DataTableTd>
                  <DataTableTd>{row.account_type.replace(/_/g, " ")}</DataTableTd>
                  <DataTableTd>
                    <StatusBadge variant={STATUS_VARIANT[row.status] ?? "neutral"}>
                      {t(`wechat.accountStatus.${row.status}`)}
                    </StatusBadge>
                  </DataTableTd>
                  <DataTableTd>
                    {row.connected_at ? format(parseISO(row.connected_at), "MMM d, yyyy") : "—"}
                  </DataTableTd>
                  <DataTableTd>
                    {row.last_sync_at ? format(parseISO(row.last_sync_at), "MMM d, HH:mm") : "—"}
                  </DataTableTd>
                  <DataTableTd>
                    <select
                      className="input text-xs py-1"
                      value={row.status}
                      onChange={(e) =>
                        updateStatusMutation.mutate({
                          id: row.id,
                          status: e.target.value as WeChatAccountStatus,
                        })
                      }
                    >
                      <option value="not_connected">{t("wechat.accountStatus.not_connected")}</option>
                      <option value="connected">{t("wechat.accountStatus.connected")}</option>
                      <option value="sync_error">{t("wechat.accountStatus.sync_error")}</option>
                      <option value="disabled">{t("wechat.accountStatus.disabled")}</option>
                    </select>
                  </DataTableTd>
                </DataTableRow>
              ))}
            </DataTableBody>
          </DataTable>
        </div>
      )}

      {showCreate && (
        <div data-app-modal className="fixed inset-0 z-50 bg-black/30 flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-5 space-y-3">
            <h3 className="font-semibold text-gray-900">{t("wechat.addAccount")}</h3>
            <input
              className="input w-full text-sm"
              placeholder={t("wechat.colAccountName")}
              value={form.account_name}
              onChange={(e) => setForm((f) => ({ ...f, account_name: e.target.value }))}
            />
            <select
              className="input w-full text-sm"
              value={form.account_type}
              onChange={(e) => setForm((f) => ({ ...f, account_type: e.target.value as WeChatAccountType }))}
            >
              <option value="personal_wechat">Personal WeChat</option>
              <option value="wecom">WeCom</option>
              <option value="official_account">Official Account</option>
            </select>
            <select
              className="input w-full text-sm"
              value={form.provider}
              onChange={(e) => setForm((f) => ({ ...f, provider: e.target.value }))}
            >
              <option value="demo">Demo (no credentials)</option>
            </select>
            <div className="flex gap-2 pt-2">
              <button type="button" className="btn-secondary flex-1" onClick={() => setShowCreate(false)}>
                {t("common.cancel")}
              </button>
              <button
                type="button"
                className="btn-primary flex-1"
                disabled={!form.account_name.trim() || createMutation.isPending}
                onClick={() => createMutation.mutate()}
              >
                {createMutation.isPending ? t("common.loading") : t("common.create")}
              </button>
            </div>
          </div>
        </div>
      )}
    </PageShell>
  );
}
