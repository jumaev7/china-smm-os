"use client";

import Link from "next/link";
import { format, parseISO } from "date-fns";
import {
  Briefcase,
  FileText,
  Plug,
  Send,
  Settings,
  ShoppingBag,
  type LucideIcon,
} from "lucide-react";
import type { JourneyTimelineEntry, JourneyWeeklyWin } from "@/lib/api";
import { cn } from "@/lib/utils";

type FeedItem = {
  id: string;
  title: string;
  detail: string;
  occurredAt: string;
  category: string;
  href?: string | null;
  icon: LucideIcon;
};

const CATEGORY_ICONS: Record<string, LucideIcon> = {
  publishing: Send,
  pipeline: Briefcase,
  buyers: ShoppingBag,
  proposals: FileText,
  communication: Briefcase,
  adoption: Settings,
  revenue: Briefcase,
  feature: Plug,
  checkpoint: Settings,
  weekly_win: FileText,
  outcome: ShoppingBag,
};

function categorizeEntry(entry: JourneyTimelineEntry): string {
  if (entry.feature_key?.includes("publish") || entry.feature_key === "publishing") return "publishing";
  if (entry.feature_key?.includes("crm") || entry.feature_key === "crm_leads") return "pipeline";
  if (entry.feature_key === "buyers") return "buyers";
  if (entry.feature_key === "content") return "publishing";
  if (entry.feature_key === "proposals") return "proposals";
  if (entry.entry_type === "checkpoint") return "adoption";
  return entry.entry_type;
}

function buildFeedItems(
  timeline: JourneyTimelineEntry[],
  weeklyWins: JourneyWeeklyWin[],
): FeedItem[] {
  const fromTimeline: FeedItem[] = timeline.map((e) => {
    const cat = categorizeEntry(e);
    return {
      id: e.id,
      title: e.title,
      detail: e.detail,
      occurredAt: e.occurred_at,
      category: cat,
      href: null,
      icon: CATEGORY_ICONS[cat] ?? CATEGORY_ICONS[e.entry_type] ?? Settings,
    };
  });

  const fromWins: FeedItem[] = weeklyWins.map((w) => ({
    id: w.id,
    title: w.title,
    detail: w.detail,
    occurredAt: w.occurred_at,
    category: w.category,
    href: w.href,
    icon: CATEGORY_ICONS[w.category] ?? FileText,
  }));

  const merged = [...fromTimeline, ...fromWins];
  const seen = new Set<string>();
  const unique = merged.filter((item) => {
    if (seen.has(item.id)) return false;
    seen.add(item.id);
    return true;
  });

  return unique
    .sort((a, b) => new Date(b.occurredAt).getTime() - new Date(a.occurredAt).getTime())
    .slice(0, 12);
}

export function JourneyActivityFeed({
  timeline,
  weeklyWins,
  delay = 0,
}: {
  timeline: JourneyTimelineEntry[];
  weeklyWins: JourneyWeeklyWin[];
  delay?: number;
}) {
  const items = buildFeedItems(timeline, weeklyWins);

  return (
    <section
      className="card-premium p-6 animate-fade-in-up"
      style={{ animationDelay: `${delay}ms` }}
      aria-label="Activity feed"
    >
      <div className="mb-5">
        <h2 className="section-title text-base font-semibold text-navy-900 dark-tenant:text-slate-100">
          Activity Feed
        </h2>
        <p className="text-xs text-gray-500 dark-tenant:text-slate-400 mt-0.5">Recent platform activity</p>
      </div>

      {items.length === 0 ? (
        <div className="text-center py-8">
          <p className="text-sm font-medium text-navy-900 dark-tenant:text-slate-200">No recent activity</p>
          <p className="text-xs text-gray-500 dark-tenant:text-slate-400 mt-1">
            Publish content, log CRM activity, or connect channels to see updates here.
          </p>
        </div>
      ) : (
        <ul className="space-y-1">
          {items.map((item, i) => {
            const Icon = item.icon;
            const inner = (
              <div
                className={cn(
                  "flex gap-3 rounded-xl px-3 py-3 transition-colors",
                  item.href && "hover:bg-brand-50/50 dark-tenant:hover:bg-violet-500/[0.06]",
                )}
              >
                <div className="w-8 h-8 rounded-lg bg-slate-100 flex items-center justify-center shrink-0 dark-tenant:bg-white/[0.06]">
                  <Icon size={14} className="text-brand-600 dark-tenant:text-violet-400" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-sm font-medium text-navy-900 dark-tenant:text-slate-200 truncate">
                      {item.title}
                    </p>
                    <time
                      className="text-[10px] text-gray-400 dark-tenant:text-slate-500 shrink-0 tabular-nums"
                      dateTime={item.occurredAt}
                    >
                      {format(parseISO(item.occurredAt), "MMM d")}
                    </time>
                  </div>
                  <p className="text-xs text-gray-500 dark-tenant:text-slate-400 mt-0.5 line-clamp-2">{item.detail}</p>
                  <span className="text-[10px] uppercase tracking-wider text-gray-400 dark-tenant:text-slate-500 mt-1 inline-block">
                    {item.category.replace(/_/g, " ")}
                  </span>
                </div>
              </div>
            );

            return (
              <li
                key={item.id}
                className="animate-fade-in-up"
                style={{ animationDelay: `${delay + i * 30}ms` }}
              >
                {item.href ? (
                  <Link href={item.href} className="block rounded-xl">
                    {inner}
                  </Link>
                ) : (
                  inner
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
