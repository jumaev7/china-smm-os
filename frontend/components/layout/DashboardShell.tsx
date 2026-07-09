"use client";



import Link from "next/link";

import { Suspense, useEffect, useMemo, useState } from "react";

import { usePathname, useSearchParams } from "next/navigation";

import {

  Users,

  FileText,

  Calendar,

  CalendarClock,

  CalendarDays,

  BarChart3,

  Zap,

  Building2,

  Radio,

  RefreshCw,

  ListOrdered,

  Inbox as InboxIcon,

  CreditCard,

  ClipboardList,

  ClipboardPen,

  ListTodo,

  Factory,

  Contact,

  LayoutDashboard,

  CircleDollarSign,

  TrendingUp,

  Handshake,

  Bot,

  Sparkles,

  Activity,

  ClipboardCheck,

  Package,

  Globe,

  Megaphone,

  Images,

  Columns3,

  Layers,

  MessagesSquare,

  Link2,

  LayoutTemplate,

  Search,

  Send,

  Terminal,

  FileSignature,

  MessageCircle,

  Mail,

  Phone,

  Brain,

  Workflow,

  Crown,

  Briefcase,

  Kanban,

  UsersRound,

  Target,

  ShieldAlert,

  Network,

  Rocket,

  Cloud,

  Presentation,

  Server,

  Store,

  Shield,

  Settings,

  Plug,

  type LucideIcon,

} from "lucide-react";

import { cn } from "@/lib/utils";

import { FloatingAssistant } from "@/components/assistant/FloatingAssistant";

import { ContextAiAssistant } from "@/components/assistant/ContextAiAssistant";

import { AiCommandPageProvider } from "@/lib/useAiCommandContext";

import { LanguageSwitcher } from "@/components/i18n/LanguageSwitcher";

import { UserMenu } from "@/components/auth/UserMenu";

import { DemoModeToggle } from "@/components/demo/DemoModeToggle";

import { useTranslation } from "@/lib/I18nProvider";
import { useDocumentInteractionCleanup } from "@/lib/useDocumentInteractionCleanup";
import { useAdminAuth } from "@/lib/admin-auth-store";
import { useAuth } from "@/lib/auth-store";
import { filterNavItems, resolveNavAudience, resolveSectionLabelKey } from "@/lib/nav-access";
import { computeSessionAwareAuthReady } from "@/lib/session-sync";
import { useDashboardOverlayCleanup } from "@/lib/useDashboardOverlayCleanup";



type NavItem = { href: string; icon: LucideIcon; labelKey: string };

type NavSection = { sectionKey: string; items: NavItem[] };



