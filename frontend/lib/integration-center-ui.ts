import type { LucideIcon } from "lucide-react";
import {
  BarChart3,
  Cloud,
  Facebook,
  Globe,
  Instagram,
  Linkedin,
  MessageCircle,
  Music2,
  Send,
  ShoppingBag,
  Users,
  Youtube,
} from "lucide-react";
import type { MetaConnectionSummary, PublishingAccount } from "@/lib/api";

export type IntegrationCategory =
  | "all"
  | "social"
  | "messaging"
  | "crm"
  | "marketplace"
  | "storage"
  | "analytics"
  | "coming_soon";

export type IntegrationStatus = "connected" | "not_connected" | "attention_needed" | "coming_soon";

export type IntegrationHealth = "healthy" | "degraded" | "unhealthy" | "unknown";

export type IntegrationPrimaryAction = "connect" | "manage" | "reconnect" | "coming_soon";

export type IntegrationKey =
  | "instagram"
  | "facebook"
  | "telegram"
  | "linkedin"
  | "tiktok"
  | "youtube"
  | "wechat"
  | "hubspot"
  | "salesforce"
  | "zoho_crm"
  | "alibaba"
  | "made_in_china"
  | "globalsources"
  | "google_drive"
  | "onedrive"
  | "dropbox"
  | "google_analytics";

export interface IntegrationCatalogItem {
  key: IntegrationKey;
  name: string;
  category: Exclude<IntegrationCategory, "all" | "coming_soon">;
  icon: LucideIcon;
  iconClassName: string;
  description: string;
  comingSoon?: boolean;
  connectHref?: string;
  manageHref?: string;
  settingsHref?: string;
  logsHref?: string;
  troubleshooting: string[];
  publishingPlatform?: boolean;
}

export interface ResolvedIntegration extends IntegrationCatalogItem {
  status: IntegrationStatus;
  health: IntegrationHealth;
  primaryAction: IntegrationPrimaryAction;
  lastSync?: string | null;
  accountName?: string | null;
  accountId?: string | null;
  permissions?: string[];
  missingPermissions?: string[];
  blockers?: string[];
  publishingPlatform?: boolean;
}

export const INTEGRATION_CATEGORIES: { id: IntegrationCategory; label: string }[] = [
  { id: "all", label: "All" },
  { id: "social", label: "Social" },
  { id: "messaging", label: "Messaging" },
  { id: "crm", label: "CRM" },
  { id: "marketplace", label: "Marketplace" },
  { id: "storage", label: "Storage" },
  { id: "analytics", label: "Analytics" },
  { id: "coming_soon", label: "Coming Soon" },
];

