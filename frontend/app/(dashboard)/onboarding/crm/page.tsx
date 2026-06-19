"use client";

import Link from "next/link";
import { ArrowRight, Briefcase, Contact, Users } from "lucide-react";
import { OnboardingLayout } from "@/components/onboarding/OnboardingLayout";

const CRM_STEPS = [
  { icon: Contact, title: "Create first lead", text: "Capture an inquiry with company and contact details.", href: "/leads" },
  { icon: Users, title: "Add a buyer", text: "Build your buyer network profile for repeat partners.", href: "/buyers" },
  { icon: Briefcase, title: "Open a deal", text: "Track negotiation stages and expected close date.", href: "/deals" },
] as const;

export default function OnboardingCrmPage() {
  return (
    <OnboardingLayout
      title="Sales CRM setup"
      subtitle="Organize leads, buyers, and deals in one pipeline."
      contextStep="crm"
    >
      <div className="space-y-4 max-w-xl">
        {CRM_STEPS.map(({ icon: Icon, title, text, href }) => (
          <Link
            key={title}
            href={href}
            className="flex gap-4 rounded-xl border border-slate-200 p-4 hover:border-brand-300 hover:bg-brand-50/30 transition-colors"
          >
            <div className="rounded-lg bg-sky-50 p-2 h-fit">
              <Icon className="text-sky-600" size={20} />
            </div>
            <div>
              <h3 className="font-semibold text-gray-900">{title}</h3>
              <p className="text-sm text-gray-600 mt-0.5">{text}</p>
            </div>
          </Link>
        ))}

        <Link
          href="/onboarding/proposal"
          className="inline-flex items-center gap-2 rounded-lg bg-brand-600 text-white font-medium px-5 py-2.5 hover:bg-brand-700 mt-4"
        >
          Continue to proposals
          <ArrowRight size={18} />
        </Link>
      </div>
    </OnboardingLayout>
  );
}
