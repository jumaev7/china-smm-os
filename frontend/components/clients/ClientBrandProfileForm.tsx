"use client";
import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { clientsApi, Client, PreferredOutputLang, ToneOfVoice } from "@/lib/api";
import toast from "react-hot-toast";

const TONE_OPTIONS: { value: ToneOfVoice; label: string }[] = [
  { value: "formal", label: "Formal" },
  { value: "friendly", label: "Friendly" },
  { value: "premium", label: "Premium" },
  { value: "energetic", label: "Energetic" },
  { value: "technical", label: "Technical" },
];

const LANG_OPTIONS: { value: PreferredOutputLang; label: string }[] = [
  { value: "ru", label: "RU" },
  { value: "uz", label: "UZ" },
  { value: "en", label: "EN" },
  { value: "cn", label: "CN Simplified" },
];

interface Props {
  client: Client;
  onSaved: () => void;
}

function brandFormFromClient(client: Client) {
  return {
    brand_name: client.brand_name ?? client.company_name ?? "",
    business_description: client.business_description ?? "",
    products_services: client.products_services ?? "",
    target_audience: client.target_audience ?? "",
    tone_of_voice: (client.tone_of_voice ?? "friendly") as ToneOfVoice,
    preferred_languages: (client.preferred_languages?.length
      ? client.preferred_languages
      : ["ru", "uz", "en"]) as PreferredOutputLang[],
    cta_phone: client.cta_phone ?? "",
    cta_telegram: client.cta_telegram ?? "",
    cta_website: client.cta_website ?? "",
    cta_address: client.cta_address ?? "",
    words_to_avoid: client.words_to_avoid ?? "",
    hashtag_preferences: client.hashtag_preferences ?? "",
    logo_url: client.logo_url ?? "",
  };
}

export function ClientBrandProfileForm({ client, onSaved }: Props) {
  const [form, setForm] = useState(() => brandFormFromClient(client));

  useEffect(() => {
    setForm(brandFormFromClient(client));
  }, [client]);

  const mutation = useMutation({
    mutationFn: () =>
      clientsApi.update(client.id, {
        ...form,
        brand_name: form.brand_name || null,
        business_description: form.business_description || null,
        products_services: form.products_services || null,
        target_audience: form.target_audience || null,
        cta_phone: form.cta_phone || null,
        cta_telegram: form.cta_telegram || null,
        cta_website: form.cta_website || null,
        cta_address: form.cta_address || null,
        words_to_avoid: form.words_to_avoid || null,
        hashtag_preferences: form.hashtag_preferences || null,
        logo_url: form.logo_url || null,
      }),
    onSuccess: () => {
      toast.success("Brand profile saved");
      onSaved();
    },
    onError: () => toast.error("Failed to save brand profile"),
  });

  const set =
    (key: keyof typeof form) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
      setForm((prev) => ({ ...prev, [key]: e.target.value }));

  const toggleLang = (lang: PreferredOutputLang) => {
    setForm((prev) => {
      const selected = new Set(prev.preferred_languages);
      if (selected.has(lang)) selected.delete(lang);
      else selected.add(lang);
      return {
        ...prev,
        preferred_languages: LANG_OPTIONS.map((o) => o.value).filter((v) =>
          selected.has(v)
        ),
      };
    });
  };

  return (
    <div className="card p-5 mb-5">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-sm font-semibold text-gray-900">Brand profile</h2>
          <p className="text-xs text-gray-500 mt-0.5">
            Used by AI for captions, subtitles context, and post text.
          </p>
        </div>
        <button
          type="button"
          className="btn-primary text-xs"
          onClick={() => mutation.mutate()}
          disabled={mutation.isPending || form.preferred_languages.length === 0}
        >
          {mutation.isPending ? "Saving…" : "Save brand profile"}
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label className="label">Brand name</label>
          <input className="input" value={form.brand_name} onChange={set("brand_name")} placeholder="Public brand name" />
        </div>
        <div>
          <label className="label">Tone of voice</label>
          <select className="input" value={form.tone_of_voice} onChange={set("tone_of_voice")}>
            {TONE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>
        <div className="md:col-span-2">
          <label className="label">Business description</label>
          <textarea className="input resize-none" rows={2} value={form.business_description} onChange={set("business_description")} placeholder="What the company does and why customers choose it" />
        </div>
        <div>
          <label className="label">Products / services</label>
          <textarea className="input resize-none" rows={2} value={form.products_services} onChange={set("products_services")} placeholder="Key offers, models, packages" />
        </div>
        <div>
          <label className="label">Target audience</label>
          <textarea className="input resize-none" rows={2} value={form.target_audience} onChange={set("target_audience")} placeholder="Who you speak to in Uzbekistan" />
        </div>
        <div className="md:col-span-2">
          <label className="label">Preferred languages</label>
          <div className="flex flex-wrap gap-2">
            {LANG_OPTIONS.map((o) => {
              const active = form.preferred_languages.includes(o.value);
              return (
                <button
                  key={o.value}
                  type="button"
                  onClick={() => toggleLang(o.value)}
                  className={
                    active
                      ? "text-xs px-2.5 py-1 rounded-full bg-brand-100 text-brand-800 border border-brand-200"
                      : "text-xs px-2.5 py-1 rounded-full bg-gray-50 text-gray-500 border border-gray-200"
                  }
                >
                  {o.label}
                </button>
              );
            })}
          </div>
        </div>
        <div>
          <label className="label">CTA phone</label>
          <input className="input" value={form.cta_phone} onChange={set("cta_phone")} placeholder="+998 …" />
        </div>
        <div>
          <label className="label">CTA Telegram</label>
          <input className="input" value={form.cta_telegram} onChange={set("cta_telegram")} placeholder="@username" />
        </div>
        <div>
          <label className="label">CTA website</label>
          <input className="input" value={form.cta_website} onChange={set("cta_website")} placeholder="https://…" />
        </div>
        <div>
          <label className="label">CTA address</label>
          <input className="input" value={form.cta_address} onChange={set("cta_address")} placeholder="Tashkent, …" />
        </div>
        <div>
          <label className="label">Words to avoid</label>
          <textarea className="input resize-none" rows={2} value={form.words_to_avoid} onChange={set("words_to_avoid")} placeholder="Comma-separated words/phrases" />
        </div>
        <div>
          <label className="label">Hashtag preferences</label>
          <textarea className="input resize-none" rows={2} value={form.hashtag_preferences} onChange={set("hashtag_preferences")} placeholder="#brand #Toshkent …" />
        </div>
        <div className="md:col-span-2">
          <label className="label">Logo URL</label>
          <input className="input" value={form.logo_url} onChange={set("logo_url")} placeholder="https://…/logo.png" />
          {form.logo_url ? (
            <div className="mt-2 flex items-center gap-3">
              <div className="w-12 h-12 rounded border border-gray-200 bg-gray-50 overflow-hidden flex items-center justify-center">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={form.logo_url} alt="Logo preview" className="max-w-full max-h-full object-contain" />
              </div>
              <span className="text-xs text-gray-400">Logo preview</span>
            </div>
          ) : (
            <p className="text-xs text-gray-400 mt-1">Paste a logo URL for reference (upload coming later).</p>
          )}
        </div>
      </div>
    </div>
  );
}
