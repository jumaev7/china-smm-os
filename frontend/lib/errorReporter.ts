/** Report frontend errors to centralized error tracking. */
import { platformOpsApi } from "@/lib/api";

export function reportFrontendError(
  error: Error,
  context?: { path?: string; metadata?: Record<string, unknown> },
): void {
  const path = context?.path ?? (typeof window !== "undefined" ? window.location.pathname : undefined);
  platformOpsApi
    .reportError({
      source: "frontend",
      path,
      message: error.message || "Unknown frontend error",
      stack_trace: error.stack,
      metadata: context?.metadata,
    })
    .catch(() => {
      /* silent — never break UX for error reporting */
    });
}
