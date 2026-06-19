"use client";

import { useEffect } from "react";
import {
  cleanupDocumentInteractionBlockers,
  scheduleDocumentInteractionCleanup,
} from "@/lib/dom-cleanup";

/**
 * Restore document interactivity after login navigation and Chrome credential UI.
 */
export function useDocumentInteractionCleanup(pathname: string) {
  useEffect(() => {
    cleanupDocumentInteractionBlockers();
    const cancelScheduled = scheduleDocumentInteractionCleanup();

    const restore = () => {
      cleanupDocumentInteractionBlockers();
    };

    window.addEventListener("focus", restore);
    window.addEventListener("visibilitychange", restore);

    return () => {
      cancelScheduled();
      window.removeEventListener("focus", restore);
      window.removeEventListener("visibilitychange", restore);
      restore();
    };
  }, [pathname]);
}

/**
 * Clear document interaction blockers once async page data has settled (success or error).
 */
export function useCleanupWhenFetched(isFetched: boolean, _isFetching = false) {
  useEffect(() => {
    if (!isFetched) return;

    cleanupDocumentInteractionBlockers();
    const cancelScheduled = scheduleDocumentInteractionCleanup();
    return cancelScheduled;
  }, [isFetched, _isFetching]);
}
