/**
 * Single source of truth for dashboard route access and sidebar visibility.
 * Guards and navigation both derive rules from this map.
 */
import type { AdminRole } from "@/lib/api";
import type { TenantUserRole } from "@/lib/api";
import {
  hasStoredAdminToken,
  hasStoredTenantToken,
  readActiveSession,
} from "@/lib/session-sync";

/** Platform console — separate (admin) layout, always requires admin JWT. */
export const PLATFORM_CONSOLE_PATHS = [
  "/admin-users",
  "/admin-audit",
  "/admin-settings",
] as const;

/** Normal tenant sidebar visibility. Keep this narrower than route access. */
export const TENANT_NAV_PATHS = [
  "/dashboard",
  "/content",
  "/content-factory",
  "/media-library",
  "/publishing",
  "/calendar",
  "/crm",
  "/leads",
  "/customers",
  "/deals",
  "/proposals",
  "/buyers",
  "/communications",
  "/communications/inbox",
  "/communications/followups",
  "/communications/templates",
  "/wechat",
  "/whatsapp",
  "/growth-center",
  "/export-growth",
  "/customer-success",
  "/executive-copilot",
  "/billing",
  "/tenant-users",
] as const;

/** Platform/admin sidebar visibility. Routes remain separately guarded below. */
export const ADMIN_PLATFORM_NAV_PATHS = [
  "/tenants",
  "/billing",
  "/pilot-program",
  "/system-health",
  "/audit-logs",
  "/error-tracking",
  "/pilot-demo-mode",
  "/admin-settings",
] as const;

/** Internal pilot / platform ops — admin session only, hidden from tenants. */
export const PLATFORM_PILOT_PATHS = [
  "/pilot-demo-mode",
  "/pilot-demo",
  "/pilot-sales-demo",
  "/pilot-launch-validation",
  "/pilot-launch",
  "/pilot-onboarding",
  "/onboarding-admin",
  "/first-pilot-client",
  "/real-factory-pilot",
  "/production-deployment",
  "/factory-partners",
  "/factory-platform",
  "/customer-portal-v2",
  "/customer-portal",
  "/tenants",
  "/ai-command-center",
  "/operator-tasks",
  "/audit",
  "/system",
  "/pilot-program",
  "/system-health",
  "/audit-logs",
  "/error-tracking",
  "/pilot-success",
  "/launch-readiness",
] as const;

/** Tenant-safe business routes (sidebar + access for authenticated tenant users). */
export const TENANT_BUSINESS_PATHS = [
  "/dashboard",
  "/clients",
  "/content",
  "/calendar",
  "/publishing",
  "/campaigns",
  "/media-library",
  "/content-studio",
  "/pipeline",
  "/content-planner",
  "/content-factory",
  "/content-factory/generate",
  "/content-factory/review",
  "/repurpose",
  "/crm",
  "/proposals",
  "/partners",
  "/sales-assistant",
  "/sales-agent",
  "/sales-playbooks",
  "/sales-department",
  "/sales-department-v3",
  "/multi-agent",
  "/sales-manager",
  "/lead-intelligence",
  "/communications",
  "/communications/inbox",
  "/communications/followups",
  "/communications/templates",
  "/unified-inbox",
  "/communication-intelligence",
  "/wechat",
  "/wechat-sync",
  "/wechat-provider",
  "/whatsapp",
  "/whatsapp-sync",
  "/whatsapp-provider",
  "/inbox",
  "/buyer-acquisition",
  "/buyer-acquisition-engine",
  "/buyer-discovery",
  "/buyer-network",
  "/buyers",
  "/buyer-intelligence",
  "/marketplace",
  "/buyer-finder",
  "/outreach",
  "/deal-room",
  "/revenue-engine",
  "/deal-risk",
  "/revenue",
  "/revenue-attribution",
  "/products",
  "/export",
  "/landing-pages",
  "/attribution-links",
  "/workflows",
  "/tasks",
  "/analytics",
  "/billing",
  "/tenant-users",
  "/executive-copilot",
  "/briefs",
  "/sales",
  "/leads",
  "/deals",
  "/customers",
  "/growth-center",
  "/export-growth",
  "/customer-success",
  "/customer-success/roi",
  "/customer-success/adoption",
  "/customer-success/business-impact",
  "/business-matching",
  "/onboarding",
  "/feedback",
  "/demo-tour",
  "/value-demo",
  "/executive-demo",
  "/revenue-forecast",
  "/pilot-readiness",
] as const;

