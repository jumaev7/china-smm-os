"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ExternalLink, Link2, Loader2 } from "lucide-react";
import { platformRelationshipsApi, type PlatformRelationships } from "@/lib/api";
import { cn } from "@/lib/utils";

type SectionKey = keyof Pick<
  PlatformRelationships,
  | "related_content"
  | "related_leads"
  | "related_buyers"
  | "related_deals"
  | "related_proposals"
  | "related_communications"
  | "related_customers"
>;

const SECTION_LABELS: Record<SectionKey, string> = {
  related_content: "Content",
  related_leads: "Leads",
  related_buyers: "Buyers",
  related_deals: "Deals",
  related_proposals: "Proposals",
  related_communications: "Communications",
  related_customers: "Customers",
};

const SECTION_ORDER: SectionKey[] = [
  "related_leads",
  "related_buyers",
  "related_deals",
  "related_proposals",
  "related_communications",
  "related_content",
  "related_customers",
];

type Props = {
  entityType: "lead" | "deal" | "proposal" | "buyer" | "content";
  entityId: string;
  className?: string;
  compact?: boolean;
};

export function RelatedEntitiesPanel({ entityType, entityId, className, compact }: Props) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["platform-related", entityType, entityId],
    queryFn: () => platformRelationshipsApi.get(entityType, entityId).then((r) => r.data),
    enabled: !!entityId,
  });

  if (isLoading) {
    return (
      <div className={cn("flex items-center gap-2 text-sm text-gray-500", className)}>
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading related records…
      </div>
    );
  }

  if (isError || !data) {
    return (
      <p className={cn("text-sm text-gray-500", className)}>
        Related records unavailable.
      </p>
    );
  }

  const sections = SECTION_ORDER.filter((key) => (data[key]?.length ?? 0) > 0);
  if (sections.length === 0) {
    return (
      <p className={cn("text-sm text-gray-500", className)}>
        No linked records yet. Connect leads, buyers, deals, or communications to build the workflow.
      </p>
    );
  }

  return (
    <div className={cn("space-y-4", className)}>
      {!compact && (
        <div className="flex items-center gap-2 text-sm font-semibold text-gray-900">
          <Link2 className="h-4 w-4 text-indigo-600" />
          Related records
        </div>
      )}
      {sections.map((key) => (
        <div key={key}>
          <h4 className="text-xs font-medium uppercase tracking-wide text-gray-500 mb-1.5">
            {SECTION_LABELS[key]}
          </h4>
          <ul className="space-y-1">
            {data[key].map((item) => (
              <li key={`${item.entity_type}-${item.entity_id}`}>
                {item.href ? (
                  <Link
                    href={item.href}
                    className="flex items-center gap-2 text-sm text-indigo-700 hover:text-indigo-900 hover:underline"
                  >
                    <span className="truncate">{item.label}</span>
                    {item.status && (
                      <span className="shrink-0 rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-600">
                        {item.status.replace(/_/g, " ")}
                      </span>
                    )}
                    <ExternalLink className="h-3 w-3 shrink-0 opacity-60" />
                  </Link>
                ) : (
                  <span className="text-sm text-gray-800">{item.label}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