export const INTEGRATION_CATALOG: IntegrationCatalogItem[] = [
  {
    key: "instagram",
    name: "Instagram",
    category: "social",
    icon: Instagram,
    iconClassName: "text-pink-600 bg-pink-50 dark-tenant:bg-pink-500/10 dark-tenant:text-pink-400",
    description: "Publish product visuals and reach international buyers on Instagram.",
    connectHref: "/onboarding/channels/instagram",
    manageHref: "/publishing",
    settingsHref: "/onboarding/channels/instagram",
    logsHref: "/publishing",
    troubleshooting: [
      "Confirm your Instagram Business account is linked to a Facebook Page.",
      "Reconnect if your Meta access token has expired.",
      "Verify publish permissions in Meta Business settings.",
    ],
    publishingPlatform: true,
  },
  {
    key: "facebook",
    name: "Facebook",
    category: "social",
    icon: Facebook,
    iconClassName: "text-blue-600 bg-blue-50 dark-tenant:bg-blue-500/10 dark-tenant:text-blue-400",
    description: "Connect Meta Business for cross-posting and page management.",
    connectHref: "/onboarding/channels/facebook",
    manageHref: "/publishing",
    settingsHref: "/onboarding/channels/facebook",
    logsHref: "/publishing",
    troubleshooting: [
      "Ensure you have admin access to the Facebook Page.",
      "Refresh the connection if the token expired.",
      "Check that required Meta permissions were granted during OAuth.",
    ],
    publishingPlatform: true,
  },
  {
    key: "telegram",
    name: "Telegram",
    category: "messaging",
    icon: Send,
    iconClassName: "text-sky-600 bg-sky-50 dark-tenant:bg-sky-500/10 dark-tenant:text-sky-400",
    description: "Content intake and buyer inquiries from your factory Telegram group.",
    connectHref: "/clients",
    manageHref: "/clients",
    settingsHref: "/clients",
    logsHref: "/publishing",
    troubleshooting: [
      "Link a Telegram group on your client profile for content intake.",
      "Add a publishing destination channel for outbound posts.",
      "Confirm the bot has been added to your group with correct permissions.",
    ],
  },
  {
    key: "linkedin",
    name: "LinkedIn",
    category: "social",
    icon: Linkedin,
    iconClassName: "text-blue-700 bg-blue-50 dark-tenant:bg-blue-500/10 dark-tenant:text-blue-300",
    description: "Professional B2B reach and industry networking.",
    connectHref: "/publishing",
    manageHref: "/publishing",
    settingsHref: "/publishing",
    logsHref: "/publishing",
    troubleshooting: [
      "Add a LinkedIn publishing account from the Publishing page.",
      "Verify the account status is connected, not mock or expired.",
    ],
    publishingPlatform: true,
  },
  {
    key: "tiktok",
    name: "TikTok",
    category: "social",
    icon: Music2,
    iconClassName: "text-gray-900 bg-gray-100 dark-tenant:bg-white/10 dark-tenant:text-slate-200",
    description: "Short-form video for product discovery and brand awareness.",
    connectHref: "/publishing",
    manageHref: "/publishing",
    settingsHref: "/publishing",
    logsHref: "/publishing",
    troubleshooting: [
      "Connect a TikTok publishing account from the Publishing page.",
      "Ensure account permissions allow video publishing.",
    ],
    publishingPlatform: true,
  },
  {
    key: "youtube",
    name: "YouTube",
    category: "social",
    icon: Youtube,
    iconClassName: "text-red-600 bg-red-50 dark-tenant:bg-red-500/10 dark-tenant:text-red-400",
    description: "Long-form product and factory storytelling on YouTube.",
    comingSoon: true,
    troubleshooting: ["YouTube integration is on our roadmap."],
  },
  {
    key: "wechat",
    name: "WeChat",
    category: "messaging",
    icon: MessageCircle,
    iconClassName: "text-emerald-600 bg-emerald-50 dark-tenant:bg-emerald-500/10 dark-tenant:text-emerald-400",
    description: "China domestic buyer networks and WeChat Business messaging.",
    comingSoon: true,
    connectHref: "/wechat",
    troubleshooting: ["WeChat Business integration is coming soon."],
  },
  {
    key: "hubspot",
    name: "HubSpot",
    category: "crm",
    icon: Users,
    iconClassName: "text-orange-600 bg-orange-50 dark-tenant:bg-orange-500/10 dark-tenant:text-orange-400",
    description: "Sync leads, deals, and contacts with HubSpot CRM.",
    comingSoon: true,
    troubleshooting: ["HubSpot CRM sync is on our roadmap."],
  },
  {
    key: "salesforce",
    name: "Salesforce",
    category: "crm",
    icon: Cloud,
    iconClassName: "text-sky-700 bg-sky-50 dark-tenant:bg-sky-500/10 dark-tenant:text-sky-300",
    description: "Enterprise CRM sync for Salesforce accounts and opportunities.",
    comingSoon: true,
    troubleshooting: ["Salesforce integration is on our roadmap."],
  },
  {
    key: "zoho_crm",
    name: "Zoho CRM",
    category: "crm",
    icon: Users,
    iconClassName: "text-red-700 bg-red-50 dark-tenant:bg-red-500/10 dark-tenant:text-red-300",
    description: "Connect Zoho CRM for lead and pipeline synchronization.",
    comingSoon: true,
    troubleshooting: ["Zoho CRM integration is on our roadmap."],
  },
  {
    key: "alibaba",
    name: "Alibaba",
    category: "marketplace",
    icon: ShoppingBag,
    iconClassName: "text-orange-700 bg-orange-50 dark-tenant:bg-orange-500/10 dark-tenant:text-orange-300",
    description: "List and sync products on Alibaba.com marketplace.",
    comingSoon: true,
    troubleshooting: ["Alibaba marketplace sync is on our roadmap."],
  },
  {
    key: "made_in_china",
    name: "Made-in-China",
    category: "marketplace",
    icon: Globe,
    iconClassName: "text-red-600 bg-red-50 dark-tenant:bg-red-500/10 dark-tenant:text-red-400",
    description: "Export marketplace presence on Made-in-China.com.",
    comingSoon: true,
    troubleshooting: ["Made-in-China integration is on our roadmap."],
  },
  {
    key: "globalsources",
    name: "GlobalSources",
    category: "marketplace",
    icon: Globe,
    iconClassName: "text-indigo-600 bg-indigo-50 dark-tenant:bg-indigo-500/10 dark-tenant:text-indigo-400",
    description: "B2B sourcing marketplace integration for GlobalSources.",
    comingSoon: true,
    troubleshooting: ["GlobalSources integration is on our roadmap."],
  },
  {
    key: "google_drive",
    name: "Google Drive",
    category: "storage",
    icon: Cloud,
    iconClassName: "text-green-600 bg-green-50 dark-tenant:bg-green-500/10 dark-tenant:text-green-400",
    description: "Import and export media assets from Google Drive.",
    comingSoon: true,
    troubleshooting: ["Google Drive sync is on our roadmap."],
  },
  {
    key: "onedrive",
    name: "OneDrive",
    category: "storage",
    icon: Cloud,
    iconClassName: "text-blue-600 bg-blue-50 dark-tenant:bg-blue-500/10 dark-tenant:text-blue-400",
    description: "Connect Microsoft OneDrive for file storage and sharing.",
    comingSoon: true,
    troubleshooting: ["OneDrive integration is on our roadmap."],
  },
  {
    key: "dropbox",
    name: "Dropbox",
    category: "storage",
    icon: Cloud,
    iconClassName: "text-blue-700 bg-blue-50 dark-tenant:bg-blue-500/10 dark-tenant:text-blue-300",
    description: "Sync creative assets and documents via Dropbox.",
    comingSoon: true,
    troubleshooting: ["Dropbox integration is on our roadmap."],
  },
  {
    key: "google_analytics",
    name: "Google Analytics",
    category: "analytics",
    icon: BarChart3,
    iconClassName: "text-amber-600 bg-amber-50 dark-tenant:bg-amber-500/10 dark-tenant:text-amber-400",
    description: "Track landing page and campaign performance with GA4.",
    comingSoon: true,
    troubleshooting: ["Google Analytics integration is on our roadmap."],
  },
];

