"use client";

import { useEffect } from "react";
import { Sparkles } from "lucide-react";
import { useOptionalAiCommandContext } from "@/lib/useAiCommandContext";

type AskAiAboutItemProps = {
  label?: string;
  entityLabel?: string;
};

export function AskAiAboutItem({ label, entityLabel }: AskAiAboutItemProps) {
  const ctx = useOptionalAiCommandContext();

  useEffect(() => {
    if (ctx && entityLabel) {
      ctx.setEntityLabel(entityLabel);
    }
  }, [ctx, entityLabel]);

  if (!ctx?.entity_type || !ctx.entity_id) return null;

  const displayLabel = label ?? ctx.entity_label ?? "this item";

  return (
    <button
      type="button"
      className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-violet-200 bg-violet-50/80 text-violet-800 hover:bg-violet-100 transition-colors"
      onClick={() => {
        window.dispatchEvent(
          new CustomEvent("ai-command-open", {
            detail: { command: `What should I do next for ${displayLabel}?` },
          }),
        );
      }}
    >
      <Sparkles size={12} />
      Ask AI about this item
    </button>
  );
}
