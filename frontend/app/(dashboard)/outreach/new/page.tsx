"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowLeft, Loader2, Send } from "lucide-react";
import toast from "react-hot-toast";
import {
  crmApi,
  outreachApi,
  productsApi,
  OutreachChannel,
  OutreachStyle,
  OutreachType,
  normalizeList,
} from "@/lib/api";
import { LoadingState } from "@/components/ui/PageStates";

const CHANNELS: OutreachChannel[] = ["email", "whatsapp", "wechat", "linkedin"];
const TYPES: OutreachType[] = ["first_contact", "follow_up", "proposal_follow_up", "re_engagement"];
const STYLES: OutreachStyle[] = ["formal", "friendly", "executive", "distributor"];
const LANGUAGES = ["en", "ru", "zh", "uz"];

function GenerateOutreachForm() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [productId, setProductId] = useState("");
  const [proposalId, setProposalId] = useState("");
  const [leadId, setLeadId] = useState("");
  const [buyerName, setBuyerName] = useState("");
  const [buyerCompany, setBuyerCompany] = useState("");
  const [country, setCountry] = useState("");
  const [language, setLanguage] = useState("en");
  const [channel, setChannel] = useState<OutreachChannel>("email");
  const [outreachType, setOutreachType] = useState<OutreachType>("first_contact");
  const [style, setStyle] = useState<OutreachStyle>("formal");

  useEffect(() => {
    const p = searchParams.get("product_id");
    const pr = searchParams.get("proposal_id");
    const l = searchParams.get("lead_id");
    const bn = searchParams.get("buyer_name");
    const bc = searchParams.get("buyer_company");
    const c = searchParams.get("country");
    const ch = searchParams.get("channel");
    const ot = searchParams.get("outreach_type");
    if (p) setProductId(p);
    if (pr) setProposalId(pr);
    if (l) setLeadId(l);
    if (bn) setBuyerName(bn);
    if (bc) setBuyerCompany(bc);
    if (c) setCountry(c);
    if (ch && CHANNELS.includes(ch as OutreachChannel)) setChannel(ch as OutreachChannel);
    if (ot && TYPES.includes(ot as OutreachType)) setOutreachType(ot as OutreachType);
  }, [searchParams]);

  const { data: products } = useQuery({
    queryKey: ["products-outreach"],
    queryFn: () => productsApi.list({ limit: 200 }).then((r) => r.data),
  });

  const { data: leads } = useQuery({
    queryKey: ["crm-leads-outreach"],
    queryFn: () => crmApi.listLeads({ limit: 200 }).then((r) => r.data),
  });

  const generateMutation = useMutation({
    mutationFn: () =>
      outreachApi
        .generate({
          product_id: productId,
          proposal_id: proposalId || null,
          lead_id: leadId || null,
          buyer_name: buyerName.trim() || null,
          buyer_company: buyerCompany.trim() || null,
          country: country.trim(),
          language,
          channel,
          outreach_type: outreachType,
          style,
        })
        .then((r) => r.data),
    onSuccess: (msg) => {
      toast.success("Outreach draft generated — review before sending");
      router.push(`/outreach/${msg.id}`);
    },
    onError: (err: Error) => toast.error(err.message || "Generation failed"),
  });

  return (
    <div className="p-6 max-w-xl mx-auto space-y-5">
      <div>
        <Link href="/outreach" className="text-xs text-gray-500 hover:text-gray-800 flex items-center gap-1 mb-2">
          <ArrowLeft size={12} />
          All outreach
        </Link>
        <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
          <Send size={20} className="text-indigo-600" />
          Generate outreach
        </h1>
        <p className="text-sm text-gray-500 mt-1">Draft only — copy and send manually</p>
      </div>

      <div className="card p-4 space-y-3">
        <label className="block space-y-1 text-sm">
          <span className="text-gray-700">Product *</span>
          <select className="input w-full" value={productId} onChange={(e) => setProductId(e.target.value)} required>
            <option value="">Select product</option>
            {normalizeList(products).map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} · {p.company_name ?? p.client_id}
              </option>
            ))}
          </select>
        </label>

        <label className="block space-y-1 text-sm">
          <span className="text-gray-700">CRM lead (optional)</span>
          <select className="input w-full" value={leadId} onChange={(e) => setLeadId(e.target.value)}>
            <option value="">None</option>
            {normalizeList(leads).map((l) => (
              <option key={l.id} value={l.id}>
                {l.name} · {l.company ?? "—"}
              </option>
            ))}
          </select>
        </label>

        <div className="grid sm:grid-cols-2 gap-3">
          <label className="block space-y-1 text-sm">
            <span className="text-gray-700">Buyer name</span>
            <input className="input w-full" value={buyerName} onChange={(e) => setBuyerName(e.target.value)} />
          </label>
          <label className="block space-y-1 text-sm">
            <span className="text-gray-700">Company</span>
            <input className="input w-full" value={buyerCompany} onChange={(e) => setBuyerCompany(e.target.value)} />
          </label>
        </div>

        <label className="block space-y-1 text-sm">
          <span className="text-gray-700">Country *</span>
          <input className="input w-full" value={country} onChange={(e) => setCountry(e.target.value)} required />
        </label>

        <div className="grid sm:grid-cols-2 gap-3">
          <label className="block space-y-1 text-sm">
            <span className="text-gray-700">Channel</span>
            <select className="input w-full" value={channel} onChange={(e) => setChannel(e.target.value as OutreachChannel)}>
              {CHANNELS.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </label>
          <label className="block space-y-1 text-sm">
            <span className="text-gray-700">Type</span>
            <select className="input w-full" value={outreachType} onChange={(e) => setOutreachType(e.target.value as OutreachType)}>
              {TYPES.map((t) => (
                <option key={t} value={t}>{t.replace(/_/g, " ")}</option>
              ))}
            </select>
          </label>
        </div>

        <div className="grid sm:grid-cols-2 gap-3">
          <label className="block space-y-1 text-sm">
            <span className="text-gray-700">Language</span>
            <select className="input w-full" value={language} onChange={(e) => setLanguage(e.target.value)}>
              {LANGUAGES.map((l) => (
                <option key={l} value={l}>{l}</option>
              ))}
            </select>
          </label>
          <label className="block space-y-1 text-sm">
            <span className="text-gray-700">Style</span>
            <select className="input w-full" value={style} onChange={(e) => setStyle(e.target.value as OutreachStyle)}>
              {STYLES.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </label>
        </div>

        <button
          type="button"
          disabled={!productId || !country.trim() || generateMutation.isPending}
          onClick={() => generateMutation.mutate()}
          className="btn-primary w-full flex items-center justify-center gap-2 disabled:opacity-50"
        >
          {generateMutation.isPending ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
          Generate draft
        </button>
      </div>
    </div>
  );
}

export default function OutreachNewPage() {
  return (
    <Suspense fallback={<LoadingState message="Loading…" className="min-h-[40vh]" />}>
      <GenerateOutreachForm />
    </Suspense>
  );
}