const ATTENTION_ACCOUNT_STATUSES = new Set([
  "expired",
  "invalid",
  "missing_permissions",
  "blocked",
  "disconnected",
]);

const ATTENTION_HEALTH_VALUES = new Set([
  "expired",
  "unhealthy",
  "missing_permissions",
  "disconnected",
  "not_configured",
]);

function accountNeedsAttention(account: PublishingAccount | undefined): boolean {
  if (!account) return false;
  if (ATTENTION_ACCOUNT_STATUSES.has(account.status)) return true;
  if (account.token_expired) return true;
  if (account.health && ATTENTION_HEALTH_VALUES.has(account.health)) return true;
  return false;
}

function metaNeedsAttention(meta: MetaConnectionSummary | undefined, platform: "facebook" | "instagram"): boolean {
  if (!meta) return false;
  if (meta.token_expired) return true;
  if (ATTENTION_HEALTH_VALUES.has(meta.health)) return true;
  const nested = platform === "facebook" ? meta.facebook : meta.instagram;
  if (!nested) return false;
  if (ATTENTION_ACCOUNT_STATUSES.has(nested.status)) return true;
  if (nested.health && ATTENTION_HEALTH_VALUES.has(nested.health)) return true;
  return (nested.blockers?.length ?? 0) > 0;
}

function resolveHealth(
  status: IntegrationStatus,
  account?: PublishingAccount,
  metaHealth?: string | null,
): IntegrationHealth {
  if (status === "coming_soon" || status === "not_connected") return "unknown";
  if (status === "attention_needed") return "unhealthy";
  if (account?.status === "mock" || metaHealth === "mock") return "degraded";
  if (account?.health === "healthy" || metaHealth === "healthy") return "healthy";
  if (account?.health) {
    if (account.health === "mock") return "degraded";
    if (ATTENTION_HEALTH_VALUES.has(account.health)) return "unhealthy";
  }
  if (metaHealth && ATTENTION_HEALTH_VALUES.has(metaHealth)) return "unhealthy";
  return status === "connected" ? "healthy" : "unknown";
}

