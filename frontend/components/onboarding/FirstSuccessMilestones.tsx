"use client";

import { CheckCircle2, Lock, Rocket, Star, Trophy } from "lucide-react";
import type { FirstSuccessSummary } from "@/lib/api";
import { OnboardingIllustration } from "./OnboardingIllustration";
import { OnboardingStepCard } from "./OnboardingStepCard";
import { cn } from "@/lib/utils";

export function FirstSuccessMilestones({
  firstSuccess,
  platformReady,
}: {
  firstSuccess: FirstSuccessSummary | null;
  platformReady: boolean;
}) {
  if (!platformReady) {
    return (
      <section className="relative rounded-3xl border border-violet-100 bg-gradient-to-br from-violet-50/80 to-white overflow-hidden">
        <div className="absolute inset-0 backdrop-blur-[1px] bg-white/40 z-10 flex flex-col items-center justify-center p-8 text-center">
          <div className="w-14 h-14 rounded-2xl bg-violet-100 flex items-center justify-center mb-4">
            <Lock size={24} className="text-violet-600" />
          </div>
          <h2 className="text-lg font-semibold text-navy-900">First Success milestones unlock soon</h2>
          <p className="text-sm text-gray-600 mt-2 max-w-md">
            Complete your platform setup first — then we&apos;ll track your first published post, proposal, social
            connection, and real lead.
          </p>
        </div>
        <div className="p-6 opacity-40 pointer-events-none select-none blur-[2px]">
          <LockedPreview />
        </div>
      </section>
    );
  }

  if (!firstSuccess) return null;

  const allDone = firstSuccess.achieved_count >= firstSuccess.total_count;

  return (
    <section className="rounded-3xl border border-violet-100 bg-gradient-to-br from-violet-50/60 via-white to-white overflow-hidden shadow-card">
      <div className="grid lg:grid-cols-[1fr_220px] gap-6 p-6 sm:p-8">
        <div className="space-y-5">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-violet-700 flex items-center gap-1.5">
                <Star size={12} />
                First Success
              </p>
              <h2 className="text-xl font-semibold text-navy-900 mt-1">
                {allDone ? "You hit every first-success milestone!" : "Real outcomes that prove it works"}
              </h2>
              <p className="text-sm text-gray-500 mt-1">
                These aren&apos;t checklist items — they&apos;re the moments buyers and leadership actually notice.
              </p>
            </div>
            <MilestoneProgressRing
              achieved={firstSuccess.achieved_count}
              total={firstSuccess.total_count}
              percent={firstSuccess.percent}
            />
          </div>

          {allDone && !firstSuccess.celebrated ? (
            <div className="flex items-center gap-3 rounded-2xl bg-violet-600 text-white px-5 py-4 animate-celebrate">
              <Trophy size={22} className="shrink-0" />
              <div>
                <p className="font-semibold">Congratulations — your factory is live!</p>
                <p className="text-sm text-violet-100 mt-0.5">
                  Publishing, proposals, social, and leads are all in motion.
                </p>
              </div>
            </div>
          ) : null}

          <div className="space-y-3">
            {firstSuccess.milestones.map((milestone, i) => (
              <OnboardingStepCard key={milestone.id} step={milestone} index={i} />
            ))}
          </div>
        </div>

        <div className="hidden lg:block">
          <OnboardingIllustration variant="success" className="h-full min-h-[200px]" />
        </div>
      </div>
    </section>
  );
}

function MilestoneProgressRing({
  achieved,
  total,
  percent,
}: {
  achieved: number;
  total: number;
  percent: number;
}) {
  const r = 36;
  const c = 2 * Math.PI * r;
  const offset = c - (percent / 100) * c;

  return (
    <div className="flex items-center gap-3">
      <div className="relative w-20 h-20">
        <svg viewBox="0 0 88 88" className="rotate-[-90deg] w-full h-full" aria-hidden>
          <circle cx="44" cy="44" r={r} fill="none" stroke="#ede9fe" strokeWidth="8" />
          <circle
            cx="44"
            cy="44"
            r={r}
            fill="none"
            stroke="#7c3aed"
            strokeWidth="8"
            strokeLinecap="round"
            strokeDasharray={c}
            strokeDashoffset={offset}
            className="transition-all duration-1000"
          />
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <Rocket size={20} className="text-violet-600" />
        </div>
      </div>
      <div>
        <p className="text-2xl font-bold tabular-nums text-violet-700">
          {achieved}/{total}
        </p>
        <p className="text-xs text-gray-500">milestones</p>
      </div>
    </div>
  );
}

function LockedPreview() {
  const placeholders = ["First published content", "First generated proposal", "First connected social", "First real lead"];
  return (
    <div className="space-y-3">
      <p className="text-xs font-semibold uppercase tracking-wider text-violet-700">First Success</p>
      {placeholders.map((label) => (
        <div key={label} className="rounded-xl border border-violet-100 bg-white p-4 flex items-center gap-3">
          <CheckCircle2 size={18} className="text-gray-300" />
          <span className="text-sm text-gray-400">{label}</span>
        </div>
      ))}
    </div>
  );
}