export const EXECUTIVE_COPILOT_PATH = "/executive-copilot";

export const TENANT_ROUTE_ROLE_REQUIREMENTS: Record<string, TenantUserRole[]> = {
  "/billing": ["owner", "manager"],
  "/tenant-users": ["owner", "manager"],
};

export const TENANT_ROUTE_PERMISSION_REQUIREMENTS: Record<string, string[]> = {
  "/executive-copilot": ["executive.copilot.view"],
};

export type RouteAuthContext = {
  authReady: boolean;
  isTenantAuthenticated: boolean;
  isAdminAuthenticated: boolean;
  tenantRole?: TenantUserRole | null;
  tenantPermissions?: string[];
  adminRole?: AdminRole | null;
  adminPermissions?: string[];
};

export type NavAudience = "loading" | "public" | "tenant" | "admin";

export type RouteAccessResult = {
  allowed: boolean;
  redirectTo?: string;
  reason?: "loading" | "admin_required" | "tenant_required" | "role_denied";
};

function pathMatches(pathname: string, prefix: string): boolean {
  return pathname === prefix || pathname.startsWith(`${prefix}/`);
}

function matchesAny(pathname: string, prefixes: readonly string[]): boolean {
  return prefixes.some((prefix) => pathMatches(pathname, prefix));
}

function longestMatchingPrefix(
  pathname: string,
  prefixes: readonly string[],
): string | null {
  let best: string | null = null;
  for (const prefix of prefixes) {
    if (pathMatches(pathname, prefix)) {
      if (!best || prefix.length > best.length) best = prefix;
    }
  }
  return best;
}

export function isPlatformConsolePath(pathname: string): boolean {
  return matchesAny(pathname, PLATFORM_CONSOLE_PATHS);
}

export function isPlatformPilotPath(pathname: string): boolean {
  return matchesAny(pathname, PLATFORM_PILOT_PATHS);
}

export function isTenantBusinessPath(pathname: string): boolean {
  return matchesAny(pathname, TENANT_BUSINESS_PATHS);
}

export function isExecutiveCopilotPath(pathname: string): boolean {
  return pathMatches(pathname, EXECUTIVE_COPILOT_PATH);
}

/** Legacy alias — platform/pilot routes that require an admin session in the dashboard shell. */
export function isAdminOnlyPath(pathname: string): boolean {
  return isPlatformPilotPath(pathname) || isPlatformConsolePath(pathname);
}

export function hasActiveAdminSession(): boolean {
  return readActiveSession() === "admin" && hasStoredAdminToken();
}

export function hasActiveTenantSession(): boolean {
  return readActiveSession() === "tenant" && hasStoredTenantToken();
}

function isEffectivelyAdminAuthenticated(ctx: RouteAuthContext): boolean {
  return ctx.isAdminAuthenticated;
}

function adminHasBusinessRead(ctx: RouteAuthContext): boolean {
  const perms = ctx.adminPermissions ?? [];
  if (perms.includes("platform.full")) return true;
  return perms.includes("business.read");
}

/** Admin session access to tenant business routes (deal-room, deal-risk, dashboard, etc.). */
export function adminCanAccessTenantBusinessRoutes(ctx: RouteAuthContext): boolean {
  if (!isEffectivelyAdminAuthenticated(ctx)) return false;

  const role = ctx.adminRole;
  if (role === "super_admin" || role === "platform_admin") return true;
  if (adminHasBusinessRead(ctx)) return true;

  // Active admin session but /me not hydrated yet — resolve now, re-check when user loads.
  if (ctx.isAdminAuthenticated && !role) return true;

  return false;
}

function resolveAuthReady(ctx: RouteAuthContext): boolean {
  return ctx.authReady;
}

function isEffectivelyTenantAuthenticated(ctx: RouteAuthContext): boolean {
  return ctx.isTenantAuthenticated;
}

export function getRouteRequiredPermissions(pathname: string): string[] {
  for (const [route, perms] of Object.entries(TENANT_ROUTE_PERMISSION_REQUIREMENTS)) {
    if (pathMatches(pathname, route)) return perms;
  }
  return [];
}

export function getTenantRequiredRoles(pathname: string): TenantUserRole[] | null {
  const prefix =
    longestMatchingPrefix(pathname, Object.keys(TENANT_ROUTE_ROLE_REQUIREMENTS)) ??
    longestMatchingPrefix(pathname, TENANT_BUSINESS_PATHS);
  if (!prefix) return null;
  for (const [route, roles] of Object.entries(TENANT_ROUTE_ROLE_REQUIREMENTS)) {
    if (pathMatches(pathname, route)) return roles;
  }
  return null;
}

