"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Loader2, Send } from "lucide-react";
import { publicLandingApi } from "@/lib/api";

export default function PublicLandingPage() {
  const { slug } = useParams<{ slug: string }>();
  const [submitted, setSubmitted] = useState(false);
  const [form, setForm] = useState({
    name: "",
    company: "",
    phone: "",
    email: "",
    telegram: "",
    whatsapp: "",
    wechat: "",
    country: "",
    message: "",
  });

  const { data: page, isLoading, error } = useQuery({
    queryKey: ["public-landing", slug],
    queryFn: () => publicLandingApi.get(slug!).then((r) => r.data),
    enabled: !!slug,
  });

  const submitMutation = useMutation({
    mutationFn: () => publicLandingApi.submitLead(slug!, form),
    onSuccess: () => setSubmitted(true),
  });

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <Loader2 className="animate-spin text-brand-600" size={28} />
      </div>
    );
  }

  if (error || !page) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 p-6">
        <div className="card p-8 max-w-md text-center">
          <p className="text-gray-700 font-medium">Page not found</p>
          <p className="text-sm text-gray-500 mt-2">This landing page may be unavailable or unpublished.</p>
        </div>
      </div>
    );
  }

  if (submitted) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 p-6">
        <div className="card p-8 max-w-md text-center">
          <p className="text-lg font-semibold text-gray-900">Thank you. We will contact you soon.</p>
        </div>
      </div>
    );
  }

  const set =
    (key: keyof typeof form) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
      setForm((f) => ({ ...f, [key]: e.target.value }));

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-2xl mx-auto px-4 py-10 space-y-8">
        {page.hero_image_url && (
          <img
            src={page.hero_image_url}
            alt=""
            className="w-full h-48 object-cover rounded-xl border border-gray-200"
          />
        )}

        <header className="space-y-2 text-center">
          <h1 className="text-2xl sm:text-3xl font-bold text-gray-900">{page.title}</h1>
          {page.subtitle && <p className="text-gray-600">{page.subtitle}</p>}
          {page.description && (
            <p className="text-sm text-gray-500 whitespace-pre-wrap pt-2">{page.description}</p>
          )}
        </header>

        {(page.product || page.campaign) && (
          <div className="card p-4 space-y-3">
            {page.product && (
              <div>
                <p className="text-xs uppercase tracking-wide text-gray-400">Product</p>
                <p className="font-medium text-gray-900">{page.product.name}</p>
                {page.product.category && (
                  <p className="text-sm text-gray-500">{page.product.category}</p>
                )}
                {page.product.description && (
                  <p className="text-sm text-gray-600 mt-1">{page.product.description}</p>
                )}
              </div>
            )}
            {page.campaign && (
              <div>
                <p className="text-xs uppercase tracking-wide text-gray-400">Campaign</p>
                <p className="font-medium text-gray-900">{page.campaign.name}</p>
                {page.campaign.objective && (
                  <p className="text-sm text-gray-500">{page.campaign.objective}</p>
                )}
              </div>
            )}
          </div>
        )}

        <form
          className="card p-6 space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (!form.name.trim()) return;
            submitMutation.mutate();
          }}
        >
          <h2 className="text-sm font-semibold text-gray-900">Contact us</h2>

          <div className="grid sm:grid-cols-2 gap-4">
            <div>
              <label className="label">Name *</label>
              <input className="input" required value={form.name} onChange={set("name")} />
            </div>
            <div>
              <label className="label">Company</label>
              <input className="input" value={form.company} onChange={set("company")} />
            </div>
            <div>
              <label className="label">Phone</label>
              <input className="input" type="tel" value={form.phone} onChange={set("phone")} />
            </div>
            <div>
              <label className="label">Email</label>
              <input className="input" type="email" value={form.email} onChange={set("email")} />
            </div>
            <div>
              <label className="label">Telegram</label>
              <input className="input" value={form.telegram} onChange={set("telegram")} placeholder="@username" />
            </div>
            <div>
              <label className="label">WhatsApp</label>
              <input className="input" value={form.whatsapp} onChange={set("whatsapp")} />
            </div>
            <div>
              <label className="label">WeChat</label>
              <input className="input" value={form.wechat} onChange={set("wechat")} />
            </div>
            <div>
              <label className="label">Country</label>
              <input className="input" value={form.country} onChange={set("country")} />
            </div>
          </div>

          <div>
            <label className="label">Message</label>
            <textarea className="input min-h-[100px]" value={form.message} onChange={set("message")} />
          </div>

          {submitMutation.isError && (
            <p className="text-sm text-red-600">
              {(submitMutation.error as any)?.response?.data?.detail || "Could not submit. Please try again."}
            </p>
          )}

          <button
            type="submit"
            className="btn-primary w-full flex items-center justify-center gap-2"
            disabled={submitMutation.isPending || !form.name.trim()}
          >
            {submitMutation.isPending ? (
              <Loader2 size={16} className="animate-spin" />
            ) : (
              <>
                <Send size={16} />
                {page.cta_text || "Get in touch"}
              </>
            )}
          </button>
        </form>
      </div>
    </div>
  );
}
