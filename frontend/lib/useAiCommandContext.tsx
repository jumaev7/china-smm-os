"use client";

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { usePathname, useParams, useSearchParams } from "next/navigation";

export type AiCommandEntityType =
  | "client"
  | "campaign"
  | "content"
  | "product"
  | "crm_lead"
  | "deal"
  | "partner"
  | "media_asset"
  | "landing_page";

export interface AiCommandPageContextValue {
  current_page: string;
  entity_type?: AiCommandEntityType;
  entity_id?: string;
  entity_label?: string;
  selected_items: string[];
  user_context_json: Record<string, unknown>;
  setSelectedItems: (ids: string[]) => void;
  setUserContextJson: (ctx: Record<string, unknown>) => void;
  setEntityLabel: (label: string | undefined) => void;
}

const AiCommandPageContext = createContext<AiCommandPageContextValue | null>(null);

function detectRouteContext(
  pathname: string,
  params: Record<string, string | string[] | undefined>,
  searchParams: URLSearchParams,
): Pick<AiCommandPageContextValue, "entity_type" | "entity_id"> {
  const id = typeof params?.id === "string" ? params.id : undefined;

  if (pathname.startsWith("/products/") && id) return { entity_type: "product", entity_id: id };
  if (pathname.startsWith("/campaigns/") && id) return { entity_type: "campaign", entity_id: id };
  if (pathname.startsWith("/content/") && id) return { entity_type: "content", entity_id: id };
  if (pathname.startsWith("/clients/") && id) return { entity_type: "client", entity_id: id };
  if (pathname.startsWith("/partners/") && id) return { entity_type: "partner", entity_id: id };
  if (pathname.startsWith("/crm/deals/") && id) return { entity_type: "deal", entity_id: id };
  if (pathname.startsWith("/landing-pages/") && id) return { entity_type: "landing_page", entity_id: id };
  if (pathname.startsWith("/media-library/") && id) return { entity_type: "media_asset", entity_id: id };

  const leadId = searchParams.get("lead");
  if (pathname.startsWith("/crm") && leadId) {
    return { entity_type: "crm_lead", entity_id: leadId };
  }

  return {};
}

export function AiCommandPageProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const params = useParams();
  const searchParams = useSearchParams();

  const [selectedItems, setSelectedItemsState] = useState<string[]>([]);
  const [userContextJson, setUserContextJsonState] = useState<Record<string, unknown>>({});
  const [entityLabel, setEntityLabel] = useState<string | undefined>();

  const routeCtx = useMemo(
    () => detectRouteContext(pathname, params, searchParams),
    [pathname, params, searchParams],
  );

  const setSelectedItems = useCallback((ids: string[]) => {
    setSelectedItemsState((prev) => {
      if (prev.length === ids.length && prev.every((v, i) => v === ids[i])) return prev;
      return ids;
    });
  }, []);

  const setUserContextJson = useCallback((ctx: Record<string, unknown>) => {
    setUserContextJsonState(ctx);
  }, []);

  const value = useMemo<AiCommandPageContextValue>(
    () => ({
      current_page: pathname,
      entity_type: routeCtx.entity_type,
      entity_id: routeCtx.entity_id,
      entity_label: entityLabel,
      selected_items: selectedItems,
      user_context_json: userContextJson,
      setSelectedItems,
      setUserContextJson,
      setEntityLabel,
    }),
    [pathname, routeCtx, entityLabel, selectedItems, userContextJson, setSelectedItems, setUserContextJson],
  );

  return (
    <AiCommandPageContext.Provider value={value}>{children}</AiCommandPageContext.Provider>
  );
}

export function useAiCommandContext(): AiCommandPageContextValue {
  const ctx = useContext(AiCommandPageContext);
  if (!ctx) {
    throw new Error("useAiCommandContext must be used within AiCommandPageProvider");
  }
  return ctx;
}

export function useOptionalAiCommandContext(): AiCommandPageContextValue | null {
  return useContext(AiCommandPageContext);
}

export function buildAiCommandPayload(ctx: AiCommandPageContextValue) {
  return {
    current_page: ctx.current_page,
    entity_type: ctx.entity_type,
    entity_id: ctx.entity_id,
    selected_items: ctx.selected_items,
    user_context_json: ctx.user_context_json,
  };
}
