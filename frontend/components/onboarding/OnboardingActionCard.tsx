"use client";

import Link from "next/link";
import type { LucideIcon } from "lucide-react";
import { ArrowRight, CheckCircle2 } from "lucide-react";
import { cn } from "@/lib/utils";

export function OnboardingActionCard({
  icon: Icon,
  title,
  description,
  href,
  completed = false,
  badge,
  onClick,
  index = 0,
}: {
  icon: LucideIcon;
  title: string;
  description: string;
  href?: string;
  completed?: boolean;
  badge?: string;
  onClick?: () => void;
  index?: number;
}) {
  const inner = (
    <div
      className={cn(
        "group relative flex gap-4 rounded-2xl border p-5 transition-all duration-300 animate-fade-in-up",
        completed
          ? "border-emerald-100 bg-emerald-50/40"
          : "border-slate-200 bg-white shadow-card hover:shadow-card-hover hover:border-brand-200",
      )}
      style={{ animationDelay: `${index * 70}ms` }}
    >
      {completed ? (
        <div className="absolute top-0 left-5 right-5 h-0.5 rounded-full bg-gradient-to-r from-emerald-400 to-emerald-500" />
      ) : null}

      <div
        className={cn(
          "shrink-0 flex items-center justify-center w-12 h-12 rounded-xl ring-1",
          completed ? "bg-emerald-100 ring-emerald-200 text-emerald-600" : "bg-brand-50 ring-brand-100 text-brand-600",
        )}
      >
        {completed ? <CheckCircle2 size={22} /> : <Icon size={22} />}
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className={cn("font-semibold text-[15px]", completed ? "text-gray-600" : "text-navy-900")}>
            {title}
          </h3>
          {badge ? (
            <span className="text-[10px] font-semibold uppercase tracking-wide text-brand-700 bg-brand-50 px-2 py-0.5 rounded-full">
              {badge}
            </span>
          ) : null}
        </div>
        <p className="text-sm text-gray-600 mt-1 leading-relaxed">{description}</p>
      </div>

      {!completed ? (
        <ArrowRight
          size={18}
          className="shrink-0 text-gray-300 group-hover:text-brand-500 group-hover:translate-x-0.5 transition-all self-center"
        />
      ) : null}
    </div>
  );

  if (onClick) {
    return (
      <button type="button" onClick={onClick} className="block w-full text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 rounded-2xl">
        {inner}
      </button>
    );
  }

  if (href) {
    return (
      <Link href={href} className="block focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 rounded-2xl">
        {inner}
      </Link>
    );
  }

  return inner;
}
