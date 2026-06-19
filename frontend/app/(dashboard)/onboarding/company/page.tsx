"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Loader2 } from "lucide-react";
import toast from "react-hot-toast";
import { tenantOnboardingApi, type OnboardingCompanyProfile } from "@/lib/api";
import { OnboardingLayout } from "@/components/onboarding/OnboardingLayout";

const LANGUAGE_OPTIONS = ["English", "Russian", "Chinese", "Uzbek"];

export default function OnboardingCompanyPage() {
  const qc = useQueryClient();
  const { data: dashboard } = useQuery({
    queryKey: ["tenant-onboarding"],
    queryFn: () => tenantOnboardingApi.dashboard().then((r) => r.data),
  });

  const [form, setForm] = useState<OnboardingCompanyProfile>({
    company_name: "",
    industry: "",
    country: "",
    city: "",
    website: "",
    contact_person: "",
    email: "",
    phone: "",
    preferred_languages: ["English", "Russian"],
  });

  const save = useMutation({
    mutationFn: () => tenantOnboardingApi.saveCompany(form).then((r) => r.data),
    onSuccess: (res) => {
      qc.setQueryData(["tenant-onboarding"], res.progress);
      toast.success("Company profile saved");
    },
    onError: () => toast.error("Could not save profile"),
  });

  function toggleLanguage(lang: string) {
    setForm((prev) => {
      const langs = prev.preferred_languages ?? [];
      return {
        ...prev,
        preferred_languages: langs.includes(lang)
          ? langs.filter((l) => l !== lang)
          : [...langs, lang],
      };
    });
  }

  return (
    <OnboardingLayout
      title="Company profile"
      subtitle="Tell buyers who you are — this powers your catalog and outreach."
      contextStep="company"
    >
      <form
        className="space-y-5 max-w-xl"
        onSubmit={(e) => {
          e.preventDefault();
          if (!form.company_name.trim()) {
            toast.error("Company name is required");
            return;
          }
          save.mutate();
        }}
      >
        <Field label="Company name *" value={form.company_name} onChange={(v) => setForm({ ...form, company_name: v })} />
        <div className="grid sm:grid-cols-2 gap-4">
          <Field label="Industry" value={form.industry ?? ""} onChange={(v) => setForm({ ...form, industry: v })} />
          <Field label="Country" value={form.country ?? ""} onChange={(v) => setForm({ ...form, country: v })} />
        </div>
        <div className="grid sm:grid-cols-2 gap-4">
          <Field label="City" value={form.city ?? ""} onChange={(v) => setForm({ ...form, city: v })} />
          <Field label="Website" value={form.website ?? ""} onChange={(v) => setForm({ ...form, website: v })} />
        </div>
        <Field label="Contact person" value={form.contact_person ?? ""} onChange={(v) => setForm({ ...form, contact_person: v })} />
        <div className="grid sm:grid-cols-2 gap-4">
          <Field label="Email" value={form.email ?? ""} onChange={(v) => setForm({ ...form, email: v })} type="email" />
          <Field label="Phone" value={form.phone ?? ""} onChange={(v) => setForm({ ...form, phone: v })} />
        </div>

        <div>
          <p className="text-sm font-medium text-gray-700 mb-2">Preferred languages</p>
          <div className="flex flex-wrap gap-2">
            {LANGUAGE_OPTIONS.map((lang) => (
              <button
                key={lang}
                type="button"
                onClick={() => toggleLanguage(lang)}
                className={`px-3 py-1 rounded-full text-sm border ${
                  form.preferred_languages?.includes(lang)
                    ? "bg-brand-50 border-brand-300 text-brand-800"
                    : "border-slate-200 text-gray-600"
                }`}
              >
                {lang}
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-wrap gap-3 pt-2">
          <button
            type="submit"
            disabled={save.isPending}
            className="inline-flex items-center gap-2 rounded-lg bg-brand-600 text-white font-medium px-5 py-2.5 hover:bg-brand-700 disabled:opacity-50"
          >
            {save.isPending ? <Loader2 size={16} className="animate-spin" /> : null}
            Save & continue
          </button>
          {dashboard?.steps.find((s) => s.id === "company_profile")?.completed ? (
            <Link href="/onboarding/channels" className="inline-flex items-center gap-2 text-sm text-brand-600 font-medium py-2.5">
              Next: Channels <ArrowRight size={16} />
            </Link>
          ) : null}
        </div>
      </form>
    </OnboardingLayout>
  );
}

function Field({
  label,
  value,
  onChange,
  type = "text",
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
}) {
  return (
    <label className="block">
      <span className="text-sm font-medium text-gray-700">{label}</span>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500/30"
      />
    </label>
  );
}
