"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import { Phone, Plus } from "lucide-react";
import toast from "react-hot-toast";
import { WhatsAppSubNav } from "@/components/whatsapp/WhatsAppSubNav";
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
  whatsappApi,
  type WhatsAppAccountStatus,
  type WhatsAppAccountType,
  type WhatsAppBusinessAccount,
} from "@/lib/api";
import { useTranslation } from "@/lib/I18nProvider";

const STATUS_VARIANT: Record<string, "success" | "warning" | "danger" | "neutral"> = {
  connected: "success",
  not_connected: "neutral",
  sync_error: "danger",
  disabled: "warning",
};

export default function WhatsAppAccountsPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({
    account_name: "",
    account_type: "whatsapp_cloud_api" as WhatsAppAccountType,
    phone_number: "",
    business_display_name: "",
    provider: "demo",
  });

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["whatsapp-accounts"],
    queryFn: () => whatsappApi.listAccounts().then((r) => r.data),
  });

  const createMutation = useMutation({
    mutationFn: () =>
      whatsappApi.createAccount({
        account_name: form.account_name.trim(),
        account_type: form.account_type,
        phone_number: form.phone_number.trim() || null,
        business_display_name: form.business_display_name.trim() || null,
        provider: form.provider || "demo",
      }).then((r) => r.data),
    onSuccess: () => {
      setShowCreate(false);
      setForm({
        account_name: "",
        account_type: "whatsapp_cloud_api",
        phone_number: "",
        business_display_name: "",
        provider: "demo",
      });
      qc.invalidateQueries({ queryKey: ["whatsapp-accounts"] });
      qc.invalidateQueries({ queryKey: ["whatsapp-dashboard"] });
      toast.success(t("whatsapp.accountCreated"));
    },
    onError: (err: Error) => toast.error(err.message || "Failed to create account"),
  });

  const updateStatusMutation = useMutation({
    mutationFn: ({ id, status }: { id: string; status: WhatsAppAccountStatus }) =>
      whatsappApi.updateAccount(id, { status }).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["whatsapp-accounts"] });
      qc.invalidateQueries({ queryKey: ["whatsapp-dashboard"] });
      toast.success(t("whatsapp.accountUpdated"));
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
        <ErrorState message={t("whatsapp.loadError")} onRetry={() => refetch()} />
      </PageShell>
    );
  }

  const accounts = data.items;

  return (
    <PageShell>
      <PageHeader
        title={t("whatsapp.nav.accounts")}
        subtitle={t("whatsapp.accountsSubtitle")}
        icon={Phone}
        actions={
          <button
            type="button"
            className="btn-primary text-sm inline-flex items-center gap-1.5"
            onClick={() => setShowCreate(true)}
          >
            <Plus size={14} />
            {t("whatsapp.addAccount")}
          </button>
        }
      />
      <WhatsAppSubNav />

      {accounts.length === 0 ? (
        <div className="mt-4">
          <EmptyState message={t("whatsapp.noAccounts")} />
        </div>
      ) : (
        <div className="mt-4">
          <DataTable>
            <DataTableHead>
              <DataTableRow>
                <DataTableTh>{t("whatsapp.colAccountName")}</DataTableTh>
                <DataTableTh>{t("whatsapp.colPhoneNumber")}</DataTableTh>
                <DataTableTh>{t("whatsapp.colBusinessDisplayName")}</DataTableTh>
                <DataTableTh>{t("whatsapp.colAccountType")}</DataTableTh>
                <DataTableTh>{t("whatsapp.colStatus")}</DataTableTh>
                <DataTableTh>{t("whatsapp.colConnected")}</DataTableTh>
                <DataTableTh>{t("whatsapp.colLastSync")}</DataTableTh>
                <DataTableTh />
              </DataTableRow>
            </DataTableHead>
            <DataTableBody>
              {accounts.map((row: WhatsAppBusinessAccount) => (
                <DataTableRow key={row.id}>
                  <DataTableTd>{row.account_name}</DataTableTd>
                  <DataTableTd>{row.phone_number || "—"}</DataTableTd>
                  <DataTableTd>{row.business_display_name || "—"}</DataTableTd>
                  <DataTableTd>{row.account_type.replace(/_/g, " ")}</DataTableTd>
                  <DataTableTd>
                    <StatusBadge variant={STATUS_VARIANT[row.status] ?? "neutral"}>
                      {t(`whatsapp.accountStatus.${row.status}`)}
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
                          status: e.target.value as WhatsAppAccountStatus,
                        })
                      }
                    >
                      <option value="not_connected">{t("whatsapp.accountStatus.not_connected")}</option>
                      <option value="connected">{t("whatsapp.accountStatus.connected")}</option>
                      <option value="sync_error">{t("whatsapp.accountStatus.sync_error")}</option>
                      <option value="disabled">{t("whatsapp.accountStatus.disabled")}</option>
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
            <h3 className="font-semibold text-gray-900">{t("whatsapp.addAccount")}</h3>
            <input
              className="input w-full text-sm"
              placeholder={t("whatsapp.colAccountName")}
              value={form.account_name}
              onChange={(e) => setForm((f) => ({ ...f, account_name: e.target.value }))}
            />
            <input
              className="input w-full text-sm"
              placeholder={t("whatsapp.colPhoneNumber")}
              value={form.phone_number}
              onChange={(e) => setForm((f) => ({ ...f, phone_number: e.target.value }))}
            />
            <input
              className="input w-full text-sm"
              placeholder={t("whatsapp.colBusinessDisplayName")}
              value={form.business_display_name}
              onChange={(e) => setForm((f) => ({ ...f, business_display_name: e.target.value }))}
            />
            <select
              className="input w-full text-sm"
              value={form.account_type}
              onChange={(e) => setForm((f) => ({ ...f, account_type: e.target.value as WhatsAppAccountType }))}
            >
              <option value="whatsapp_cloud_api">WhatsApp Cloud API</option>
              <option value="whatsapp_business_api">WhatsApp Business API</option>
              <option value="third_party_connection">Third Party Connection</option>
              <option value="manual_import">Manual Import</option>
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
                className="btn-primary flex-1 bg-green-600 hover:bg-green-700 border-green-600"
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
