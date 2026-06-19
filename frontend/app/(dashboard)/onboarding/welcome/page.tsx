"use client";

import Link from "next/link";
import { ArrowRight, BarChart3, MessageSquare, Target, Users } from "lucide-react";
import { OnboardingLayout } from "@/components/onboarding/OnboardingLayout";

const HIGHLIGHTS = [
  {
    icon: Users,
    title: "Find buyers",
    text: "Build a buyer network, track leads, and match with international demand.",
  },
  {
    icon: MessageSquare,
    title: "Manage content",
    text: "Upload factory media, generate AI captions, and schedule publications.",
  },
  {
    icon: Target,
    title: "Close sales",
    text: "Pipeline deals, commercial proposals, and unified communications in one place.",
  },
  {
    icon: BarChart3,
    title: "Grow with data",
    text: "Growth Center KPIs and AI recommendations show where to focus next.",
  },
] as const;

export default function OnboardingWelcomePage() {
  return (
    <OnboardingLayout
      title="Welcome to your factory workspace"
      subtitle="One platform for export sales, content, and buyer relationships."
      contextStep="welcome"
    >
      <div className="space-y-6">
        <p className="text-gray-700 leading-relaxed">
          China SMM OS helps Chinese manufacturers reach buyers in Central Asia and worldwide.
          In the next few steps you will connect channels, publish content, and set up your sales pipeline.
        </p>

        <div className="grid sm:grid-cols-2 gap-4">
          {HIGHLIGHTS.map(({ icon: Icon, title, text }) => (
            <div key={title} className="rounded-xl border border-slate-200 p-4 bg-white">
              <Icon className="text-brand-600 mb-2" size={22} />
              <h3 className="font-semibold text-gray-900">{title}</h3>
              <p className="text-sm text-gray-600 mt-1">{text}</p>
            </div>
          ))}
        </div>

        <Link
          href="/onboarding/company"
          className="inline-flex items-center gap-2 rounded-lg bg-brand-600 text-white font-medium px-5 py-2.5 hover:bg-brand-700"
        >
          Start setup
          <ArrowRight size={18} />
        </Link>
      </div>
    </OnboardingLayout>
  );
}
