"use client";

import Link from "next/link";
import { ArrowRight, Calendar, Image, Sparkles, Upload } from "lucide-react";
import { OnboardingLayout } from "@/components/onboarding/OnboardingLayout";

const STEPS = [
  { icon: Upload, title: "Upload media", text: "Add your first factory photo or product video.", href: "/media-library" },
  { icon: Image, title: "Create a post", text: "Turn media into a draft content item.", href: "/content" },
  { icon: Sparkles, title: "AI caption", text: "Use Content Studio or AI assistant to generate captions.", href: "/content-studio" },
  { icon: Calendar, title: "Schedule", text: "Plan your first publication on the calendar.", href: "/calendar" },
] as const;

export default function OnboardingContentPage() {
  return (
    <OnboardingLayout
      title="First content"
      subtitle="Show buyers what you manufacture — content drives inbound interest."
      contextStep="content"
    >
      <div className="space-y-4 max-w-xl">
        {STEPS.map(({ icon: Icon, title, text, href }) => (
          <Link
            key={title}
            href={href}
            className="flex gap-4 rounded-xl border border-slate-200 p-4 hover:border-brand-300 hover:bg-brand-50/30 transition-colors"
          >
            <div className="rounded-lg bg-brand-50 p-2 h-fit">
              <Icon className="text-brand-600" size={20} />
            </div>
            <div>
              <h3 className="font-semibold text-gray-900">{title}</h3>
              <p className="text-sm text-gray-600 mt-0.5">{text}</p>
            </div>
          </Link>
        ))}

        <Link
          href="/onboarding/crm"
          className="inline-flex items-center gap-2 rounded-lg bg-brand-600 text-white font-medium px-5 py-2.5 hover:bg-brand-700 mt-4"
        >
          Continue to CRM
          <ArrowRight size={18} />
        </Link>
      </div>
    </OnboardingLayout>
  );
}
