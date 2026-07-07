"use client";

import { cn } from "@/lib/utils";

const RING_RADIUS = 52;
const CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS;

export function ReadinessGauge({
  percent,
  label,
  sublabel,
  tone = "brand",
  size = "md",
  delay = 0,
}: {
  percent: number;
  label: string;
  sublabel?: string;
  tone?: "brand" | "emerald" | "violet" | "amber";
  size?: "sm" | "md" | "lg";
  delay?: number;
}) {
  const clamped = Math.min(100, Math.max(0, percent));
  const offset = CIRCUMFERENCE - (clamped / 100) * CIRCUMFERENCE;

  const toneMap = {
    brand: { stroke: "#2563eb", track: "#dbeafe", text: "text-brand-700" },
    emerald: { stroke: "#10b981", track: "#d1fae5", text: "text-emerald-700" },
    violet: { stroke: "#7c3aed", track: "#ede9fe", text: "text-violet-700" },
    amber: { stroke: "#f59e0b", track: "#fef3c7", text: "text-amber-700" },
  };
  const colors = toneMap[tone];

  const dim =
    size === "lg"
      ? { box: "w-36 h-36", text: "text-3xl", svg: 128 }
      : size === "sm"
        ? { box: "w-20 h-20", text: "text-lg", svg: 80 }
        : { box: "w-28 h-28", text: "text-2xl", svg: 112 };

  return (
    <div className="flex flex-col items-center gap-2 animate-fade-in-up" style={{ animationDelay: `${delay}ms` }}>
      <div className={cn("relative", dim.box)}>
        <svg
          width={dim.svg}
          height={dim.svg}
          viewBox="0 0 120 120"
          className="rotate-[-90deg] absolute inset-0 m-auto"
          aria-hidden
        >
          <circle cx="60" cy="60" r={RING_RADIUS} fill="none" stroke={colors.track} strokeWidth="10" />
          <circle
            cx="60"
            cy="60"
            r={RING_RADIUS}
            fill="none"
            stroke={colors.stroke}
            strokeWidth="10"
            strokeLinecap="round"
            strokeDasharray={CIRCUMFERENCE}
            strokeDashoffset={offset}
            className="transition-all duration-1000 ease-out"
            style={{ transitionDelay: `${delay}ms` }}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className={cn("font-bold tabular-nums", dim.text, colors.text)}>{clamped}%</span>
        </div>
      </div>
      <div className="text-center">
        <p className="text-sm font-semibold text-navy-900">{label}</p>
        {sublabel ? <p className="text-xs text-gray-500 mt-0.5">{sublabel}</p> : null}
      </div>
    </div>
  );
}