const NAV_SECTIONS: NavSection[] = [

  {

    sectionKey: "nav.sectionExecutive",

    items: [

      { href: "/dashboard", icon: LayoutDashboard, labelKey: "nav.dashboard" },

      { href: "/onboarding", icon: Rocket, labelKey: "nav.factoryOnboarding" },

      { href: "/demo-tour", icon: Presentation, labelKey: "nav.demoTour" },

      { href: "/value-demo", icon: Target, labelKey: "nav.valueDemo" },

      { href: "/executive-demo", icon: Crown, labelKey: "nav.executiveDemo" },

      { href: "/executive-copilot", icon: Crown, labelKey: "nav.executiveCopilot" },

      { href: "/growth-center", icon: BarChart3, labelKey: "nav.growthCenter" },

      { href: "/customer-success", icon: Sparkles, labelKey: "nav.customerSuccess" },

      { href: "/export-growth", icon: Globe, labelKey: "nav.exportGrowth" },

      { href: "/business-matching", icon: Handshake, labelKey: "nav.businessMatching" },

      { href: "/deal-room", icon: Briefcase, labelKey: "nav.dealRoom" },

      { href: "/revenue-forecast", icon: TrendingUp, labelKey: "nav.revenueForecast" },

      { href: "/revenue-engine", icon: CircleDollarSign, labelKey: "nav.revenueEngine" },

      { href: "/deal-risk", icon: ShieldAlert, labelKey: "nav.dealRisk" },

    ],

  },

  {

    sectionKey: "nav.sectionPilot",

    items: [

      { href: "/pilot-demo", icon: Rocket, labelKey: "nav.pilotDemo" },
      { href: "/pilot-demo-mode", icon: Presentation, labelKey: "nav.pilotDemoMode" },

      { href: "/pilot-sales-demo", icon: Presentation, labelKey: "nav.pilotSalesDemo" },
      { href: "/pilot-launch-validation", icon: ClipboardCheck, labelKey: "nav.pilotLaunchValidation" },

      { href: "/pilot-readiness", icon: ClipboardCheck, labelKey: "nav.pilotReadiness" },

      { href: "/pilot-launch", icon: Rocket, labelKey: "nav.pilotLaunch" },

      { href: "/pilot-onboarding", icon: Rocket, labelKey: "nav.pilotOnboarding" },
      { href: "/onboarding-admin", icon: BarChart3, labelKey: "nav.onboardingAdmin" },
      { href: "/first-pilot-client", icon: Rocket, labelKey: "nav.firstPilotClient" },
      { href: "/real-factory-pilot", icon: Factory, labelKey: "nav.realFactoryPilot" },
      { href: "/production-deployment", icon: Cloud, labelKey: "nav.productionDeployment" },
      { href: "/pilot-program", icon: Factory, labelKey: "nav.pilotProgram" },
      { href: "/pilot-success", icon: TrendingUp, labelKey: "nav.pilotSuccess" },
      { href: "/launch-readiness", icon: ClipboardCheck, labelKey: "nav.launchReadiness" },
      { href: "/feedback", icon: MessagesSquare, labelKey: "nav.feedback" },
      { href: "/system-health", icon: Activity, labelKey: "nav.systemHealth" },
      { href: "/audit-logs", icon: Shield, labelKey: "nav.auditLogs" },
      { href: "/error-tracking", icon: ShieldAlert, labelKey: "nav.errorTracking" },

      { href: "/factory-partners", icon: Factory, labelKey: "nav.factoryPartners" },

      { href: "/factory-platform", icon: Factory, labelKey: "nav.factoryPlatform" },

      { href: "/customer-portal-v2", icon: Sparkles, labelKey: "nav.customerPortalV2" },

      { href: "/customer-portal", icon: Building2, labelKey: "nav.customerPortal" },

      { href: "/tenants", icon: Network, labelKey: "nav.tenants" },

      { href: "/tenant-users", icon: Users, labelKey: "nav.tenantUsers" },

      { href: "/billing", icon: CreditCard, labelKey: "nav.billing" },

    ],

  },

  {

    sectionKey: "nav.sectionBuyers",

    items: [

      { href: "/buyer-acquisition", icon: Layers, labelKey: "nav.buyerAcquisition" },

      { href: "/buyer-acquisition-engine", icon: Target, labelKey: "nav.buyerAcquisitionEngine" },

      { href: "/buyer-discovery", icon: Search, labelKey: "nav.buyerDiscovery" },

      { href: "/buyers", icon: Building2, labelKey: "nav.buyers" },

      { href: "/buyer-network", icon: Network, labelKey: "nav.buyerNetwork" },

      { href: "/buyer-intelligence", icon: Target, labelKey: "nav.buyerIntelligence" },

      { href: "/marketplace", icon: Store, labelKey: "nav.marketplace" },

      { href: "/buyer-finder", icon: Search, labelKey: "nav.buyerFinder" },

      { href: "/outreach", icon: Send, labelKey: "nav.outreach" },

    ],

  },

  {

    sectionKey: "nav.sectionSales",

    items: [

      { href: "/sales", icon: TrendingUp, labelKey: "nav.salesDashboard" },

      { href: "/crm-pipeline", icon: Kanban, labelKey: "nav.crmPipeline" },

      { href: "/leads", icon: Contact, labelKey: "nav.leads" },

      { href: "/deals", icon: Briefcase, labelKey: "nav.deals" },

      { href: "/customers", icon: Users, labelKey: "nav.customers" },

      { href: "/sales-department", icon: Building2, labelKey: "nav.salesDepartment" },

      { href: "/sales-department-v3", icon: Building2, labelKey: "nav.salesDepartmentV3" },

      { href: "/multi-agent", icon: UsersRound, labelKey: "nav.multiAgentTeam" },

      { href: "/sales-manager", icon: LayoutDashboard, labelKey: "nav.salesManager" },

      { href: "/lead-intelligence", icon: Brain, labelKey: "nav.leadIntelligence" },

      { href: "/crm", icon: Contact, labelKey: "nav.crm" },

      { href: "/proposals", icon: FileSignature, labelKey: "nav.proposals" },

      { href: "/partners", icon: Handshake, labelKey: "nav.partners" },

      { href: "/sales-playbooks", icon: ClipboardList, labelKey: "nav.salesPlaybooks" },

      { href: "/sales-assistant", icon: Sparkles, labelKey: "nav.salesAssistant" },

      { href: "/sales-agent", icon: Bot, labelKey: "nav.salesAgent" },

    ],

  },

  {

    sectionKey: "nav.sectionCommunications",

    items: [

      { href: "/communications", icon: MessagesSquare, labelKey: "nav.communicationsHub" },

      { href: "/communications/inbox", icon: InboxIcon, labelKey: "nav.communicationsInbox" },

      { href: "/communications/followups", icon: CalendarClock, labelKey: "nav.communicationsFollowups" },

      { href: "/communications/templates", icon: FileText, labelKey: "nav.communicationsTemplates" },

      { href: "/unified-inbox", icon: Mail, labelKey: "nav.unifiedInbox" },

      { href: "/communication-intelligence", icon: MessagesSquare, labelKey: "nav.communicationIntelligence" },

      { href: "/wechat", icon: MessageCircle, labelKey: "nav.wechatCenter" },

      { href: "/wechat-sync", icon: RefreshCw, labelKey: "nav.wechatSync" },

      { href: "/wechat-provider", icon: Server, labelKey: "nav.wechatProvider" },

      { href: "/whatsapp", icon: Phone, labelKey: "nav.whatsappCenter" },

      { href: "/whatsapp-sync", icon: RefreshCw, labelKey: "nav.whatsappSync" },

      { href: "/whatsapp-provider", icon: Server, labelKey: "nav.whatsappProvider" },

      { href: "/inbox", icon: InboxIcon, labelKey: "nav.inbox" },

    ],

  },

  {

    sectionKey: "nav.sectionContent",

    items: [

      { href: "/clients", icon: Users, labelKey: "nav.clients" },

      { href: "/briefs", icon: ClipboardPen, labelKey: "nav.clientBriefs" },

      { href: "/content", icon: FileText, labelKey: "nav.content" },

      { href: "/pipeline", icon: Columns3, labelKey: "nav.pipeline" },

      { href: "/campaigns", icon: Megaphone, labelKey: "nav.campaigns" },

      { href: "/content-studio", icon: Sparkles, labelKey: "nav.contentStudio" },

      { href: "/repurpose", icon: Layers, labelKey: "nav.repurpose" },

      { href: "/media-library", icon: Images, labelKey: "nav.mediaLibrary" },

      { href: "/content-planner", icon: ClipboardList, labelKey: "nav.contentPlanner" },

      { href: "/content-factory", icon: Factory, labelKey: "nav.contentFactory" },

      { href: "/calendar", icon: Calendar, labelKey: "nav.calendar" },

      { href: "/publishing", icon: Radio, labelKey: "nav.publishing" },

      { href: "/publishing/calendar", icon: CalendarDays, labelKey: "nav.publishCalendar" },

      { href: "/publishing/queue", icon: ListOrdered, labelKey: "nav.publishingQueue" },

    ],

  },

  {

    sectionKey: "nav.sectionPlatform",

    items: [

      { href: "/products", icon: Package, labelKey: "nav.products" },

      { href: "/export", icon: Globe, labelKey: "nav.exportAgent" },

      { href: "/landing-pages", icon: LayoutTemplate, labelKey: "nav.landingPages" },

      { href: "/attribution-links", icon: Link2, labelKey: "nav.attributionLinks" },

      { href: "/revenue", icon: CircleDollarSign, labelKey: "nav.revenue" },

      { href: "/revenue-attribution", icon: TrendingUp, labelKey: "nav.revenueAttribution" },

      { href: "/workflows", icon: Workflow, labelKey: "nav.workflows" },

      { href: "/ai-command-center", icon: Terminal, labelKey: "nav.aiCommandCenter" },

      { href: "/tasks", icon: ListTodo, labelKey: "nav.tasks" },

      { href: "/operator-tasks", icon: ListTodo, labelKey: "nav.operatorTasks" },

      { href: "/analytics", icon: BarChart3, labelKey: "nav.analytics" },

      { href: "/audit", icon: ClipboardCheck, labelKey: "nav.audit" },

      { href: "/system", icon: Activity, labelKey: "nav.system" },

      { href: "/system/stability", icon: Activity, labelKey: "nav.systemStability" },

    ],

  },

];

