"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Handshake, Plus, Search, ChevronRight } from "lucide-react";
import toast from "react-hot-toast";
import { partnersApi, Partner, PartnerType, PARTNER_TYPE_LABELS, normalizeList } from "@/lib/api";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";

function formatMoney(val: number | string | null | undefined): string {
  if (val == null || val === "") return "—";
  const n = typeof val === "string" ? parseFloat(val) : val;
  if (Number.isNaN(n)) return String(val);
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(n);
}

function PartnerRow({ partner }: { partner: Partner }) {
  return (
    <Link
      href={`/partners/${partner.id}`}
      className="card p-4 flex items-center justify-between gap-3 hover:ring-1 hover:ring-brand-200 transition-shadow"
    >
      <div className="min-w-0">
        <p className="text-sm font-semibold text-gray-900">{partner.name}</p>
        {(partner.company_name || partner.company) && (
          <p className="text-xs text-gray-500">{partner.company_name || partner.company}</p>
        )}
        <div className="flex flex-wrap gap-2 mt-1">
          {partner.partner_type && (
            <span className="text-[10px] text-violet-700 capitalize">
              {PARTNER_TYPE_LABELS[partner.partner_type as PartnerType] ?? partner.partner_type}
            </span>
          )}
          {partner.country && (
            <span className="text-[10px] text-gray-500">{partner.country}{partner.city ? `, ${partner.city}` : ""}</span>
          )}
        </div>
        {partner.referral_links[0] && (
          <p className="text-[10px] text-violet-600 mt-1 font-mono">
            ref: {partner.referral_links[0].code}
          </p>
        )}
      </div>
      <div className="flex items-center gap-4 shrink-0 text-right">
        <div className="hidden sm:grid grid-cols-4 gap-4 text-xs text-gray-600 tabular-nums">
          <div>
            <p className="text-[9px] text-gray-400 uppercase">Leads</p>
            <p className="font-medium text-gray-900">{partner.leads_count}</p>
          </div>
          <div>
            <p className="text-[9px] text-gray-400 uppercase">Won</p>
            <p className="font-medium text-gray-900">{partner.won_deals}</p>
          </div>
          <div>
            <p className="text-[9px] text-gray-400 uppercase">Revenue</p>
            <p className="font-medium text-gray-900">{formatMoney(partner.revenue)}</p>
          </div>
          <div>
            <p className="text-[9px] text-gray-400 uppercase">Commission</p>
            <p className="font-medium text-gray-900">{formatMoney(partner.commission)}</p>
          </div>
        </div>
        <span
          className={cn(
            "text-[10px] px-2 py-0.5 rounded-full border font-medium capitalize",
            partner.status === "active"
              ? "bg-emerald-100 text-emerald-800 border-emerald-200"
              : "bg-gray-100 text-gray-600 border-gray-200",
          )}
        >
          {partner.status}
        </span>
        <ChevronRight size={16} className="text-gray-400" />
      </div>
    </Link>
  );
}

