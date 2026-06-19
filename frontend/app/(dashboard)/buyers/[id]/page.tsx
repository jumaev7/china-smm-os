"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import {
  ArrowLeft,
  Building2,
  Clock,
  Link2,
  Loader2,
  MessageSquare,
  Trash2,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  buyersApi,
  salesCrmApi,
  salesProposalsApi,
  type BuyerLinkedEntity,
  type BuyerStatus,
} from "@/lib/api";
import { useTranslation } from "@/lib/I18nProvider";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import { RelatedEntitiesPanel } from "@/components/platform/RelatedEntitiesPanel";

const STATUS_STYLE: Record<BuyerStatus, string> = {
  prospect: "bg-sky-100 text-sky-800",
  contacted: "bg-amber-100 text-amber-800",
  interested: "bg-violet-100 text-violet-800",
  negotiating: "bg-orange-100 text-orange-800",
  active_buyer: "bg-emerald-100 text-emerald-800",
  inactive: "bg-gray-100 text-gray-600",
};

function statusLabel(status: BuyerStatus, t: (k: string) => string) {
  const key = `buyerCrm.status.${status}`;
  const translated = t(key);
  return translated === key ? status.replace(/_/g, " ") : translated;
}

function entityHref(link: BuyerLinkedEntity): string {
  switch (link.entity_type) {
    case "lead":
      return "/leads";
    case "deal":
      return "/deals";
    case "customer":
      return "/customers";
    case "proposal":
      return `/proposals/${link.entity_id}`;
    default:
      return "#";
  }
}