const TENANT_SIMPLIFIED_NAV_SECTIONS: NavSection[] = [
  {
    sectionKey: "nav.sectionTenantOverview",
    items: [
      { href: "/dashboard", icon: LayoutDashboard, labelKey: "nav.dashboard" },
      { href: "/executive-copilot", icon: Bot, labelKey: "nav.aiAssistant" },
    ],
  },
  {
    sectionKey: "nav.sectionContent",
    items: [
      { href: "/content", icon: FileText, labelKey: "nav.content" },
      { href: "/pipeline", icon: Columns3, labelKey: "nav.pipeline" },
      { href: "/content-factory", icon: Factory, labelKey: "nav.contentFactory" },
      { href: "/media-library", icon: Images, labelKey: "nav.mediaLibrary" },
      { href: "/publishing", icon: Radio, labelKey: "nav.publishing" },
      { href: "/calendar", icon: Calendar, labelKey: "nav.calendar" },
    ],
  },
  {
    sectionKey: "nav.sectionTenantSales",
    items: [
      { href: "/crm-pipeline", icon: Kanban, labelKey: "nav.crmPipeline" },
      { href: "/crm", icon: Contact, labelKey: "nav.crm" },
      { href: "/leads", icon: Contact, labelKey: "nav.leads" },
      { href: "/customers", icon: Users, labelKey: "nav.customers" },
      { href: "/deals", icon: Briefcase, labelKey: "nav.deals" },
      { href: "/proposals", icon: FileSignature, labelKey: "nav.proposals" },
      { href: "/buyers", icon: Building2, labelKey: "nav.buyers" },
      { href: "/communications", icon: MessagesSquare, labelKey: "nav.communications" },
      { href: "/communications/inbox", icon: InboxIcon, labelKey: "nav.communicationsInbox" },
      { href: "/communications/followups", icon: CalendarClock, labelKey: "nav.communicationsFollowups" },
      { href: "/communications/templates", icon: FileText, labelKey: "nav.communicationsTemplates" },
      { href: "/wechat", icon: MessageCircle, labelKey: "nav.wechatCenter" },
      { href: "/whatsapp", icon: Phone, labelKey: "nav.whatsappCenter" },
    ],
  },
  {
    sectionKey: "nav.sectionTenantAnalytics",
    items: [
      { href: "/analytics", icon: BarChart3, labelKey: "nav.analytics" },
      { href: "/growth-center", icon: TrendingUp, labelKey: "nav.growthCenter" },
      { href: "/export-growth", icon: Globe, labelKey: "nav.exportGrowth" },
      { href: "/customer-success", icon: Sparkles, labelKey: "nav.customerSuccess" },
    ],
  },
  {
    sectionKey: "nav.sectionTenantSettings",
    items: [
      { href: "/integrations", icon: Plug, labelKey: "nav.integrations" },
      { href: "/tenant-users", icon: Users, labelKey: "nav.tenantUsers" },
      { href: "/billing", icon: CreditCard, labelKey: "nav.billing" },
    ],
  },
];

