"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation } from "@tanstack/react-query";
import { ArrowLeft, Loader2, Sparkles } from "lucide-react";
import toast from "react-hot-toast";
import { clientsApi, Client, OutreachChannel, salesPlaybooksApi, normalizeList } from "@/lib/api";
import { useQuery } from "@tanstack/react-query";

const CHANNELS: OutreachChannel[] = ["email", "whatsapp", "wechat", "linkedin"];
const BUYER_TYPES = ["distributor", "retailer", "importer", "manufacturer", "agent"];
const CATEGORIES = ["food", "textiles", "machinery", "chemicals", "electronics", "agriculture"];

export default function GeneratePlaybookPage() {
  const router = useRouter();
  const [clientId, setClientId] = useState("");
  const [productCategory, setProductCategory] = useState("food");
  const [buyerType, setBuyerType] = useState("distributor");
  const [country, setCountry] = useState("Uzbekistan");
  const [language, setLanguage] = useState("en");
  const [channel, setChannel] = useState<OutreachChannel>("email");
  const [name, setName] = useState("");

  const { data: clients } = useQuery({
    queryKey: ["clients-list"],
    queryFn: () => clientsApi.list({ limit: 100 }).then((r) => r.data),
  });
  const clientOptions = normalizeList<Client>(clients);

  const generateMutation = useMutation({
    mutationFn: () =>
      salesPlaybooksApi
        .generate({
          client_id: clientId || null,
          product_category: productCategory,
          buyer_type: buyerType,
          country,
          language,
          channel,
          name: name.trim() || null,
        })
        .then((r) => r.data),
    onSuccess: (data) => {
      toast.success(data.demo_mode ? "Playbook generated (demo mode)" : "Playbook generated");
      router.push(`/sales-playbooks/${data.id}`);
    },
    onError: (err: Error) => toast.error(err.message || "Generation failed"),
  });

  return (
    <div className="p-6 max-w-xl mx-auto space-y-5">
      <div>
        <Link
          href="/sales-playbooks"
          className="text-xs text-gray-500 hover:text-gray-800 flex items-center gap-1 mb-2"
        >
          <ArrowLeft size={12} />
          All playbooks
        </Link>
        <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
          <Sparkles size={20} className="text-violet-600" />
          Generate Sales Playbook
        </h1>
        <p className="text-sm text-gray-500 mt-1">
          AI creates a 3–5 step draft playbook — review before activating
        </p>
      </div>

      <div className="card p-4 space-y-4">
        <div>
          <label className="text-xs text-gray-500">Client (optional)</label>
          <select className="input w-full mt-1 text-sm" value={clientId} onChange={(e) => setClientId(e.target.value)}>
            <option value="">Global template</option>
            {clientOptions.map((c) => (
              <option key={c.id} value={c.id}>{c.company_name}</option>
            ))}
          </select>
        </div>

        <div className="grid sm:grid-cols-2 gap-3">
          <div>
            <label className="text-xs text-gray-500">Product category</label>
            <select
              className="input w-full mt-1 text-sm"
              value={productCategory}
              onChange={(e) => setProductCategory(e.target.value)}
            >
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-500">Buyer type</label>
            <select
              className="input w-full mt-1 text-sm"
              value={buyerType}
              onChange={(e) => setBuyerType(e.target.value)}
            >
              {BUYER_TYPES.map((b) => (
                <option key={b} value={b}>{b}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-500">Country</label>
            <input className="input w-full mt-1 text-sm" value={country} onChange={(e) => setCountry(e.target.value)} />
          </div>
          <div>
            <label className="text-xs text-gray-500">Language</label>
            <select className="input w-full mt-1 text-sm" value={language} onChange={(e) => setLanguage(e.target.value)}>
              <option value="en">English</option>
              <option value="ru">Russian</option>
              <option value="uz">Uzbek</option>
              <option value="zh">Chinese</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-500">Channel</label>
            <select
              className="input w-full mt-1 text-sm"
              value={channel}
              onChange={(e) => setChannel(e.target.value as OutreachChannel)}
            >
              {CHANNELS.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-500">Name (optional)</label>
            <input className="input w-full mt-1 text-sm" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
        </div>

        <button
          type="button"
          disabled={generateMutation.isPending}
          onClick={() => generateMutation.mutate()}
          className="btn-primary w-full flex items-center justify-center gap-2"
        >
          {generateMutation.isPending ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} />}
          Generate with AI
        </button>

        <p className="text-[10px] text-amber-700 text-center">
          Draft only — applying a playbook creates outreach/proposal/task drafts, never auto-sends.
        </p>
      </div>
    </div>
  );
}
