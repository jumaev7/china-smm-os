import type { LucideIcon } from "lucide-react";
import {
  AlertTriangle,
  Bell,
  CheckCircle2,
  CreditCard,
  FileSignature,
  HeartPulse,
  Info,
  Link2,
  Radio,
  Rocket,
  Shield,
  Sparkles,
  UserPlus,
  XCircle,
  Zap,
} from "lucide-react";
import type { NotificationItem as ApiNotificationItem } from "@/lib/api";

export type NotificationCategory =
  | "all"
  | "publishing"
  | "crm"
  | "integrations"
  | "automation"
  | "journey"
  | "billing"
  | "security"
  | "platform";

export type NotificationSeverity = "info" | "success" | "warning" | "error" | "critical";

export type NotificationTimeFilter = "all" | "today" | "week";

export type NotificationReadFilter = "all" | "unread";

export interface NotificationTimelineEvent {
  id: string;
  label: string;
  timestamp: string;
  detail?: string;
}

export interface NotificationMetadata {
  [key: string]: string | number | boolean | null | undefined;
}

export interface AppNotification {
  id: string;
  category: Exclude<NotificationCategory, "all">;
  title: string;
  description: string;
  severity: NotificationSeverity;
  createdAt: string;
  read: boolean;
  readAt?: string | null;
  eventType: string;
  actionUrl?: string | null;
  icon: LucideIcon;
  iconClassName: string;
  primaryAction: { label: string; href: string };
  secondaryAction?: { label: string; href: string };
  relatedModule: string;
  relatedModuleHref: string;
  suggestedAction: string;
  timeline: NotificationTimelineEvent[];
  metadata: NotificationMetadata;
}

export interface NotificationFilters {
  category: NotificationCategory;
  severity: NotificationSeverity | "all";
  read: NotificationReadFilter;
  time: NotificationTimeFilter;
  search: string;
}

export const NOTIFICATION_CATEGORIES: { id: NotificationCategory; labelKey: string }[] = [
  { id: "all", labelKey: "notifications.categories.all" },
  { id: "publishing", labelKey: "notifications.categories.publishing" },
  { id: "crm", labelKey: "notifications.categories.crm" },
  { id: "integrations", labelKey: "notifications.categories.integrations" },
  { id: "automation", labelKey: "notifications.categories.automation" },
  { id: "journey", labelKey: "notifications.categories.journey" },
  { id: "billing", labelKey: "notifications.categories.billing" },
  { id: "security", labelKey: "notifications.categories.security" },
  { id: "platform", labelKey: "notifications.categories.platform" },
];

export const SEVERITY_OPTIONS: { id: NotificationSeverity | "all"; labelKey: string }[] = [
  { id: "all", labelKey: "notifications.severities.all" },
  { id: "info", labelKey: "notifications.severities.info" },
  { id: "success", labelKey: "notifications.severities.success" },
  { id: "warning", labelKey: "notifications.severities.warning" },
  { id: "error", labelKey: "notifications.severities.error" },
  { id: "critical", labelKey: "notifications.severities.critical" },
];

export const TIME_FILTER_OPTIONS: { id: NotificationTimeFilter; labelKey: string }[] = [
  { id: "all", labelKey: "notifications.time.all" },
  { id: "today", labelKey: "notifications.time.today" },
  { id: "week", labelKey: "notifications.time.week" },
];

export const READ_FILTER_OPTIONS: { id: NotificationReadFilter; labelKey: string }[] = [
  { id: "all", labelKey: "notifications.readFilter.all" },
  { id: "unread", labelKey: "notifications.readFilter.unread" },
];

export const CATEGORY_LABEL_KEYS: Record<Exclude<NotificationCategory, "all">, string> = {
  publishing: "notifications.categories.publishing",
  crm: "notifications.categories.crm",
  integrations: "notifications.categories.integrations",
  automation: "notifications.categories.automation",
  journey: "notifications.categories.journey",
  billing: "notifications.categories.billing",
  security: "notifications.categories.security",
  platform: "notifications.categories.platform",
};

export const SEVERITY_LABEL_KEYS: Record<NotificationSeverity, string> = {
  info: "notifications.severities.info",
  success: "notifications.severities.success",
  warning: "notifications.severities.warning",
  error: "notifications.severities.error",
  critical: "notifications.severities.critical",
};

