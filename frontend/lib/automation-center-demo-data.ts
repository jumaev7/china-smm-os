/**
 * Demo-only automation seed data for the Automation Center prototype.
 * Replace with real API responses when a tenant automation backend exists.
 */
import {
  Instagram,
  Lightbulb,
  Rocket,
  ShoppingBag,
  Trophy,
  UserPlus,
  XCircle,
  HeartPulse,
} from "lucide-react";
import type { Automation } from "@/lib/automation-center-ui";

/** Demo fallback — disabled by default; live API is the primary data source. */
export const AUTOMATION_CENTER_USES_DEMO_DATA = false;

function hoursAgo(hours: number): string {
  return new Date(Date.now() - hours * 60 * 60 * 1000).toISOString();
}

function daysAgo(days: number, hours = 0): string {
  return new Date(Date.now() - (days * 24 + hours) * 60 * 60 * 1000).toISOString();
}

function hoursFromNow(hours: number): string {
  return new Date(Date.now() + hours * 60 * 60 * 1000).toISOString();
}

/** Sample automations illustrating platform event-driven workflows (not live tenant data). */
export function createDemoAutomations(): Automation[] {
  return [
    {
      id: "auto-instagram-disconnected",
      name: "Instagram disconnected response",
      description:
        "When Instagram loses connection, notify admins, reduce health score, and surface a reconnection recommendation.",
      status: "active",
      enabled: true,
      steps: [
        { id: "s1", label: "Instagram disconnected" },
        { id: "s2", label: "Notify admin" },
        { id: "s3", label: "Reduce Health Score" },
        { id: "s4", label: "Show recommendation" },
      ],
      conditions: ["Integration status = disconnected", "Platform = Instagram"],
      relatedModules: [
        { label: "Integrations", href: "/integrations" },
        { label: "Customer Success", href: "/customer-success" },
        { label: "Notifications", href: "/notifications" },
      ],
      lastExecution: hoursAgo(2),
      successRate: 98,
      nextScheduled: null,
      icon: Instagram,
      iconClassName: "text-pink-600 bg-pink-50 dark-tenant:bg-pink-500/10 dark-tenant:text-pink-400",
      createdAt: daysAgo(30),
      updatedAt: hoursAgo(2),
      executionHistory: [
        {
          id: "ex-ig-1",
          automationId: "auto-instagram-disconnected",
          automationName: "Instagram disconnected response",
          timestamp: hoursAgo(2),
          result: "success",
          detail: "Admin notified, health score -8",
          durationMs: 1240,
        },
        {
          id: "ex-ig-2",
          automationId: "auto-instagram-disconnected",
          automationName: "Instagram disconnected response",
          timestamp: daysAgo(14),
          result: "success",
          detail: "Previous disconnect handled",
          durationMs: 980,
        },
      ],
    },
    {
      id: "auto-publishing-failed",
      name: "Publishing failure recovery",
      description:
        "Automatically retry failed publishes and create a notification for the content team.",
      status: "failed",
      enabled: true,
      steps: [
        { id: "s1", label: "Publishing failed" },
        { id: "s2", label: "Retry publish" },
        { id: "s3", label: "Create notification" },
      ],
      conditions: ["Publish status = failed", "Retry count < 3"],
      relatedModules: [
        { label: "Publishing", href: "/publishing" },
        { label: "Notifications", href: "/notifications" },
      ],
      lastExecution: hoursAgo(1),
      successRate: 72,
      nextScheduled: hoursFromNow(2),
      icon: XCircle,
      iconClassName: "text-red-600 bg-red-50 dark-tenant:bg-red-500/10 dark-tenant:text-red-400",
      createdAt: daysAgo(45),
      updatedAt: hoursAgo(1),
      executionHistory: [
        {
          id: "ex-pub-1",
          automationId: "auto-publishing-failed",
          automationName: "Publishing failure recovery",
          timestamp: hoursAgo(1),
          result: "failed",
          detail: "Retry exhausted — media rejected by Meta",
          durationMs: 4520,
        },
        {
          id: "ex-pub-2",
          automationId: "auto-publishing-failed",
          automationName: "Publishing failure recovery",
          timestamp: hoursAgo(5),
          result: "success",
          detail: "Recovered on second retry",
          durationMs: 3100,
        },
        {
          id: "ex-pub-3",
          automationId: "auto-publishing-failed",
          automationName: "Publishing failure recovery",
          timestamp: daysAgo(1),
          result: "skipped",
          detail: "No failed posts in queue",
          durationMs: 120,
        },
      ],
    },
    {
      id: "auto-journey-milestone",
      name: "Journey milestone celebration",
      description:
        "Unlock achievements, log activity, and notify the team when a customer success milestone is completed.",
      status: "active",
      enabled: true,
      steps: [
        { id: "s1", label: "Journey milestone completed" },
        { id: "s2", label: "Achievement unlocked" },
        { id: "s3", label: "Create activity" },
        { id: "s4", label: "Notification" },
      ],
      conditions: ["Milestone status = completed", "Journey = active"],
      relatedModules: [
        { label: "Customer Success Journey", href: "/customer-success/journey" },
        { label: "Notifications", href: "/notifications" },
      ],
      lastExecution: daysAgo(2),
      successRate: 100,
      nextScheduled: null,
      icon: Trophy,
      iconClassName: "text-amber-600 bg-amber-50 dark-tenant:bg-amber-500/10 dark-tenant:text-amber-400",
      createdAt: daysAgo(60),
      updatedAt: daysAgo(2),
      executionHistory: [
        {
          id: "ex-jm-1",
          automationId: "auto-journey-milestone",
          automationName: "Journey milestone celebration",
          timestamp: daysAgo(2),
          result: "success",
          detail: 'Milestone "Activate publishing" completed',
          durationMs: 890,
        },
      ],
    },
    {
      id: "auto-buyer-imported",
      name: "Buyer import to CRM",
      description: "When new buyers are imported from marketplace sync, create CRM leads and notify sales.",
      status: "active",
      enabled: true,
      steps: [
        { id: "s1", label: "New buyer imported" },
        { id: "s2", label: "Create CRM lead" },
        { id: "s3", label: "Notify sales" },
      ],
      conditions: ["Import source = marketplace", "Buyer count >= 1"],
      relatedModules: [
        { label: "Buyers", href: "/buyers" },
        { label: "CRM Pipeline", href: "/crm-pipeline" },
        { label: "Leads", href: "/leads" },
      ],
      lastExecution: hoursAgo(6),
      successRate: 96,
      nextScheduled: hoursFromNow(18),
      icon: ShoppingBag,
      iconClassName: "text-emerald-600 bg-emerald-50 dark-tenant:bg-emerald-500/10 dark-tenant:text-emerald-400",
      createdAt: daysAgo(20),
      updatedAt: hoursAgo(6),
      executionHistory: [
        {
          id: "ex-buy-1",
          automationId: "auto-buyer-imported",
          automationName: "Buyer import to CRM",
          timestamp: hoursAgo(6),
          result: "success",
          detail: "12 leads created, sales team notified",
          durationMs: 2100,
        },
        {
          id: "ex-buy-2",
          automationId: "auto-buyer-imported",
          automationName: "Buyer import to CRM",
          timestamp: daysAgo(3),
          result: "success",
          detail: "8 leads created",
          durationMs: 1850,
        },
      ],
    },
    {
      id: "auto-platform-ready",
      name: "Platform readiness kickoff",
      description:
        "When the workspace passes all readiness checks, automatically start the Customer Success Journey.",
      status: "active",
      enabled: true,
      steps: [
        { id: "s1", label: "Platform ready" },
        { id: "s2", label: "Start Customer Success Journey" },
      ],
      conditions: ["Readiness score = 100%", "Onboarding = complete"],
      relatedModules: [
        { label: "Customer Success Journey", href: "/customer-success/journey" },
        { label: "Onboarding", href: "/onboarding" },
      ],
      lastExecution: daysAgo(1),
      successRate: 100,
      nextScheduled: null,
      icon: Rocket,
      iconClassName: "text-violet-600 bg-violet-50 dark-tenant:bg-violet-500/10 dark-tenant:text-violet-400",
      createdAt: daysAgo(90),
      updatedAt: daysAgo(1),
      executionHistory: [
        {
          id: "ex-pr-1",
          automationId: "auto-platform-ready",
          automationName: "Platform readiness kickoff",
          timestamp: daysAgo(1),
          result: "success",
          detail: "Journey started for workspace",
          durationMs: 650,
        },
      ],
    },
    {
      id: "auto-health-drop",
      name: "Health score drop alert",
      description: "Alert CSM when account health drops below threshold and suggest interventions.",
      status: "paused",
      enabled: false,
      steps: [
        { id: "s1", label: "Health score dropped" },
        { id: "s2", label: "Notify CSM" },
        { id: "s3", label: "Create follow-up task" },
      ],
      conditions: ["Health score < 70", "Change >= 10 points"],
      relatedModules: [
        { label: "Customer Success", href: "/customer-success" },
        { label: "Tasks", href: "/tasks" },
      ],
      lastExecution: daysAgo(7),
      successRate: 94,
      nextScheduled: null,
      icon: HeartPulse,
      iconClassName: "text-rose-600 bg-rose-50 dark-tenant:bg-rose-500/10 dark-tenant:text-rose-400",
      createdAt: daysAgo(40),
      updatedAt: daysAgo(5),
      executionHistory: [
        {
          id: "ex-hd-1",
          automationId: "auto-health-drop",
          automationName: "Health score drop alert",
          timestamp: daysAgo(7),
          result: "success",
          detail: "CSM notified for Acme Trading",
          durationMs: 720,
        },
      ],
    },
    {
      id: "auto-lead-assigned",
      name: "Lead assignment notification",
      description: "Send instant notifications when inbound leads are assigned to team members.",
      status: "paused",
      enabled: false,
      steps: [
        { id: "s1", label: "Lead assigned" },
        { id: "s2", label: "Notify assignee" },
        { id: "s3", label: "Create activity" },
      ],
      conditions: ["Lead status = assigned", "Assignee is set"],
      relatedModules: [
        { label: "Leads", href: "/leads" },
        { label: "CRM", href: "/crm" },
      ],
      lastExecution: daysAgo(14),
      successRate: 99,
      nextScheduled: null,
      icon: UserPlus,
      iconClassName: "text-sky-600 bg-sky-50 dark-tenant:bg-sky-500/10 dark-tenant:text-sky-400",
      createdAt: daysAgo(50),
      updatedAt: daysAgo(10),
      executionHistory: [],
    },
    {
      id: "auto-recommendation-engine",
      name: "Smart recommendation surfacing",
      description: "Surface contextual recommendations based on platform usage patterns.",
      status: "draft",
      enabled: false,
      steps: [
        { id: "s1", label: "Usage pattern detected" },
        { id: "s2", label: "Generate recommendation" },
        { id: "s3", label: "Show in Growth Center" },
      ],
      conditions: ["Feature adoption < 50%", "Account age > 14 days"],
      relatedModules: [
        { label: "Growth Center", href: "/growth-center" },
      ],
      lastExecution: null,
      successRate: 0,
      nextScheduled: null,
      icon: Lightbulb,
      iconClassName: "text-indigo-600 bg-indigo-50 dark-tenant:bg-indigo-500/10 dark-tenant:text-indigo-400",
      createdAt: daysAgo(3),
      updatedAt: daysAgo(1),
      executionHistory: [],
    },
  ];
}
