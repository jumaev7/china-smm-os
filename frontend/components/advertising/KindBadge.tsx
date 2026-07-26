"use client";

import { StatusBadge } from "@/components/ui/design-system";
import { kindLabel, kindVariant } from "@/lib/advertising-ui";

/** Display badge for OBSERVED | SIMULATED | DIRECTIONAL | INSUFFICIENT DATA. */
export function KindBadge({ kind }: { kind?: string | null }) {
  if (!kind) return null;
  return <StatusBadge variant={kindVariant(kind)}>{kindLabel(kind)}</StatusBadge>;
}