function tenantHasPermission(permissions: string[] | undefined, permission: string): boolean {
  if (!permissions) return false;
  if (permissions.includes("tenant.full")) return true;
  return permissions.includes(permission);
}

function tenantHasRole(role: TenantUserRole | null | undefined, roles: TenantUserRole[]): boolean {
  if (!role) return false;
  if (role === "owner") return true;
  return roles.includes(role);
}

function tenantHasRouteRoles(pathname: string, role: TenantUserRole | null | undefined): boolean {
  const required = getTenantRequiredRoles(pathname);
  if (!required) return true;
  return tenantHasRole(role, required);
}

function tenantHasRoutePermissions(
  pathname: string,
  permissions: string[] | undefined,
): boolean {
  for (const [route, requiredPerms] of Object.entries(TENANT_ROUTE_PERMISSION_REQUIREMENTS)) {
    if (!pathMatches(pathname, route)) continue;
    return requiredPerms.some((perm) => tenantHasPermission(permissions, perm));
  }
  return true;
}

function tenantHasExecutiveAccess(ctx: RouteAuthContext): boolean {
  if (!ctx.isTenantAuthenticated) return false;
  if (ctx.tenantRole === "owner") return true;
  return tenantHasPermission(ctx.tenantPermissions, "executive.copilot.view");
}

/**
 * Resolve sidebar / session mode. When both tokens are present, honor the last
 * explicit login (ACTIVE_SESSION_KEY). Without a marker, prefer tenant so a
 * stale admin token cannot expose pilot/platform nav to tenant users.
 */
export function resolveNavAudience(ctx: Pick<
  RouteAuthContext,
  "authReady" | "isTenantAuthenticated" | "isAdminAuthenticated"
>): NavAudience {
  if (!ctx.authReady) return "loading";

  const tenant = isEffectivelyTenantAuthenticated(ctx);
  const admin = isEffectivelyAdminAuthenticated(ctx);

  if (tenant && admin) {
    const active = readActiveSession();
    if (active === "admin") return "admin";
    if (active === "tenant") return "tenant";
    return "tenant";
  }

  if (admin) return "admin";
  if (tenant) return "tenant";
  return "public";
}

export function isNavItemVisible(href: string, ctx: RouteAuthContext): boolean {
  const audience = resolveNavAudience(ctx);

  if (audience === "admin") {
    return matchesAny(href, ADMIN_PLATFORM_NAV_PATHS);
  }

  if (isPlatformPilotPath(href) || isPlatformConsolePath(href)) return false;

  if (isExecutiveCopilotPath(href)) {
    return audience === "tenant" && tenantHasExecutiveAccess(ctx);
  }

  if (!matchesAny(href, TENANT_NAV_PATHS)) return false;
  if (!isTenantBusinessPath(href)) return false;

  if (audience === "tenant") {
    return (
      tenantHasRouteRoles(href, ctx.tenantRole ?? null) &&
      tenantHasRoutePermissions(href, ctx.tenantPermissions)
    );
  }

  // loading + public: fail closed — only show tenant-safe business links (owner-level)
  if (isExecutiveCopilotPath(href)) return false;
  if (!isTenantBusinessPath(href)) return false;
  return tenantHasRouteRoles(href, "owner");
}

export function filterNavItems<T extends { href: string }>(items: T[], ctx: RouteAuthContext): T[] {
  return items.filter((item) => isNavItemVisible(item.href, ctx));
}

/** Tenant-safe items from the pilot nav block — relabeled for client-facing sidebars. */
const PILOT_SECTION_TENANT_COMPANY_PATHS = new Set(["/tenant-users", "/billing"]);

/** Client-facing section titles — no internal pilot/admin wording for tenants. */
const TENANT_SECTION_LABELS: Record<string, string> = {
  "nav.sectionExecutive": "nav.sectionTenantOverview",
  "nav.sectionPilot": "nav.sectionCompany",
  "nav.sectionBuyers": "nav.sectionTenantMarket",
  "nav.sectionSales": "nav.sectionTenantSales",
  "nav.sectionCommunications": "nav.sectionTenantMessages",
  "nav.sectionContent": "nav.sectionTenantContent",
  "nav.sectionPlatform": "nav.sectionTenantTools",
};

