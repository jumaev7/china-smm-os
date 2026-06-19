/**
 * Navigation and route access — re-exports from route-permissions (single source of truth).
 */
export {
  ADMIN_DEFAULT_LANDING,
  ADMIN_PLATFORM_NAV_PATHS,
  EXECUTIVE_COPILOT_PATH,
  PLATFORM_CONSOLE_PATHS,
  PLATFORM_PILOT_PATHS,
  TENANT_BUSINESS_PATHS,
  TENANT_NAV_PATHS,
  TENANT_ROUTE_ROLE_REQUIREMENTS,
  evaluateRouteAccess,
  filterNavItems,
  getTenantRequiredRoles,
  isAdminOnlyPath,
  isExecutiveCopilotPath,
  isNavItemVisible,
  isPlatformConsolePath,
  isPlatformPilotPath,
  isTenantBusinessPath,
  requiresTenantAuth,
  resolveAdminPostLoginPath,
  resolveNavAudience,
  resolveSectionLabelKey,
  type NavAudience,
  type RouteAccessResult,
  type RouteAuthContext,
} from "@/lib/route-permissions";

/** @deprecated Use PLATFORM_PILOT_PATHS — kept for imports that expect ADMIN_ONLY_PATHS */
export { PLATFORM_PILOT_PATHS as ADMIN_ONLY_PATHS } from "@/lib/route-permissions";

/** @deprecated Use TENANT_BUSINESS_PATHS */
export { TENANT_BUSINESS_PATHS as TENANT_VISIBLE_PATHS } from "@/lib/route-permissions";

export type NavAuthGates = import("@/lib/route-permissions").RouteAuthContext;