export const SEVERITY_STYLES: Record<NotificationSeverity, string> = {
  info: "bg-sky-100 text-sky-700 dark-tenant:bg-sky-500/15 dark-tenant:text-sky-300",
  success: "bg-emerald-100 text-emerald-700 dark-tenant:bg-emerald-500/15 dark-tenant:text-emerald-300",
  warning: "bg-amber-100 text-amber-800 dark-tenant:bg-amber-500/15 dark-tenant:text-amber-300",
  error: "bg-orange-100 text-orange-800 dark-tenant:bg-orange-500/15 dark-tenant:text-orange-300",
  critical: "bg-red-100 text-red-700 dark-tenant:bg-red-500/15 dark-tenant:text-red-300",
};

export const SEVERITY_DOT_STYLES: Record<NotificationSeverity, string> = {
  info: "bg-sky-500",
  success: "bg-emerald-500",
  warning: "bg-amber-500",
  error: "bg-orange-500",
  critical: "bg-red-500",
};

const CATEGORY_MODULE: Record<
  Exclude<NotificationCategory, "all">,
  { labelKey: string; href: string; icon: LucideIcon; iconClassName: string }
> = {
  publishing: {
    labelKey: "notifications.categories.publishing",
    href: "/publishing",
    icon: Radio,
    iconClassName: "text-violet-600 bg-violet-50 dark-tenant:bg-violet-500/10 dark-tenant:text-violet-400",
  },
  crm: {
    labelKey: "notifications.categories.crm",
    href: "/crm",
    icon: FileSignature,
    iconClassName: "text-indigo-600 bg-indigo-50 dark-tenant:bg-indigo-500/10 dark-tenant:text-indigo-400",
  },
  integrations: {
    labelKey: "notifications.categories.integrations",
    href: "/integrations",
    icon: Link2,
    iconClassName: "text-sky-600 bg-sky-50 dark-tenant:bg-sky-500/10 dark-tenant:text-sky-400",
  },
  automation: {
    labelKey: "notifications.categories.automation",
    href: "/automation",
    icon: Zap,
    iconClassName: "text-amber-600 bg-amber-50 dark-tenant:bg-amber-500/10 dark-tenant:text-amber-400",
  },
  journey: {
    labelKey: "notifications.categories.journey",
    href: "/customer-success/journey",
    icon: HeartPulse,
    iconClassName: "text-amber-600 bg-amber-50 dark-tenant:bg-amber-500/10 dark-tenant:text-amber-400",
  },
  billing: {
    labelKey: "notifications.categories.billing",
    href: "/billing",
    icon: CreditCard,
    iconClassName: "text-slate-600 bg-slate-100 dark-tenant:bg-white/10 dark-tenant:text-slate-300",
  },
  security: {
    labelKey: "notifications.categories.security",
    href: "/tenant-users",
    icon: Shield,
    iconClassName: "text-red-600 bg-red-50 dark-tenant:bg-red-500/10 dark-tenant:text-red-400",
  },
  platform: {
    labelKey: "notifications.categories.platform",
    href: "/dashboard",
    icon: Rocket,
    iconClassName: "text-violet-600 bg-violet-50 dark-tenant:bg-violet-500/10 dark-tenant:text-violet-400",
  },
};

function severityIcon(severity: NotificationSeverity): LucideIcon {
  if (severity === "critical" || severity === "error") return XCircle;
  if (severity === "warning") return AlertTriangle;
  if (severity === "success") return CheckCircle2;
  return Info;
}

function severityIconClass(severity: NotificationSeverity): string {
  if (severity === "critical" || severity === "error") {
    return "text-red-600 bg-red-50 dark-tenant:bg-red-500/10 dark-tenant:text-red-400";
  }
  if (severity === "warning") {
    return "text-amber-600 bg-amber-50 dark-tenant:bg-amber-500/10 dark-tenant:text-amber-400";
  }
  if (severity === "success") {
    return "text-emerald-600 bg-emerald-50 dark-tenant:bg-emerald-500/10 dark-tenant:text-emerald-400";
  }
  return "text-sky-600 bg-sky-50 dark-tenant:bg-sky-500/10 dark-tenant:text-sky-400";
}

