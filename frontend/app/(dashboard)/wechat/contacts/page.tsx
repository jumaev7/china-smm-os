"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import { Link2, MessageCircle } from "lucide-react";
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
import { PageHeader, PageShell } from "@/components/ui/design-system";
import { buyersApi, salesCrmApi, wechatApi, type WeChatContactExtended } from "@/lib/api";
import { useTranslation } from "@/lib/I18nProvider";

export default function WeChatContactsPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [linkContactId, setLinkContactId] = useState<string | null>(null);
  const [linkBuyerId, setLinkBuyerId] = useState("");
  const [linkCustomerId, setLinkCustomerId] = useState("");

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["wechat-contacts-extended", search],
    queryFn: () =>
      wechatApi.listContactsExtended({ search: search || undefined, limit: 100 }).then((r) => r.data),
  });

  const { data: buyers } = useQuery({
    queryKey: ["buyers-wechat-link"],
    queryFn: () => buyersApi.list({ limit: 100 }).then((r) => r.data),
    enabled: !!linkContactId,
  });

  const { data: customers } = useQuery({
    queryKey: ["customers-wechat-link"],
    queryFn: () => salesCrmApi.listCustomers({ limit: 100 }).then((r) => r.data.items),
    enabled: !!linkContactId,
  });

  const linkBuyerMutation = useMutation({
    mutationFn: () => wechatApi.linkContactBuyer(linkContactId!, linkBuyerId).then((r) => r.data),
    onSuccess: (result) => {
      setLinkContactId(null);
      setLinkBuyerId("");
      qc.invalidateQueries({ queryKey: ["wechat-contacts-extended"] });
      toast.success(`${t("wechat.linkedBuyer")}: ${result.buyer_name}`);
    },
    onError: (err: Error) => toast.error(err.message || "Link failed"),
  });

  const linkCustomerMutation = useMutation({
    mutationFn: () => wechatApi.linkContactCustomer(linkContactId!, linkCustomerId).then((r) => r.data),
    onSuccess: (result) => {
      setLinkContactId(null);
      setLinkCustomerId("");
      qc.invalidateQueries({ queryKey: ["wechat-contacts-extended"] });
      toast.success(`${t("wechat.linkedCustomer")}: ${result.customer_name}`);
    },
    onError: (err: Error) => toast.error(err.message || "Link failed"),
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

  const contacts = data.items;

  return (
    <PageShell>
      <PageHeader
        title={t("wechat.nav.contacts")}
        subtitle={t("wechat.contactsSubtitle")}
        icon={MessageCircle}
      />
      <WeChatSubNav />

      <div className="mt-4 flex flex-col sm:flex-row gap-2">
        <input
          className="input text-sm flex-1 max-w-md"
          placeholder={t("wechat.searchContacts")}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <Link href="/wechat/messages" className="btn-secondary text-sm inline-flex items-center justify-center">
          {t("wechat.openMessages")}
        </Link>
      </div>

      {contacts.length === 0 ? (
        <div className="mt-4">
          <EmptyState message={t("wechat.noContacts")} />
        </div>
      ) : (
        <div className="mt-4">
          <DataTable>
            <DataTableHead>
              <DataTableRow>
                <DataTableTh>{t("wechat.colDisplayName")}</DataTableTh>
                <DataTableTh>{t("wechat.colCompany")}</DataTableTh>
                <DataTableTh>{t("wechat.colCountry")}</DataTableTh>
                <DataTableTh>{t("wechat.colIndustry")}</DataTableTh>
                <DataTableTh>{t("wechat.colTags")}</DataTableTh>
                <DataTableTh>{t("wechat.colCrmLinks")}</DataTableTh>
                <DataTableTh>{t("wechat.colLastInteraction")}</DataTableTh>
                <DataTableTh />
              </DataTableRow>
            </DataTableHead>
            <DataTableBody>
              {contacts.map((row: WeChatContactExtended) => (
                <DataTableRow key={row.id}>
                  <DataTableTd>
                    <p className="font-medium text-gray-900">{row.display_name}</p>
                    <p className="text-[11px] text-gray-400">{row.wechat_id || row.wecom_id || "—"}</p>
                  </DataTableTd>
                  <DataTableTd>{row.company || "—"}</DataTableTd>
                  <DataTableTd>{row.country || "—"}</DataTableTd>
                  <DataTableTd>{row.industry || "—"}</DataTableTd>
                  <DataTableTd>
                    {row.tags.length ? (
                      <div className="flex flex-wrap gap-1">
                        {row.tags.map((tag) => (
                          <span
                            key={tag}
                            className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-600"
                          >
                            {tag}
                          </span>
                        ))}
                      </div>
                    ) : (
                      "—"
                    )}
                  </DataTableTd>
                  <DataTableTd>
                    <div className="text-xs text-gray-600 space-y-0.5">
                      {row.linked_lead_name && <p>Lead: {row.linked_lead_name}</p>}
                      {row.linked_buyer_name && <p>Buyer: {row.linked_buyer_name}</p>}
                      {row.linked_customer_name && <p>Customer: {row.linked_customer_name}</p>}
                      {!row.linked_lead_name && !row.linked_buyer_name && !row.linked_customer_name && "—"}
                    </div>
                  </DataTableTd>
                  <DataTableTd>
                    {row.last_interaction_at
                      ? format(parseISO(row.last_interaction_at), "MMM d, HH:mm")
                      : "—"}
                  </DataTableTd>
                  <DataTableTd>
                    <button
                      type="button"
                      className="btn-secondary text-xs inline-flex items-center gap-1"
                      onClick={() => setLinkContactId(row.id)}
                    >
                      <Link2 size={12} />
                      {t("wechat.linkCrm")}
                    </button>
                  </DataTableTd>
                </DataTableRow>
              ))}
            </DataTableBody>
          </DataTable>
        </div>
      )}

      {linkContactId && (
        <div data-app-modal className="fixed inset-0 z-50 bg-black/30 flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-5 space-y-3">
            <h3 className="font-semibold text-gray-900">{t("wechat.linkCrm")}</h3>
            <label className="text-xs text-gray-600">{t("wechat.linkBuyer")}</label>
            <select
              className="input w-full text-sm"
              value={linkBuyerId}
              onChange={(e) => setLinkBuyerId(e.target.value)}
            >
              <option value="">—</option>
              {(buyers?.items ?? []).map((b) => (
                <option key={b.id} value={b.id}>{b.company_name}</option>
              ))}
            </select>
            <button
              type="button"
              className="btn-secondary w-full text-sm"
              disabled={!linkBuyerId || linkBuyerMutation.isPending}
              onClick={() => linkBuyerMutation.mutate()}
            >
              {t("wechat.linkBuyer")}
            </button>
            <label className="text-xs text-gray-600">{t("wechat.linkCustomer")}</label>
            <select
              className="input w-full text-sm"
              value={linkCustomerId}
              onChange={(e) => setLinkCustomerId(e.target.value)}
            >
              <option value="">—</option>
              {(customers ?? []).map((c) => (
                <option key={c.id} value={c.id}>{c.company || c.name}</option>
              ))}
            </select>
            <button
              type="button"
              className="btn-secondary w-full text-sm"
              disabled={!linkCustomerId || linkCustomerMutation.isPending}
              onClick={() => linkCustomerMutation.mutate()}
            >
              {t("wechat.linkCustomer")}
            </button>
            <button type="button" className="btn-primary w-full text-sm" onClick={() => setLinkContactId(null)}>
              {t("common.cancel")}
            </button>
          </div>
        </div>
      )}
    </PageShell>
  );
}
