"use client";

import Link from "next/link";
import { EmptyState } from "@/components/ui/PageStates";

type GuidedEmptyStateProps = {
  module: "leads" | "buyers" | "content" | "proposals" | "communications" | "deals";
  onAction?: () => void;
  actionLabel?: string;
};

const GUIDANCE: Record<
  GuidedEmptyStateProps["module"],
  { title: string; description: string; defaultAction: string; defaultRoute: string }
> = {
  leads: {
    title: "No Leads Yet",
    description: "Leads track buyer interest from first inquiry to closed deal. Create your first lead or load demo data.",
    defaultAction: "Create your first lead",
    defaultRoute: "/leads",
  },
  buyers: {
    title: "No Buyers Yet",
    description: "Build your export buyer network by importing contacts or discovering matched buyers.",
    defaultAction: "Import or create buyers",
    defaultRoute: "/buyers",
  },
  content: {
    title: "No Content Yet",
    description: "Post photos or videos to your linked Telegram group, or upload manually. AI will generate export marketing captions.",
    defaultAction: "Connect Telegram",
    defaultRoute: "/onboarding/channels",
  },
  proposals: {
    title: "No Proposals Yet",
    description: "Send professional export proposals to close deals faster. Create from an active deal or start fresh.",
    defaultAction: "Create your first proposal",
    defaultRoute: "/proposals",
  },
  communications: {
    title: "No Messages Yet",
    description: "All buyer conversations appear here. Connect Telegram or email to start managing export communications.",
    defaultAction: "Open Communication Hub",
    defaultRoute: "/communications",
  },
  deals: {
    title: "No Deals Yet",
    description: "Track export deals from inquiry to close. Convert a lead or create a deal to start building pipeline.",
    defaultAction: "Create your first deal",
    defaultRoute: "/deals",
  },
};

export function GuidedEmptyState({ module, onAction, actionLabel }: GuidedEmptyStateProps) {
  const guide = GUIDANCE[module];

  return (
    <EmptyState
      title={guide.title}
      description={guide.description}
      action={
        onAction ? (
          <button type="button" onClick={onAction} className="btn-primary text-sm">
            {actionLabel ?? guide.defaultAction}
          </button>
        ) : (
          <Link href={guide.defaultRoute} className="btn-primary text-sm">
            {actionLabel ?? guide.defaultAction}
          </Link>
        )
      }
    />
  );
}