function resolvePrimaryAction(status: IntegrationStatus, connectHref?: string): IntegrationPrimaryAction {
  if (status === "coming_soon") return "coming_soon";
  if (status === "attention_needed") return "reconnect";
  if (status === "connected") return "manage";
  return connectHref ? "connect" : "coming_soon";
}

export interface IntegrationDataContext {
  accounts: PublishingAccount[];
  meta?: MetaConnectionSummary | null;
  telegramConnected?: boolean;
  telegramGroupTitle?: string | null;
  readinessSteps?: { id: string; status: string }[];
}

function findAccount(accounts: PublishingAccount[], platform: string): PublishingAccount | undefined {
  return accounts.find((a) => a.platform === platform);
}

function stepCompleted(steps: { id: string; status: string }[] | undefined, id: string): boolean {
  return steps?.find((s) => s.id === id)?.status === "completed";
}

export function resolveIntegration(
  item: IntegrationCatalogItem,
  ctx: IntegrationDataContext,
): ResolvedIntegration {
  if (item.comingSoon) {
    return {
      ...item,
      status: "coming_soon",
      health: "unknown",
      primaryAction: "coming_soon",
    };
  }

  const account = item.publishingPlatform
    ? findAccount(ctx.accounts, item.key === "instagram" || item.key === "facebook" ? item.key : item.key)
    : item.key === "telegram"
      ? findAccount(ctx.accounts, "telegram")
      : undefined;

  let connected = false;
  let needsAttention = false;
  let lastSync: string | null | undefined;
  let accountName: string | null | undefined;
  let accountId: string | null | undefined;
  let permissions: string[] | undefined;
  let missingPermissions: string[] | undefined;
  let blockers: string[] | undefined;

  switch (item.key) {
    case "telegram": {
      const stepDone = stepCompleted(ctx.readinessSteps, "telegram_connected");
      connected = stepDone || !!ctx.telegramConnected || account?.status === "connected";
      needsAttention = accountNeedsAttention(account);
      lastSync = account?.updated_at;
      accountName = ctx.telegramGroupTitle ?? account?.account_name;
      accountId = account?.account_id;
      permissions = account?.permissions;
      missingPermissions = account?.missing_permissions;
      break;
    }
    case "facebook": {
      const stepDone = stepCompleted(ctx.readinessSteps, "facebook_connected");
      connected = stepDone || !!ctx.meta?.connected || account?.status === "connected";
      needsAttention = metaNeedsAttention(ctx.meta ?? undefined, "facebook") || accountNeedsAttention(account);
      lastSync = account?.updated_at ?? ctx.meta?.facebook?.expires_at ?? ctx.meta?.expires_at;
      accountName = ctx.meta?.facebook?.account_name ?? account?.account_name;
      accountId = ctx.meta?.facebook?.account_id ?? account?.account_id;
      permissions = ctx.meta?.facebook?.permissions ?? account?.permissions ?? ctx.meta?.permissions;
      missingPermissions =
        ctx.meta?.facebook?.missing_permissions ?? account?.missing_permissions ?? ctx.meta?.missing_permissions;
      blockers = ctx.meta?.facebook?.blockers ?? ctx.meta?.blockers;
      break;
    }
    case "instagram": {
      const stepDone = stepCompleted(ctx.readinessSteps, "instagram_connected");
      connected = stepDone || !!ctx.meta?.instagram?.publish_ready || account?.status === "connected";
      needsAttention = metaNeedsAttention(ctx.meta ?? undefined, "instagram") || accountNeedsAttention(account);
      lastSync = account?.updated_at;
      accountName = ctx.meta?.instagram?.account_name ?? account?.account_name;
      accountId = ctx.meta?.instagram?.account_id ?? account?.account_id;
      permissions = ctx.meta?.instagram?.permissions ?? account?.permissions;
      missingPermissions = ctx.meta?.instagram?.missing_permissions ?? account?.missing_permissions;
      blockers = ctx.meta?.instagram?.blockers;
      break;
    }
    case "linkedin":
    case "tiktok": {
      connected = account?.status === "connected" || account?.status === "mock";
      needsAttention = accountNeedsAttention(account);
      lastSync = account?.updated_at;
      accountName = account?.account_name;
      accountId = account?.account_id;
      permissions = account?.permissions;
      missingPermissions = account?.missing_permissions;
      break;
    }
    default:
      break;
  }

  const status: IntegrationStatus = connected
    ? needsAttention
      ? "attention_needed"
      : "connected"
    : "not_connected";

  const metaHealth =
    item.key === "facebook"
      ? ctx.meta?.facebook?.health ?? ctx.meta?.health
      : item.key === "instagram"
        ? ctx.meta?.instagram?.health ?? ctx.meta?.health
        : null;

  return {
    ...item,
    status,
    health: resolveHealth(status, account, metaHealth),
    primaryAction: resolvePrimaryAction(status, item.connectHref),
    lastSync,
    accountName,
    accountId,
    permissions,
    missingPermissions,
    blockers,
  };
}

