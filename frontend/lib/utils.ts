import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";
import { ContentStatus } from "./api";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export const STATUS_CONFIG: Record<ContentStatus, { label: string; color: string; dot: string }> = {
  new: {
    label: "New",
    color: "bg-slate-100 text-slate-800 border-slate-200",
    dot: "bg-slate-400",
  },
  needs_review: {
    label: "Needs Review",
    color: "bg-amber-100 text-amber-800 border-amber-200",
    dot: "bg-amber-500",
  },
  needs_caption: {
    label: "Needs Caption",
    color: "bg-orange-100 text-orange-800 border-orange-200",
    dot: "bg-orange-500",
  },
  rejected: {
    label: "Rejected",
    color: "bg-red-100 text-red-700 border-red-200",
    dot: "bg-red-400",
  },
  draft: {
    label: "Draft",
    color: "bg-yellow-100 text-yellow-800 border-yellow-200",
    dot: "bg-yellow-400",
  },
  ready: {
    label: "Ready",
    color: "bg-green-100 text-green-800 border-green-200",
    dot: "bg-green-500",
  },
  ready_for_approval: {
    label: "Ready for approval",
    color: "bg-teal-100 text-teal-800 border-teal-200",
    dot: "bg-teal-500",
  },
  changes_requested: {
    label: "Changes requested",
    color: "bg-orange-100 text-orange-800 border-orange-200",
    dot: "bg-orange-500",
  },
  approved: {
    label: "Approved",
    color: "bg-blue-100 text-blue-800 border-blue-200",
    dot: "bg-blue-500",
  },
  scheduled: {
    label: "Scheduled",
    color: "bg-purple-100 text-purple-800 border-purple-200",
    dot: "bg-purple-500",
  },
  publishing: {
    label: "Publishing",
    color: "bg-cyan-100 text-cyan-800 border-cyan-200",
    dot: "bg-cyan-500",
  },
  published: {
    label: "Published",
    color: "bg-emerald-100 text-emerald-800 border-emerald-200",
    dot: "bg-emerald-500",
  },
  partial_failed: {
    label: "Partial failed",
    color: "bg-orange-100 text-orange-800 border-orange-200",
    dot: "bg-orange-500",
  },
  failed: {
    label: "Failed",
    color: "bg-red-100 text-red-800 border-red-200",
    dot: "bg-red-500",
  },
};

export const PLATFORM_CONFIG: Record<string, { label: string; color: string; icon: string }> = {
  instagram: { label: "Instagram", color: "text-pink-600 bg-pink-50", icon: "IG" },
  facebook: { label: "Facebook", color: "text-blue-600 bg-blue-50", icon: "FB" },
  tiktok: { label: "TikTok", color: "text-gray-800 bg-gray-100", icon: "TK" },
  telegram: { label: "Telegram", color: "text-sky-600 bg-sky-50", icon: "TG" },
  linkedin: { label: "LinkedIn", color: "text-indigo-600 bg-indigo-50", icon: "LI" },
};

export const LANGUAGE_LABELS: Record<string, string> = {
  zh: "Chinese",
  en: "English",
  ru: "Russian",
  ko: "Korean",
  ja: "Japanese",
};

export const CATEGORY_LABELS: Record<string, string> = {
  restaurant: "Restaurant",
  retail: "Retail",
  beauty: "Beauty",
  construction: "Construction",
  logistics: "Logistics",
  technology: "Technology",
  education: "Education",
  healthcare: "Healthcare",
  real_estate: "Real Estate",
  other: "Other",
};

export type BillingStatusLabel = "active" | "unpaid" | "paused";

export const BILLING_STATUS_CONFIG: Record<
  BillingStatusLabel,
  { label: string; color: string }
> = {
  active: {
    label: "Active",
    color: "bg-emerald-100 text-emerald-800 border-emerald-200",
  },
  unpaid: {
    label: "Unpaid",
    color: "bg-red-100 text-red-800 border-red-200",
  },
  paused: {
    label: "Paused",
    color: "bg-gray-100 text-gray-600 border-gray-200",
  },
};

export type InboxPriorityLabel = "high" | "medium" | "low";

export const INBOX_PRIORITY_CONFIG: Record<
  InboxPriorityLabel,
  { label: string; color: string }
> = {
  high: {
    label: "High",
    color: "bg-red-100 text-red-800 border-red-200",
  },
  medium: {
    label: "Medium",
    color: "bg-amber-100 text-amber-800 border-amber-200",
  },
  low: {
    label: "Low",
    color: "bg-gray-100 text-gray-600 border-gray-200",
  },
};

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