const ADMIN_PLATFORM_NAV_SECTIONS: NavSection[] = [
  {
    sectionKey: "nav.sectionPlatformAdmin",
    items: [
      { href: "/tenants", icon: Network, labelKey: "nav.tenants" },
      { href: "/billing", icon: CreditCard, labelKey: "nav.billing" },
      { href: "/billing?tab=plans", icon: ListOrdered, labelKey: "nav.plans" },
      { href: "/billing?tab=licenses", icon: Shield, labelKey: "nav.licenses" },
      { href: "/pilot-program", icon: Factory, labelKey: "nav.pilotProgram" },
      { href: "/system-health", icon: Activity, labelKey: "nav.systemHealth" },
      { href: "/audit-logs", icon: ClipboardCheck, labelKey: "nav.auditLogs" },
      { href: "/error-tracking", icon: ShieldAlert, labelKey: "nav.errorTracking" },
      { href: "/pilot-demo-mode", icon: Presentation, labelKey: "nav.demoManagement" },
      { href: "/admin-settings", icon: Settings, labelKey: "nav.platformSettings" },
    ],
  },
];



const SECTION_LABEL_FALLBACK: Record<string, string> = {

  "nav.sectionExecutive": "Executive",

  "nav.sectionPilot": "Pilot & Tenants",

  "nav.sectionCompany": "Company Settings",

  "nav.sectionBuyers": "Buyers & Market",

  "nav.sectionSales": "Sales & CRM",

  "nav.sectionCommunications": "Communications",

  "nav.sectionContent": "Content & Publishing",

  "nav.sectionPlatform": "Platform",
  "nav.sectionTenantDashboard": "Dashboard",
  "nav.sectionTenantOverview": "Overview",
  "nav.sectionTenantMarket": "Market & Outreach",
  "nav.sectionTenantSales": "Sales & Buyers",
  "nav.sectionTenantMessages": "Messages",
  "nav.sectionTenantContent": "Content & Publishing",
  "nav.sectionTenantGrowth": "Growth",
  "nav.sectionTenantAnalytics": "Analytics",
  "nav.sectionTenantSettings": "Settings & Billing",
  "nav.sectionTenantTools": "Tools & Analytics",
  "nav.sectionPlatformAdmin": "Platform Admin",
  "nav.settings": "Settings",

};