export function resolveAllIntegrations(ctx: IntegrationDataContext): ResolvedIntegration[] {
  return INTEGRATION_CATALOG.map((item) => resolveIntegration(item, ctx));
}

export function filterIntegrationsByCategory(
  items: ResolvedIntegration[],
  category: IntegrationCategory,
): ResolvedIntegration[] {
  if (category === "all") return items;
  if (category === "coming_soon") return items.filter((i) => i.status === "coming_soon");
  return items.filter((i) => i.category === category);
}

export function computeIntegrationSummary(items: ResolvedIntegration[]) {
  const actionable = items.filter((i) => i.status !== "coming_soon");
  const connected = actionable.filter((i) => i.status === "connected");
  const attention = actionable.filter((i) => i.status === "attention_needed");
  const healthy = connected.filter((i) => i.health === "healthy").length;
  const degraded = connected.filter((i) => i.health === "degraded").length;

  const overallHealth: IntegrationHealth =
    attention.length > 0
      ? "unhealthy"
      : connected.length === 0
        ? "unknown"
        : degraded > 0
          ? "degraded"
          : "healthy";

  return {
    total: items.length,
    connectedCount: connected.length,
    attentionCount: attention.length,
    notConnectedCount: actionable.filter((i) => i.status === "not_connected").length,
    comingSoonCount: items.filter((i) => i.status === "coming_soon").length,
    overallHealth,
    connected,
    attention,
  };
}

export function formatRelativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export const STATUS_LABELS: Record<IntegrationStatus, string> = {
  connected: "Connected",
  not_connected: "Not Connected",
  attention_needed: "Attention Needed",
  coming_soon: "Coming Soon",
};

export const STATUS_STYLES: Record<IntegrationStatus, string> = {
  connected:
    "bg-emerald-100 text-emerald-700 dark-tenant:bg-emerald-500/15 dark-tenant:text-emerald-300",
  not_connected: "bg-slate-100 text-slate-600 dark-tenant:bg-white/[0.06] dark-tenant:text-slate-400",
  attention_needed:
    "bg-amber-100 text-amber-800 dark-tenant:bg-amber-500/15 dark-tenant:text-amber-300",
  coming_soon: "bg-slate-100 text-slate-500 dark-tenant:bg-white/[0.06] dark-tenant:text-slate-500",
};

export const HEALTH_STYLES: Record<IntegrationHealth, string> = {
  healthy: "bg-emerald-500",
  degraded: "bg-amber-500",
  unhealthy: "bg-red-500",
  unknown: "bg-slate-300 dark-tenant:bg-slate-600",
};

export const HEALTH_LABELS: Record<IntegrationHealth, string> = {
  healthy: "Healthy",
  degraded: "Degraded",
  unhealthy: "Unhealthy",
  unknown: "Unknown",
};

export const CATEGORY_LABELS: Record<Exclude<IntegrationCategory, "all">, string> = {
  social: "Social",
  messaging: "Messaging",
  crm: "CRM",
  marketplace: "Marketplace",
  storage: "Storage",
  analytics: "Analytics",
  coming_soon: "Coming Soon",
};
