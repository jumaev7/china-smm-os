"use client";

import { Briefcase, Contact, Users } from "lucide-react";
import { OnboardingActionCard } from "@/components/onboarding/OnboardingActionCard";
import { OnboardingStepShell } from "@/components/onboarding/OnboardingStepShell";
import { useOnboardingReadiness } from "@/lib/onboarding-hooks";

const CRM_STEPS = [
  { id: "first_lead", icon: Contact, title: "Create first lead", text: "Capture an inquiry with company and contact details.", href: "/leads" },
  { id: "first_buyer", icon: Users, title: "Add a buyer", text: "Build your buyer network profile for repeat partners.", href: "/buyers" },
  { id: "first_deal", icon: Briefcase, title: "Open a deal", text: "Track negotiation stages and expected close date.", href: "/deals" },
] as const;

export default function OnboardingCrmPage() {
  const { data: readiness } = useOnboardingReadiness();

  return (
    <OnboardingStepShell
      stepId="first_lead"
      title="Sales CRM setup"
      subtitle="Organize leads, buyers, and deals in one executive pipeline."
      illustration="business"
      nextHref="/onboarding/proposal"
      nextLabel="Continue to proposals"
    >
      <div className="space-y-3">
        {CRM_STEPS.map(({ id, icon, title, text, href }, i) => {
          const step = readiness?.business_steps.find((s) => s.id === id);
          return (
            <OnboardingActionCard
              key={id}
              icon={icon}
              title={title}
              description={text}
              href={href}
              completed={step?.status === "completed"}
              index={i}
            />
          );
        })}
      </div>
    </OnboardingStepShell>
  );
}