export default function BuyerProfilePage() {
  const { t } = useTranslation();
  const params = useParams();
  const buyerId = params.id as string;
  const qc = useQueryClient();
  const [noteText, setNoteText] = useState("");
  const [linkType, setLinkType] = useState<BuyerLinkedEntity["entity_type"]>("lead");
  const [linkEntityId, setLinkEntityId] = useState("");

  const { data: buyer, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["buyers", buyerId],
    queryFn: () => buyersApi.get(buyerId).then((r) => r.data),
  });

  const { data: timeline } = useQuery({
    queryKey: ["buyers", buyerId, "timeline"],
    queryFn: () => buyersApi.timeline(buyerId).then((r) => r.data),
    enabled: !!buyer,
  });

  const { data: statusHistory } = useQuery({
    queryKey: ["buyers", buyerId, "status-history"],
    queryFn: () => buyersApi.statusHistory(buyerId).then((r) => r.data),
    enabled: !!buyer,
  });

  const { data: leadsData } = useQuery({
    queryKey: ["sales-crm", "leads", "link-picker"],
    queryFn: () => salesCrmApi.listLeads({ limit: 50 }).then((r) => r.data),
    enabled: linkType === "lead",
  });
  const { data: dealsData } = useQuery({
    queryKey: ["sales-crm", "deals", "link-picker"],
    queryFn: () => salesCrmApi.listDeals({ limit: 50 }).then((r) => r.data),
    enabled: linkType === "deal",
  });
  const { data: customersData } = useQuery({
    queryKey: ["sales-crm", "customers", "link-picker"],
    queryFn: () => salesCrmApi.listCustomers({ limit: 50 }).then((r) => r.data),
    enabled: linkType === "customer",
  });
  const { data: proposalsData } = useQuery({
    queryKey: ["sales-proposals", "link-picker"],
    queryFn: () => salesProposalsApi.list({ limit: 50 }).then((r) => r.data),
    enabled: linkType === "proposal",
  });

  const noteMutation = useMutation({
    mutationFn: () => buyersApi.createNote(buyerId, noteText.trim()),
    onSuccess: () => {
      toast.success(t("buyerCrm.noteAdded"));
      setNoteText("");
      qc.invalidateQueries({ queryKey: ["buyers", buyerId] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const linkMutation = useMutation({
    mutationFn: () => buyersApi.createLink(buyerId, linkType, linkEntityId),
    onSuccess: () => {
      toast.success(t("buyerCrm.linkAdded"));
      setLinkEntityId("");
      qc.invalidateQueries({ queryKey: ["buyers", buyerId] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const unlinkMutation = useMutation({
    mutationFn: (linkId: string) => buyersApi.deleteLink(buyerId, linkId),
    onSuccess: () => {
      toast.success(t("buyerCrm.linkRemoved"));
      qc.invalidateQueries({ queryKey: ["buyers", buyerId] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  if (isLoading) return <LoadingState message={t("buyerCrm.loading")} />;
  if (isError || !buyer) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : t("buyerCrm.error")}
        onRetry={() => refetch()}
      />
    );
  }

  const allLinks = [
    ...(buyer.linked_leads ?? []),
    ...(buyer.linked_deals ?? []),
    ...(buyer.linked_customers ?? []),
    ...(buyer.linked_proposals ?? []),
  ];

  const linkOptions =
    linkType === "lead"
      ? (leadsData?.items ?? []).map((l) => ({ id: l.id, label: l.company || l.name }))
      : linkType === "deal"
        ? (dealsData?.items ?? []).map((d) => ({ id: d.id, label: d.title }))
        : linkType === "customer"
          ? (customersData?.items ?? []).map((c) => ({ id: c.id, label: c.company || c.name }))
          : (proposalsData?.items ?? []).map((p) => ({ id: p.id, label: p.title }));

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <Link href="/buyers" className="inline-flex items-center gap-1 text-sm text-brand-700 hover:underline">
        <ArrowLeft size={14} />
        {t("buyerCrm.backToDirectory")}
      </Link>

      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <Building2 size={22} className="text-brand-600" />
            {buyer.company_name}
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            {[buyer.contact_person, buyer.city, buyer.country].filter(Boolean).join(" · ")}
          </p>
        </div>
        <span className={cn("text-xs px-3 py-1 rounded-full", STATUS_STYLE[buyer.status])}>
          {statusLabel(buyer.status, t)}
        </span>
      </div>

      <div className="grid lg:grid-cols-3 gap-6">
        <section className="lg:col-span-2 space-y-4">
          <div className="card p-5">
            <h2 className="text-sm font-semibold text-gray-900 mb-3">{t("buyerCrm.profileDetails")}</h2>
            <dl className="grid sm:grid-cols-2 gap-x-6 gap-y-3 text-sm">
              <div>
                <dt className="text-xs text-gray-400">{t("buyerCrm.industry")}</dt>
                <dd className="text-gray-800">{buyer.industry || "—"}</dd>
              </div>
              <div>
                <dt className="text-xs text-gray-400">{t("buyerCrm.annualVolume")}</dt>
                <dd className="text-gray-800">{buyer.annual_purchase_volume || "—"}</dd>
              </div>
              <div>
                <dt className="text-xs text-gray-400">{t("buyerCrm.email")}</dt>
                <dd className="text-gray-800">{buyer.email || "—"}</dd>
              </div>
              <div>
                <dt className="text-xs text-gray-400">{t("buyerCrm.phone")}</dt>
                <dd className="text-gray-800">{buyer.phone || "—"}</dd>
              </div>
              <div>
                <dt className="text-xs text-gray-400">Telegram</dt>
                <dd className="text-gray-800">{buyer.telegram || "—"}</dd>
              </div>
              <div>
                <dt className="text-xs text-gray-400">WhatsApp</dt>
                <dd className="text-gray-800">{buyer.whatsapp || "—"}</dd>
              </div>
              <div>
                <dt className="text-xs text-gray-400">WeChat</dt>
                <dd className="text-gray-800">{buyer.wechat || "—"}</dd>
              </div>
              <div>
                <dt className="text-xs text-gray-400">{t("buyerCrm.website")}</dt>
                <dd className="text-gray-800">
                  {buyer.website ? (
                    <a href={buyer.website} target="_blank" rel="noreferrer" className="text-brand-700 hover:underline">
                      {buyer.website}
                    </a>
                  ) : "—"}
                </dd>
              </div>
              <div className="sm:col-span-2">
                <dt className="text-xs text-gray-400">{t("buyerCrm.productCategories")}</dt>
                <dd className="flex flex-wrap gap-1 mt-1">
                  {(buyer.product_categories ?? []).length > 0
                    ? buyer.product_categories.map((c) => (
                        <span key={c} className="text-[10px] px-2 py-0.5 rounded-full bg-gray-100 text-gray-700">{c}</span>
                      ))
                    : "—"}
                </dd>
              </div>
              <div className="sm:col-span-2">
                <dt className="text-xs text-gray-400">{t("buyerCrm.tags")}</dt>
                <dd className="flex flex-wrap gap-1 mt-1">
                  {(buyer.tags ?? []).length > 0
                    ? buyer.tags.map((tag) => (
                        <span key={tag} className="text-[10px] px-2 py-0.5 rounded-full bg-brand-50 text-brand-800">{tag}</span>
                      ))
                    : "—"}
                </dd>
              </div>
              {buyer.notes && (
                <div className="sm:col-span-2">
                  <dt className="text-xs text-gray-400">{t("buyerCrm.notes")}</dt>
                  <dd className="text-gray-700 whitespace-pre-wrap">{buyer.notes}</dd>
                </div>
              )}
            </dl>
          </div>

          <div className="card p-5">
            <h2 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-2">
              <Clock size={16} />
              {t("buyerCrm.activityTimeline")}
            </h2>
            {(timeline?.items ?? []).length === 0 ? (
              <EmptyState title={t("buyerCrm.noTimeline")} description={t("buyerCrm.noTimelineHint")} />
            ) : (
              <ul className="space-y-3">
                {(timeline?.items ?? []).map((item) => (
                  <li key={`${item.kind}-${item.id}`} className="border-l-2 border-brand-200 pl-3">
                    <p className="text-sm font-medium text-gray-900">{item.title}</p>
                    {item.description && <p className="text-xs text-gray-600 mt-0.5">{item.description}</p>}
                    <p className="text-[10px] text-gray-400 mt-1">
                      {format(parseISO(item.occurred_at), "MMM d, yyyy HH:mm")}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>

        <aside className="space-y-4">
          <div className="card p-4">
            <h2 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-2">
              <Link2 size={16} />
              {t("buyerCrm.linkedRecords")}
            </h2>
            {allLinks.length === 0 ? (
              <p className="text-xs text-gray-500">{t("buyerCrm.noLinks")}</p>
            ) : (
              <ul className="space-y-2 text-sm">
                {allLinks.map((link) => (
                  <li key={link.link_id} className="flex items-center justify-between gap-2">
                    <Link href={entityHref(link)} className="text-brand-700 hover:underline truncate">
                      <span className="capitalize text-[10px] text-gray-400">{link.entity_type}: </span>
                      {link.label}
                    </Link>
                    <button
                      type="button"
                      onClick={() => unlinkMutation.mutate(link.link_id)}
                      className="text-red-500 shrink-0"
                      aria-label={t("buyerCrm.removeLink")}
                    >
                      <Trash2 size={12} />
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <div className="mt-4 pt-4 border-t border-gray-100 space-y-2">
              <select className="input w-full text-sm" value={linkType} onChange={(e) => setLinkType(e.target.value as BuyerLinkedEntity["entity_type"])}>
                <option value="lead">{t("nav.leads")}</option>
                <option value="deal">{t("nav.deals")}</option>
                <option value="customer">{t("nav.customers")}</option>
                <option value="proposal">{t("nav.proposals")}</option>
              </select>
              <select className="input w-full text-sm" value={linkEntityId} onChange={(e) => setLinkEntityId(e.target.value)}>
                <option value="">{t("buyerCrm.selectRecord")}</option>
                {linkOptions.map((opt) => (
                  <option key={opt.id} value={opt.id}>{opt.label}</option>
                ))}
              </select>
              <button
                type="button"
                className="btn-secondary w-full text-sm"
                disabled={!linkEntityId || linkMutation.isPending}
                onClick={() => linkMutation.mutate()}
              >
                {linkMutation.isPending ? <Loader2 size={14} className="animate-spin mx-auto" /> : t("buyerCrm.addLink")}
              </button>
            </div>
          </div>

          <div className="card p-4">
            <RelatedEntitiesPanel entityType="buyer" entityId={buyerId} />
          </div>

          <div className="card p-4">
            <h2 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-2">
              <MessageSquare size={16} />
              {t("buyerCrm.buyerNotes")}
            </h2>
            <textarea
              className="input w-full text-sm min-h-[80px]"
              value={noteText}
              onChange={(e) => setNoteText(e.target.value)}
              placeholder={t("buyerCrm.notePlaceholder")}
            />
            <button
              type="button"
              className="btn-primary w-full text-sm mt-2"
              disabled={!noteText.trim() || noteMutation.isPending}
              onClick={() => noteMutation.mutate()}
            >
              {noteMutation.isPending ? <Loader2 size={14} className="animate-spin mx-auto" /> : t("buyerCrm.addNote")}
            </button>
          </div>

          <div className="card p-4">
            <h2 className="text-sm font-semibold text-gray-900 mb-3">{t("buyerCrm.relationshipHistory")}</h2>
            {(statusHistory?.items ?? []).length === 0 ? (
              <p className="text-xs text-gray-500">{t("buyerCrm.noHistory")}</p>
            ) : (
              <ul className="space-y-2 text-xs">
                {(statusHistory?.items ?? []).map((entry) => (
                  <li key={entry.id} className="text-gray-700">
                    <span className="font-medium">
                      {entry.from_status ? statusLabel(entry.from_status as BuyerStatus, t) : "—"}
                      {" → "}
                      {statusLabel(entry.to_status as BuyerStatus, t)}
                    </span>
                    <p className="text-[10px] text-gray-400">{format(parseISO(entry.changed_at), "MMM d, yyyy")}</p>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}
