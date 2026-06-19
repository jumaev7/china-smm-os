"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Building2, CheckCircle2, FileText, Globe2, Loader2, Send, Users } from "lucide-react";
import toast from "react-hot-toast";
import { factoryPartnerPortalApi, FactoryPartnerApplication } from "@/lib/api";

const COMMISSION_OPTIONS = [
  { value: "revenue_share", label: "Revenue share" },
  { value: "fixed_commission", label: "Fixed commission" },
  { value: "referral_fee", label: "Referral fee" },
  { value: "negotiable", label: "Negotiable" },
];

const COOPERATION_TERMS = `By applying, you agree to cooperate with our export sales team under manual review.
We do not auto-approve applications, auto-publish content, or initiate sales outreach on your behalf.
Commission terms are confirmed individually after approval.`;

function parseList(value: string): string[] {
  return value
    .split(/[,;\n]/)
    .map((s) => s.trim())
    .filter(Boolean);
}

export default function FactoryApplyPage() {
  const [step, setStep] = useState(1);
  const [applicationId, setApplicationId] = useState<string | null>(null);
  const [termsAccepted, setTermsAccepted] = useState(false);
  const [companyName, setCompanyName] = useState("");
  const [country, setCountry] = useState("China");
  const [city, setCity] = useState("");
  const [industry, setIndustry] = useState("");
  const [companyDescription, setCompanyDescription] = useState("");
  const [contactName, setContactName] = useState("");
  const [contactPhone, setContactPhone] = useState("");
  const [contactWechat, setContactWechat] = useState("");
  const [contactWhatsapp, setContactWhatsapp] = useState("");
  const [contactEmail, setContactEmail] = useState("");
  const [website, setWebsite] = useState("");
  const [productCategories, setProductCategories] = useState("");
  const [targetMarkets, setTargetMarkets] = useState("");
  const [commissionModel, setCommissionModel] = useState("negotiable");
  const [submitted, setSubmitted] = useState(false);

  const buildPayload = () => ({
    company_name: companyName.trim(),
    country: country || undefined,
    city: city || undefined,
    industry: industry || undefined,
    company_description: companyDescription || undefined,
    contact_name: contactName || undefined,
    contact_phone: contactPhone || undefined,
    contact_wechat: contactWechat || undefined,
    contact_whatsapp: contactWhatsapp || undefined,
    contact_email: contactEmail || undefined,
    website: website || undefined,
    product_categories: parseList(productCategories),
    target_markets: parseList(targetMarkets),
    commission_model: commissionModel,
    cooperation_terms_accepted: termsAccepted,
    documents: [],
  });

  const applyMutation = useMutation({
    mutationFn: () => factoryPartnerPortalApi.apply(buildPayload()).then((r) => r.data),
    onSuccess: (data: FactoryPartnerApplication) => {
      setApplicationId(data.id);
      toast.success("Draft saved");
    },
    onError: (e: Error) => toast.error(e.message || "Could not save application"),
  });

  const submitMutation = useMutation({
    mutationFn: async () => {
      let id = applicationId;
      if (!id) {
        const created = await factoryPartnerPortalApi.apply(buildPayload()).then((r) => r.data);
        id = created.id;
        setApplicationId(id);
      } else {
        await factoryPartnerPortalApi.update(id, buildPayload());
      }
      return factoryPartnerPortalApi.submit(id!).then((r) => r.data);
    },
    onSuccess: () => {
      setSubmitted(true);
      toast.success("Application submitted for review");
    },
    onError: (e: Error) => toast.error(e.message || "Submit failed"),
  });

  if (submitted) {
    return (
      <div className="min-h-screen bg-gradient-to-b from-slate-50 to-white flex items-center justify-center p-6">
        <div className="max-w-md text-center space-y-4">
          <CheckCircle2 className="mx-auto text-emerald-600" size={48} />
          <h1 className="text-xl font-semibold text-gray-900">Application submitted</h1>
          <p className="text-sm text-gray-600">
            Thank you. Our team will review your factory application manually. You will be contacted
            after approval — no automatic publishing or sales actions.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-50 to-white">
      <div className="max-w-2xl mx-auto px-4 py-10 space-y-8">
        <header className="text-center space-y-2">
          <Building2 className="mx-auto text-indigo-600" size={36} />
          <h1 className="text-2xl font-semibold text-gray-900">Factory Partner Application</h1>
          <p className="text-sm text-gray-500">
            Chinese factories & exporters — self-service onboarding portal
          </p>
        </header>

        <div className="flex justify-center gap-1 text-[10px] text-gray-400">
          {[1, 2, 3, 4, 5, 6, 7, 8].map((n) => (
            <span
              key={n}
              className={`px-2 py-0.5 rounded ${step === n ? "bg-indigo-100 text-indigo-700 font-medium" : ""}`}
            >
              {n}
            </span>
          ))}
        </div>

        {step === 1 && (
          <section className="card p-6 space-y-4">
            <h2 className="font-semibold text-gray-900 flex items-center gap-2">
              <FileText size={18} /> 1. Cooperation terms
            </h2>
            <pre className="text-xs text-gray-600 whitespace-pre-wrap bg-gray-50 rounded-lg p-4 border">
              {COOPERATION_TERMS}
            </pre>
            <label className="flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                checked={termsAccepted}
                onChange={(e) => setTermsAccepted(e.target.checked)}
                className="mt-1"
              />
              <span>I accept the cooperation terms</span>
            </label>
            <button
              type="button"
              className="btn-primary w-full"
              disabled={!termsAccepted}
              onClick={() => setStep(2)}
            >
              Continue
            </button>
          </section>
        )}

        {step === 2 && (
          <section className="card p-6 space-y-4">
            <h2 className="font-semibold text-gray-900">2. Company information</h2>
            <div>
              <label className="label">Company name *</label>
              <input className="input" value={companyName} onChange={(e) => setCompanyName(e.target.value)} />
            </div>
            <div className="grid sm:grid-cols-2 gap-3">
              <div>
                <label className="label">Country</label>
                <input className="input" value={country} onChange={(e) => setCountry(e.target.value)} />
              </div>
              <div>
                <label className="label">City</label>
                <input className="input" value={city} onChange={(e) => setCity(e.target.value)} />
              </div>
            </div>
            <div>
              <label className="label">Industry</label>
              <input className="input" value={industry} onChange={(e) => setIndustry(e.target.value)} placeholder="e.g. manufacturing, technology" />
            </div>
            <div>
              <label className="label">Company description</label>
              <textarea className="input min-h-[100px]" value={companyDescription} onChange={(e) => setCompanyDescription(e.target.value)} />
            </div>
            <div className="flex gap-2">
              <button type="button" className="btn-secondary flex-1" onClick={() => setStep(1)}>Back</button>
              <button type="button" className="btn-primary flex-1" disabled={!companyName.trim()} onClick={() => setStep(3)}>Continue</button>
            </div>
          </section>
        )}

        {step === 3 && (
          <section className="card p-6 space-y-4">
            <h2 className="font-semibold text-gray-900 flex items-center gap-2">
              <Users size={18} /> 3. Contact information
            </h2>
            <div>
              <label className="label">Contact name</label>
              <input className="input" value={contactName} onChange={(e) => setContactName(e.target.value)} />
            </div>
            <div className="grid sm:grid-cols-2 gap-3">
              <div>
                <label className="label">Phone</label>
                <input className="input" value={contactPhone} onChange={(e) => setContactPhone(e.target.value)} />
              </div>
              <div>
                <label className="label">Email</label>
                <input className="input" type="email" value={contactEmail} onChange={(e) => setContactEmail(e.target.value)} />
              </div>
            </div>
            <div className="grid sm:grid-cols-2 gap-3">
              <div>
                <label className="label">WeChat</label>
                <input className="input" value={contactWechat} onChange={(e) => setContactWechat(e.target.value)} />
              </div>
              <div>
                <label className="label">WhatsApp</label>
                <input className="input" value={contactWhatsapp} onChange={(e) => setContactWhatsapp(e.target.value)} />
              </div>
            </div>
            <div>
              <label className="label">Website</label>
              <input className="input" value={website} onChange={(e) => setWebsite(e.target.value)} />
            </div>
            <div className="flex gap-2">
              <button type="button" className="btn-secondary flex-1" onClick={() => setStep(2)}>Back</button>
              <button type="button" className="btn-primary flex-1" onClick={() => setStep(4)}>Continue</button>
            </div>
          </section>
        )}

        {step === 4 && (
          <section className="card p-6 space-y-4">
            <h2 className="font-semibold text-gray-900">4. Product categories</h2>
            <p className="text-xs text-gray-500">Comma-separated — can seed product catalog after approval</p>
            <textarea
              className="input min-h-[80px]"
              value={productCategories}
              onChange={(e) => setProductCategories(e.target.value)}
              placeholder="Electronics, Industrial machinery, Textiles"
            />
            <div className="flex gap-2">
              <button type="button" className="btn-secondary flex-1" onClick={() => setStep(3)}>Back</button>
              <button type="button" className="btn-primary flex-1" onClick={() => setStep(5)}>Continue</button>
            </div>
          </section>
        )}

        {step === 5 && (
          <section className="card p-6 space-y-4">
            <h2 className="font-semibold text-gray-900 flex items-center gap-2">
              <Globe2 size={18} /> 5. Target markets
            </h2>
            <textarea
              className="input min-h-[80px]"
              value={targetMarkets}
              onChange={(e) => setTargetMarkets(e.target.value)}
              placeholder="Uzbekistan, Kazakhstan, UAE"
            />
            <div className="flex gap-2">
              <button type="button" className="btn-secondary flex-1" onClick={() => setStep(4)}>Back</button>
              <button type="button" className="btn-primary flex-1" onClick={() => setStep(6)}>Continue</button>
            </div>
          </section>
        )}

        {step === 6 && (
          <section className="card p-6 space-y-4">
            <h2 className="font-semibold text-gray-900">6. Commission model</h2>
            <select className="input" value={commissionModel} onChange={(e) => setCommissionModel(e.target.value)}>
              {COMMISSION_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
            <div className="flex gap-2">
              <button type="button" className="btn-secondary flex-1" onClick={() => setStep(5)}>Back</button>
              <button type="button" className="btn-primary flex-1" onClick={() => setStep(7)}>Continue</button>
            </div>
          </section>
        )}

        {step === 7 && (
          <section className="card p-6 space-y-4">
            <h2 className="font-semibold text-gray-900">7. Documents</h2>
            <p className="text-sm text-gray-500 bg-amber-50 border border-amber-100 rounded-lg p-3">
              Document upload will be available in a future release. You may email certificates and
              catalogs to our team after submission.
            </p>
            <div className="flex gap-2">
              <button type="button" className="btn-secondary flex-1" onClick={() => setStep(6)}>Back</button>
              <button type="button" className="btn-primary flex-1" onClick={() => setStep(8)}>Continue</button>
            </div>
          </section>
        )}

        {step === 8 && (
          <section className="card p-6 space-y-4">
            <h2 className="font-semibold text-gray-900 flex items-center gap-2">
              <Send size={18} /> 8. Submit application
            </h2>
            <ul className="text-sm text-gray-600 space-y-1">
              <li><strong>Company:</strong> {companyName || "—"}</li>
              <li><strong>Location:</strong> {[city, country].filter(Boolean).join(", ") || "—"}</li>
              <li><strong>Contact:</strong> {contactName || contactEmail || "—"}</li>
              <li><strong>Markets:</strong> {targetMarkets || "—"}</li>
            </ul>
            <p className="text-xs text-gray-400">
              Submission requires manual review. No auto-approval, publishing, or messaging.
            </p>
            <div className="flex gap-2">
              <button type="button" className="btn-secondary flex-1" onClick={() => setStep(7)}>Back</button>
              <button
                type="button"
                className="btn-primary flex-1 flex items-center justify-center gap-2"
                disabled={!termsAccepted || !companyName.trim() || submitMutation.isPending}
                onClick={() => submitMutation.mutate()}
              >
                {submitMutation.isPending ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
                Submit for review
              </button>
            </div>
            <button
              type="button"
              className="text-xs text-gray-500 underline w-full"
              disabled={applyMutation.isPending}
              onClick={() => applyMutation.mutate()}
            >
              Save draft only
            </button>
          </section>
        )}
      </div>
    </div>
  );
}