function communicationsNavMatches(pathname: string, path: string): boolean {
  if (path === "/communications") {
    return pathname === "/communications";
  }
  if (path === "/communications/inbox") {
    return (
      pathname === "/communications/inbox" ||
      pathname.startsWith("/communications/inbox/") ||
      pathname.startsWith("/communications/threads/") ||
      pathname.startsWith("/communications/contacts/")
    );
  }
  return pathname === path || pathname.startsWith(`${path}/`);
}

function navIsActive(pathname: string, href: string, searchParams: URLSearchParams): boolean {
  const [path, queryString] = href.split("?");
  const pathMatches = path === "/publishing"
    ? pathname === "/publishing"
    : path.startsWith("/communications")
      ? communicationsNavMatches(pathname, path)
      : pathname === path || pathname.startsWith(`${path}/`);

  if (!pathMatches) return false;
  if (!queryString) {
    if (path === "/billing") {
      const tab = searchParams.get("tab");
      return !tab || tab === "overview";
    }
    return true;
  }
  const expected = new URLSearchParams(queryString);
  for (const [key, value] of expected.entries()) {
    if (searchParams.get(key) !== value) return false;
  }
  return true;
}



export function DashboardShell({ children }: { children: React.ReactNode }) {

  const pathname = usePathname();
  const searchParams = useSearchParams();

  const { t } = useTranslation();
  const { isAuthenticated: isTenantAuthenticated, loading: tenantLoading, user: tenantUser, permissions: tenantPermissions } = useAuth();
  const { isAuthenticated: isAdminAuthenticated, loading: adminLoading, user: adminUser, permissions: adminPermissions } = useAdminAuth();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  const authReady = mounted && computeSessionAwareAuthReady(tenantLoading, adminLoading);

  const navGates = useMemo(
    () => ({
      authReady,
      isTenantAuthenticated,
      isAdminAuthenticated,
      tenantRole: tenantUser?.role ?? null,
      tenantPermissions,
      adminRole: adminUser?.role ?? null,
      adminPermissions,
    }),
    [
      authReady,
      isTenantAuthenticated,
      isAdminAuthenticated,
      tenantUser?.role,
      tenantPermissions,
      adminUser?.role,
      adminPermissions,
    ],
  );

  const navAudience = resolveNavAudience(navGates);
  const navSections =
    navAudience === "loading"
      ? []
      : navAudience === "tenant"
      ? TENANT_SIMPLIFIED_NAV_SECTIONS
      : navAudience === "admin"
        ? ADMIN_PLATFORM_NAV_SECTIONS
        : NAV_SECTIONS;

  useDocumentInteractionCleanup(pathname);
  useDashboardOverlayCleanup(authReady);



  const sectionLabel = (key: string) => {

    const translated = t(key);

    return translated === key ? SECTION_LABEL_FALLBACK[key] ?? key : translated;

  };



  const isTenantNav = navAudience === "tenant";

  return (

    <div
      data-dashboard-shell
      data-tenant-theme={isTenantNav ? "dark" : undefined}
      className={cn(
        "flex h-screen overflow-hidden",
        isTenantNav ? "bg-surface-dark-page" : "bg-slate-50",
      )}
    >

      <aside className={cn(
        "w-60 shrink-0 flex flex-col shadow-sidebar",
        isTenantNav
          ? "border-r border-white/[0.06] bg-[#070b14]"
          : "border-r border-navy-800/20 bg-navy-900",
      )}>

        <div className={cn(
          "flex items-center gap-3 px-4 py-4 border-b",
          isTenantNav ? "border-white/[0.06]" : "border-white/10",
        )}>

          <div className={cn(
            "w-9 h-9 rounded-xl flex items-center justify-center shadow-md ring-1",
            isTenantNav
              ? "bg-gradient-to-br from-violet-600 to-brand-700 ring-violet-500/20"
              : "bg-gradient-to-br from-brand-500 to-brand-700 ring-white/10",
          )}>

            <Zap size={16} className="text-white" />

          </div>

          <div className="min-w-0">

            <div className="text-sm font-semibold text-white leading-tight truncate">{t("app.name")}</div>

            <div className="text-[10px] text-slate-500 leading-tight">{t("app.version")}</div>

          </div>

        </div>

        <nav className="flex-1 px-2.5 py-3 overflow-y-auto scrollbar-thin">

          {navSections.map(({ sectionKey, items }) => {
            const visibleItems = filterNavItems(items, navGates);
            if (visibleItems.length === 0) return null;

            return (
            <div key={sectionKey} className="mb-2">

              <p className={cn(
                "px-3 pt-3 pb-1.5 text-[10px] font-semibold uppercase tracking-widest",
                isTenantNav ? "text-slate-500" : "nav-section-label",
              )}>
                {sectionLabel(resolveSectionLabelKey(sectionKey, visibleItems, navAudience))}
              </p>

              <div className="space-y-0.5">

                {visibleItems.map(({ href, icon: Icon, labelKey }) => {

                  const active = navIsActive(pathname, href, searchParams);

                  return (

                    <Link

                      key={`${href}-${labelKey}`}

                      href={href}

                      className={cn(
                        active ? "nav-link-active" : "nav-link-inactive",
                        isTenantNav && active && "bg-violet-500/15 border-l-2 border-violet-400 pl-[10px]",
                        isTenantNav && !active && "text-slate-400 hover:text-slate-100 hover:bg-white/[0.04]",
                      )}

                    >

                      <Icon size={16} className={cn(
                        "shrink-0",
                        active && (isTenantNav ? "text-violet-400" : "text-accent-cyan"),
                      )} />

                      <span className="truncate">{t(labelKey)}</span>

                    </Link>

                  );

                })}

              </div>

            </div>
            );
          })}

        </nav>



        <div className={cn(
          "px-4 py-3 border-t",
          isTenantNav ? "border-white/[0.06]" : "border-white/10",
        )}>

          <div className="flex items-center gap-2 text-[10px] text-slate-500">

            <Building2 size={12} className={cn("shrink-0", isTenantNav ? "text-violet-400/70" : "text-accent-gold")} />

            <span className="truncate">{t("app.footer")}</span>

          </div>

        </div>

      </aside>



      <main className="flex-1 flex flex-col min-w-0 overflow-hidden">

        <header className={cn(
          "sticky top-0 z-30 shrink-0 px-5 py-3 flex items-center justify-end gap-3",
          isTenantNav
            ? "border-b border-white/[0.06] bg-surface-dark-page/80 backdrop-blur-md"
            : "border-b border-gray-200/80 bg-white/90 backdrop-blur-md shadow-sm",
        )}>

          <LanguageSwitcher />

          <DemoModeToggle />

          <UserMenu />

        </header>

        <div className={cn(
          "flex-1 overflow-y-auto min-h-0",
          isTenantNav ? "bg-surface-dark-page" : "bg-slate-50",
        )}>

          <Suspense fallback={null}>

            <AiCommandPageProvider>

              {children}

              <ContextAiAssistant />

            </AiCommandPageProvider>

          </Suspense>

        </div>

      </main>

      <FloatingAssistant />

    </div>

  );

}