/**
 * Resolve sidebar section title from audience. Pilot block items visible to tenants
 * (tenant-users, billing) use a company label instead of internal "Pilot & Tenants".
 */
export function resolveSectionLabelKey(
  sectionKey: string,
  visibleItems: readonly { href: string }[],
  audience: NavAudience,
): string {
  if (audience === "tenant") {
    if (sectionKey === "nav.sectionPilot" && visibleItems.length > 0) {
      const onlyCompanyItems = visibleItems.every((item) =>
        PILOT_SECTION_TENANT_COMPANY_PATHS.has(item.href),
      );
      if (onlyCompanyItems) return "nav.sectionCompany";
    }
    return TENANT_SECTION_LABELS[sectionKey] ?? sectionKey;
  }

  if (sectionKey !== "nav.sectionPilot") return sectionKey;
  if (visibleItems.length === 0) return sectionKey;
  const onlyCompanyItems = visibleItems.every((item) =>
    PILOT_SECTION_TENANT_COMPANY_PATHS.has(item.href),
  );
  if (onlyCompanyItems) return "nav.sectionCompany";
  return sectionKey;
}

export function requiresTenantAuth(pathname: string): boolean {
  if (isPlatformPilotPath(pathname) || isPlatformConsolePath(pathname)) return false;
  if (isExecutiveCopilotPath(pathname)) return true;
  return isTenantBusinessPath(pathname);
}

export function evaluateRouteAccess(pathname: string, ctx: RouteAuthContext): RouteAccessResult {
  const authReady = resolveAuthReady(ctx);
  const readyCtx: RouteAuthContext = { ...ctx, authReady: true };

  if (!authReady) {
    if (
      isPlatformPilotPath(pathname) ||
      isPlatformConsolePath(pathname) ||
      isExecutiveCopilotPath(pathname) ||
      (isTenantBusinessPath(pathname) && requiresTenantAuth(pathname))
    ) {
      return { allowed: false, reason: "loading" };
    }
    return { allowed: true };
  }

  const audience = resolveNavAudience(readyCtx);

  if (audience === "admin") {
    if (isPlatformConsolePath(pathname) || isPlatformPilotPath(pathname)) {
      return { allowed: true };
    }
    if (isTenantBusinessPath(pathname) || isExecutiveCopilotPath(pathname)) {
      if (adminCanAccessTenantBusinessRoutes(readyCtx)) return { allowed: true };
      return { allowed: false, redirectTo: "/dashboard", reason: "role_denied" };
    }
    return { allowed: true };
  }

  if (isPlatformConsolePath(pathname) || isPlatformPilotPath(pathname)) {
    if (ctx.isTenantAuthenticated) {
      return { allowed: false, redirectTo: "/dashboard", reason: "admin_required" };
    }
    return {
      allowed: false,
      redirectTo: `/admin-login?next=${encodeURIComponent(pathname)}`,
      reason: "admin_required",
    };
  }

  if (isExecutiveCopilotPath(pathname)) {
    if (adminCanAccessTenantBusinessRoutes(readyCtx)) return { allowed: true };
    if (ctx.isTenantAuthenticated) {
      if (tenantHasExecutiveAccess(ctx)) return { allowed: true };
      return { allowed: false, redirectTo: "/dashboard", reason: "role_denied" };
    }
    return {
      allowed: false,
      redirectTo: `/login?next=${encodeURIComponent(pathname)}`,
      reason: "tenant_required",
    };
  }

  if (isTenantBusinessPath(pathname)) {
    if (adminCanAccessTenantBusinessRoutes(readyCtx)) return { allowed: true };

    if (!ctx.isTenantAuthenticated && hasActiveTenantSession()) {
      return { allowed: false, reason: "loading" };
    }

    if (!ctx.isTenantAuthenticated) {
      return {
        allowed: false,
        redirectTo: `/login?next=${encodeURIComponent(pathname)}`,
        reason: "tenant_required",
      };
    }
    if (!tenantHasRouteRoles(pathname, ctx.tenantRole ?? null)) {
      return { allowed: false, redirectTo: "/dashboard", reason: "role_denied" };
    }
    if (!tenantHasRoutePermissions(pathname, ctx.tenantPermissions)) {
      return { allowed: false, redirectTo: "/dashboard", reason: "role_denied" };
    }
    return { allowed: true };
  }

  return { allowed: true };
}

export const ADMIN_DEFAULT_LANDING = "/dashboard";

export function resolveAdminPostLoginPath(_next: string | null | undefined): string {
  return ADMIN_DEFAULT_LANDING;
}
