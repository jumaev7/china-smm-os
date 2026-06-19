"use client";

import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import {
  cleanupDocumentInteractionBlockers,
  POST_AUTH_CLEANUP_RETRY_MS,
  scheduleDocumentInteractionCleanup,
  waitForCredentialUiToSettle,
} from "@/lib/dom-cleanup";

/**
 * Redirect authenticated users away from login pages without racing Chrome's
 * password-save UI, and restore document interactivity if focus was lost.
 */
export function usePostAuthNavigation(
  isAuthenticated: boolean,
  loading: boolean,
  nextPath: string,
) {
  const router = useRouter();
  const navigatingRef = useRef(false);

  useEffect(() => {
    if (loading || !isAuthenticated) return;

    let cancelled = false;
    let cancelScheduledCleanup: (() => void) | undefined;

    const restoreInteractivity = () => {
      cleanupDocumentInteractionBlockers();
    };

    window.addEventListener("focus", restoreInteractivity);
    window.addEventListener("visibilitychange", restoreInteractivity);

    void (async () => {
      await waitForCredentialUiToSettle(300);
      if (cancelled || navigatingRef.current) return;
      navigatingRef.current = true;
      restoreInteractivity();
      router.replace(nextPath);
      cancelScheduledCleanup = scheduleDocumentInteractionCleanup(POST_AUTH_CLEANUP_RETRY_MS);
      window.setTimeout(() => {
        navigatingRef.current = false;
      }, 300);
    })();

    return () => {
      cancelled = true;
      window.removeEventListener("focus", restoreInteractivity);
      window.removeEventListener("visibilitychange", restoreInteractivity);
      restoreInteractivity();
      cancelScheduledCleanup?.();
      scheduleDocumentInteractionCleanup();
    };
  }, [loading, isAuthenticated, nextPath, router]);
}