function metadataFromPayload(payload: Record<string, unknown> | null): NotificationMetadata {
  if (!payload) return {};
  const out: NotificationMetadata = {};
  for (const [key, value] of Object.entries(payload)) {
    if (
      typeof value === "string" ||
      typeof value === "number" ||
      typeof value === "boolean" ||
      value === null ||
      value === undefined
    ) {
      out[key] = value;
    }
  }
  return out;
}

export function mapApiNotificationToApp(
  item: ApiNotificationItem,
  t: (key: string) => string,
): AppNotification {
  const category = item.category;
  const moduleMeta = CATEGORY_MODULE[category] ?? CATEGORY_MODULE.platform;
  const href = item.action_url || moduleMeta.href;
  const description = item.message || item.title;
  const Icon = severityIcon(item.severity);
  const iconClassName = severityIconClass(item.severity);

  return {
    id: item.id,
    category,
    title: item.title,
    description,
    severity: item.severity,
    createdAt: item.created_at,
    read: item.is_read,
    readAt: item.read_at,
    eventType: item.event_type,
    actionUrl: item.action_url,
    icon: Icon,
    iconClassName,
    primaryAction: {
      label: t("notifications.actions.open"),
      href,
    },
    secondaryAction: href !== "/notifications"
      ? { label: t("notifications.actions.viewModule"), href: moduleMeta.href }
      : undefined,
    relatedModule: t(moduleMeta.labelKey),
    relatedModuleHref: moduleMeta.href,
    suggestedAction: description,
    timeline: [
      {
        id: `${item.id}-created`,
        label: item.event_type,
        timestamp: item.created_at,
        detail: description,
      },
    ],
    metadata: metadataFromPayload(item.metadata),
  };
}

function startOfToday(): number {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

function startOfWeek(): number {
  const d = new Date();
  const day = d.getDay();
  const diff = day === 0 ? 6 : day - 1;
  d.setDate(d.getDate() - diff);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

export function formatRelativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days === 1) return "yesterday";
  if (days < 7) return `${days}d ago`;
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export const DEFAULT_NOTIFICATION_FILTERS: NotificationFilters = {
  category: "all",
  severity: "all",
  read: "all",
  time: "all",
  search: "",
};

function matchesTime(notification: AppNotification, time: NotificationTimeFilter): boolean {
  if (time === "all") return true;
  const ts = new Date(notification.createdAt).getTime();
  if (time === "today") return ts >= startOfToday();
  if (time === "week") return ts >= startOfWeek();
  return true;
}

export function filterNotificationsByTime(
  notifications: AppNotification[],
  time: NotificationTimeFilter,
): AppNotification[] {
  return notifications.filter((n) => matchesTime(n, time));
}

export function computeNotificationSummary(notifications: AppNotification[]) {
  const unread = notifications.filter((n) => !n.read);
  const critical = notifications.filter(
    (n) => (n.severity === "critical" || n.severity === "error") && !n.read,
  );
  const warnings = notifications.filter((n) => n.severity === "warning" && !n.read);
  const todayStart = startOfToday();
  const resolvedToday = notifications.filter(
    (n) => n.read && n.readAt && new Date(n.readAt).getTime() >= todayStart,
  );

  return {
    unreadCount: unread.length,
    criticalCount: critical.length,
    warningCount: warnings.length,
    resolvedTodayCount: resolvedToday.length,
    total: notifications.length,
  };
}

export function sortNotifications(notifications: AppNotification[]): AppNotification[] {
  return [...notifications].sort(
    (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime(),
  );
}

export function formatUnreadBadge(count: number): string {
  if (count <= 0) return "";
  if (count > 99) return "99+";
  return String(count);
}

export const EMPTY_STATE_ICON = Bell;
export const INFO_ICON = Info;
export const ALERT_ICON = AlertTriangle;

export const CATEGORY_ICONS: Record<Exclude<NotificationCategory, "all">, LucideIcon> = {
  publishing: Radio,
  crm: UserPlus,
  integrations: Link2,
  automation: Zap,
  journey: Sparkles,
  billing: CreditCard,
  security: Shield,
  platform: Rocket,
};
