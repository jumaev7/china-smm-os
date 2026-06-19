"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import { Link2, Phone } from "lucide-react";
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
import { PageHeader, PageShell } from "@/components/ui/design-system";
import { buyersApi, salesCrmApi, whatsappApi, type WhatsAppContactExtended } from "@/lib/api";
import { useTranslation } from "@/lib/I18nProvider";

export default function WhatsAppContactsPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [linkContactId, setLinkContactId] = useState<string | null>(null);
  const [linkBuyerId, setLinkBuyerId] = useState("");
  const [linkCustomerId, setLinkCustomerId] = useState("");
  const [linkLeadId, setLinkLeadId] = useState("");

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["whatsapp-contacts-extended", search],
    queryFn: () =>
      whatsappApi.listContactsExtended({ search: search || undefined, limit: 100 }).then((r) => r.data),
  });

  const { data: buyers } = useQuery({
    queryKey: ["buyers-whatsapp-link"],
    queryFn: () => buyersApi.list({ limit: 100 }).then((r) => r.data),
    enabled: !!linkContactId,
  });

  const { data: customers } = useQuery({
    queryKey: ["customers-whatsapp-link"],
    queryFn: () => salesCrmApi.listCustomers({ limit: 100 }).then((r) => r.data.items),
    enabled: !!linkContactId,
  });

  const { data: leads } = useQuery({
    queryKey: ["leads-whatsapp-link"],
    queryFn: () => salesCrmApi.listLeads({ limit: 100 }).then((r) => r.data.items),
    enabled: !!linkContactId,
  });

  const linkBuyerMutation = useMutation({
    mutationFn: () => whatsappApi.linkContactBuyer(linkContactId!, linkBuyerId).then((r) => r.data),
    onSuccess: (result) => {
      setLinkContactId(null);
      setLinkBuyerId("");
      qc.invalidateQueries({ queryKey: ["whatsapp-contacts-extended"] });
      toast.success(`${t("whatsapp.linkedBuyer")}: ${result.buyer_name}`);
    },
    onError: (err: Error) => toast.error(err.message || "Link failed"),
  });

  const linkCustomerMutation = useMutation({
    mutationFn: () => whatsappApi.linkContactCustomer(linkContactId!, linkCustomerId).then((r) => r.data),
    onSuccess: (result) => {
      setLinkContactId(null);
      setLinkCustomerId("");
      qc.invalidateQueries({ queryKey: ["whatsapp-contacts-extended"] });
      toast.success(`${t("whatsapp.linkedCustomer")}: ${result.customer_name}`);
    },
    onError: (err: Error) => toast.error(err.message || "Link failed"),
  });

  const linkLeadMutation = useMutation({
    mutationFn: () => whatsappApi.linkContactLead(linkContactId!, linkLeadId).then((r) => r.data),
    onSuccess: (result) => {
      setLinkContactId(null);
      setLinkLeadId("");
      qc.invalidateQueries({ queryKey: ["whatsapp-contacts-extended"] });
      toast.success(`${t("whatsapp.linkedLead")}: ${result.lead_name}`);
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
        <ErrorState message={t("whatsapp.loadError")} onRetry={() => refetch()} />
      </PageShell>
    );
  }

  const contacts = data.items;

  return (
    <PageShell>
      <PageHeader
        title={t("whatsapp.nav.contacts")}
        subtitle={t("whatsapp.contactsSubtitle")}
        icon={Phone}
      />
      <WhatsAppSubNav />

      <div className="mt-4 flex flex-col sm:flex-row gap-2">
        <input
          className="input text-sm flex-1 max-w-md"
          placeholder={t("whatsapp.searchContacts")}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <Link href="/whatsapp/messages" className="btn-secondary text-sm inline-flex items-center justify-center">
          {t("whatsapp.openMessages")}
        </Link>
      </div>

      {contacts.length === 0 ? (
        <div className="mt-4">
          <EmptyState message={t("whatsapp.noContacts")} />
        </div>
      ) : (
        <div className="mt-4">
          <DataTable>
            <DataTableHead>
              <DataTableRow>
                <DataTableTh>{t("whatsapp.colDisplayName")}</DataTableTh>
                <DataTableTh>{t("whatsapp.colPhoneNumber")}</DataTableTh>
                <DataTableTh>{t("whatsapp.colCompany")}</DataTableTh>
                <DataTableTh>{t("whatsapp.colCountry")}</DataTableTh>
                <DataTableTh>{t("whatsapp.colCity")}</DataTableTh>
                <DataTableTh>{t("whatsapp.colIndustry")}</DataTableTh>
                <DataTableTh>{t("whatsapp.colTags")}</DataTableTh>
                <DataTableTh>{t("whatsapp.colCrmLinks")}</DataTableTh>
                <DataTableTh>{t("whatsapp.colLastInteraction")}</DataTableTh>
                <DataTableTh />
              </DataTableRow>
            </DataTableHead>
            <DataTableBody>
              {contacts.map((row: WhatsAppContactExtended) => (
                <DataTableRow key={row.id}>
                  <DataTableTd>
                    <p className="font-medium text-gray-900">{row.display_name}</p>
                  </DataTableTd>
                  <DataTableTd>{row.phone_number || "—"}</DataTableTd>
                  <DataTableTd>{row.company || "—"}</DataTableTd>
                  <DataTableTd>{row.country || "—"}</DataTableTd>
                  <DataTableTd>{row.city || "—"}</DataTableTd>
                  <DataTableTd>{row.industry || "—"}</DataTableTd>
                  <DataTableTd>
                    {row.tags.length ? (
                      <div className="flex flex-wrap gap-1">
                        {row.tags.map((tag) => (
                          <span
                            key={tag}
                            className="text-[10px] px-1.5 py-0.5 rounded bg-green-50 text-green-700"
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
                      {t("whatsapp.linkCrm")}
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
            <h3 className="font-semibold text-gray-900">{t("whatsapp.linkCrm")}</h3>
            <label className="text-xs text-gray-600">{t("whatsapp.linkLead")}</label>
            <select
              className="input w-full text-sm"
              value={linkLeadId}
              onChange={(e) => setLinkLeadId(e.target.value)}
            >
              <option value="">—</option>
              {(leads ?? []).map((l) => (
                <option key={l.id} value={l.id}>{l.company || l.name}</option>
              ))}
            </select>
            <button
              type="button"
              className="btn-secondary w-full text-sm"
              disabled={!linkLeadId || linkLeadMutation.isPending}
              onClick={() => linkLeadMutation.mutate()}
            >
              {t("whatsapp.linkLead")}
            </button>
            <label className="text-xs text-gray-600">{t("whatsapp.linkBuyer")}</label>
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
              {t("whatsapp.linkBuyer")}
            </button>
            <label className="text-xs text-gray-600">{t("whatsapp.linkCustomer")}</label>
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
              {t("whatsapp.linkCustomer")}
            </button>
            <button
              type="button"
              className="btn-primary w-full text-sm bg-green-600 hover:bg-green-700 border-green-600"
              onClick={() => setLinkContactId(null)}
            >
              {t("common.cancel")}
            </button>
          </div>
        </div>
      )}
    </PageShell>
  );
}
