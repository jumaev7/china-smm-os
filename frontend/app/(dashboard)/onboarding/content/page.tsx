"use client";

import { Calendar, Image, Sparkles, Upload } from "lucide-react";
import { OnboardingActionCard } from "@/components/onboarding/OnboardingActionCard";
import { OnboardingStepShell } from "@/components/onboarding/OnboardingStepShell";

const STEPS = [
  { icon: Upload, title: "Upload media", text: "Add your first factory photo or product video.", href: "/media-library" },
  { icon: Image, title: "Create a post", text: "Turn media into a draft content item.", href: "/content" },
  { icon: Sparkles, title: "AI caption", text: "Use Content Studio to generate export-ready captions.", href: "/content-studio" },
  { icon: Calendar, title: "Schedule", text: "Plan your first publication on the calendar.", href: "/calendar" },
] as const;

export default function OnboardingContentPage() {
  return (
    <OnboardingStepShell
      stepId="first_ai_content"
      title="Generate your first AI content"
      subtitle="Show buyers what you manufacture — AI content proves the publishing workflow."
      illustration="platform"
      nextHref="/onboarding/publishing"
      nextLabel="Review publishing readiness"
    >
      <div className="space-y-3">
        {STEPS.map(({ icon, title, text, href }, i) => (
          <OnboardingActionCard key={title} icon={icon} title={title} description={text} href={href} index={i} />
        ))}
      </div>
    </OnboardingStepShell>
  );
}