export default function PartnersPage() {
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [search, setSearch] = useState("");
  const [country, setCountry] = useState("");
  const [partnerType, setPartnerType] = useState("");
  const [industry, setIndustry] = useState("");
  const [name, setName] = useState("");
  const [company, setCompany] = useState("");
  const [formCountry, setFormCountry] = useState("");
  const [formType, setFormType] = useState<PartnerType | "">("");
  const [referralCode, setReferralCode] = useState("");

  const { data: filters } = useQuery({
    queryKey: ["partner-filters"],
    queryFn: () => partnersApi.filters().then((r) => r.data),
  });

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["partners", search, country, partnerType, industry],
    queryFn: () =>
      partnersApi
        .list({
          search: search || undefined,
          country: country || undefined,
          partner_type: partnerType || undefined,
          industry: industry || undefined,
          limit: 200,
        })
        .then((r) => r.data),
  });

  const createMutation = useMutation({
    mutationFn: () =>
      partnersApi
        .create({
          name: name.trim(),
          company_name: company.trim() || null,
          country: formCountry.trim() || null,
          partner_type: formType || null,
          referral_code: referralCode.trim() || undefined,
        })
        .then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["partners"] });
      queryClient.invalidateQueries({ queryKey: ["partner-filters"] });
      setShowForm(false);
      setName("");
      setCompany("");
      setFormCountry("");
      setFormType("");
      setReferralCode("");
      toast.success("Partner created");
    },
    onError: (err: Error) => toast.error(err.message || "Failed to create partner"),
  });

  const partners = normalizeList<Partner>(data);

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
            <Handshake size={22} className="text-violet-600" />
            Partner Directory
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Distributors, dealers, and agents — connect products, leads, and factories
          </p>
        </div>
        <button
          type="button"
          onClick={() => setShowForm(!showForm)}
          className="btn-primary text-sm flex items-center gap-1.5"
        >
          <Plus size={14} />
          Add partner
        </button>
      </div>

      <div className="flex flex-wrap gap-3">
        <div className="relative flex-1 min-w-[200px]">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            className="input pl-9 w-full"
            placeholder="Search partners…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <select className="input text-sm min-w-[130px]" value={country} onChange={(e) => setCountry(e.target.value)}>
          <option value="">All countries</option>
          {(filters?.countries ?? []).map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
        <select className="input text-sm min-w-[140px]" value={partnerType} onChange={(e) => setPartnerType(e.target.value)}>
          <option value="">All types</option>
          {(filters?.partner_types ?? Object.keys(PARTNER_TYPE_LABELS)).map((t) => (
            <option key={t} value={t}>
              {PARTNER_TYPE_LABELS[t as PartnerType] ?? t}
            </option>
          ))}
        </select>
        <select className="input text-sm min-w-[130px]" value={industry} onChange={(e) => setIndustry(e.target.value)}>
          <option value="">All industries</option>
          {(filters?.industries ?? []).map((i) => (
            <option key={i} value={i}>{i}</option>
          ))}
        </select>
      </div>

      {showForm && (
        <div className="card p-4 space-y-3">
          <p className="text-sm font-semibold text-gray-900">New partner</p>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-2">
            <input className="input text-sm" placeholder="Contact name *" value={name} onChange={(e) => setName(e.target.value)} />
            <input className="input text-sm" placeholder="Company name" value={company} onChange={(e) => setCompany(e.target.value)} />
            <input className="input text-sm" placeholder="Country" value={formCountry} onChange={(e) => setFormCountry(e.target.value)} />
            <select className="input text-sm" value={formType} onChange={(e) => setFormType(e.target.value as PartnerType | "")}>
              <option value="">Partner type</option>
              {Object.entries(PARTNER_TYPE_LABELS).map(([k, label]) => (
                <option key={k} value={k}>{label}</option>
              ))}
            </select>
            <input className="input text-sm font-mono" placeholder="Referral code (optional)" value={referralCode} onChange={(e) => setReferralCode(e.target.value)} />
          </div>
          <button
            type="button"
            disabled={!name.trim() || createMutation.isPending}
            onClick={() => createMutation.mutate()}
            className="text-sm px-4 py-2 rounded-lg bg-brand-600 text-white disabled:opacity-50"
          >
            {createMutation.isPending ? "Creating…" : "Create partner"}
          </button>
        </div>
      )}

      {isLoading && <LoadingState message="Loading partners…" />}
      {isError && (
        <ErrorState
          message={error instanceof Error ? error.message : "Failed to load partners"}
          onRetry={() => refetch()}
        />
      )}
      {!isLoading && !isError && partners.length === 0 && (
        <EmptyState
          title="No partners yet"
          description="Add distributors, dealers, or agents to build your partner network."
        />
      )}
      <div className="space-y-2">
        {partners.map((p) => (
          <PartnerRow key={p.id} partner={p} />
        ))}
      </div>
    </div>
  );
}
