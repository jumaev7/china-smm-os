/**
 * Restore page interactivity after auth flows or browser credential UI (e.g. Chrome
 * "Save password?") that can leave pointer/scroll locks or orphaned backdrop nodes.
 *
 * Never removes React-managed DOM nodes — only clears safe inline styles/attributes.
 */

/** Retries through credential UI settle + slow dashboard widget fetches. */
const CLEANUP_RETRY_MS = [0, 50, 150, 400, 800, 1500, 2500, 5000, 8000];

export const POST_AUTH_CLEANUP_RETRY_MS = CLEANUP_RETRY_MS;

function clearRootInteractionLocks(root: HTMLElement) {
  root.style.pointerEvents = "";
  root.style.overflow = "";
  root.style.paddingRight = "";
  root.style.position = "";
  root.style.filter = "";
  root.removeAttribute("aria-hidden");
  root.removeAttribute("inert");
  root.removeAttribute("data-scroll-locked");
  root.removeAttribute("data-scroll-lock");

  if (window.getComputedStyle(root).pointerEvents === "none") {
    root.style.pointerEvents = "auto";
  }
}

function parseColorAlpha(color: string): number {
  const match = color.match(/rgba?\(([^)]+)\)/);
  if (!match) return color === "transparent" ? 0 : 1;
  const parts = match[1].split(",").map((part) => part.trim());
  if (parts.length >= 4) return parseFloat(parts[3]) || 0;
  return 1;
}

function shouldKeepOverlayElement(node: HTMLElement): boolean {
  if (node.hasAttribute("data-keep-overlay")) return true;
  if (node.closest("[data-keep-overlay]")) return true;
  if (node.hasAttribute("data-app-modal")) return true;
  if (node.closest("[data-app-modal]")) return true;
  if (node.hasAttribute("data-rht-toaster")) return true;
  if (node.closest("[data-rht-toaster]")) return true;
  if (node.tagName === "BUTTON" && !coversViewport(node)) return true;
  return false;
}

/** Nodes owned by the Next.js / React app — never remove or mutate structure. */
function isAppManagedNode(node: HTMLElement): boolean {
  if (node.id === "__next") return true;
  if (node.closest("#__next")) return true;
  if (node.closest("[data-dashboard-shell]")) return true;
  if (node.closest("nextjs-portal")) return true;
  if (node.closest("[data-nextjs-dialog]")) return true;
  if (node.closest("[data-nextjs-toast]")) return true;
  if (node.closest("next-route-announcer")) return true;
  if (node.closest("[data-nextjs-scroll-focus-boundary]")) return true;
  return false;
}

function shouldPreserveNode(node: HTMLElement): boolean {
  if (shouldKeepOverlayElement(node)) return true;
  if (isAppManagedNode(node)) return true;
  if (node.hasAttribute("data-login-overlay") || node.closest("[data-login-overlay]")) return true;
  return false;
}

function coversViewport(node: HTMLElement): boolean {
  const rect = node.getBoundingClientRect();
  return (
    rect.width >= window.innerWidth * 0.85 && rect.height >= window.innerHeight * 0.85
  );
}

/** Full-viewport layer that looks dimmed or blocks clicks (Chrome credential UI leftovers). */
function isOrphanedBlockingOverlay(node: HTMLElement): boolean {
  if (shouldPreserveNode(node)) return false;

  const style = window.getComputedStyle(node);
  if (style.display === "none" || style.visibility === "hidden") return false;
  if (style.position !== "fixed" && style.position !== "absolute") return false;
  if (!coversViewport(node)) return false;

  const bgAlpha = parseColorAlpha(style.backgroundColor);
  const hasDimBackground =
    bgAlpha > 0.05 && style.backgroundColor !== "rgba(0, 0, 0, 0)";
  const hasBackdrop = style.backdropFilter !== "none";
  const hasDimFilter = style.filter !== "none" && style.filter !== "";
  const lowOpacity = parseFloat(style.opacity) < 0.98;

  // Visible dim layer (even pointer-events:none) or invisible click interceptor.
  if (hasDimBackground || hasBackdrop || hasDimFilter || lowOpacity) return true;
  if (style.pointerEvents === "none") return false;
  return bgAlpha === 0;
}

/** Clear blocking styles without removing the node from the DOM. */
function neutralizeOverlayStyles(node: HTMLElement): void {
  if (shouldPreserveNode(node)) return;

  node.style.pointerEvents = "none";
  node.style.opacity = "0";
  node.style.filter = "";
  node.style.backdropFilter = "none";
  node.removeAttribute("inert");
  node.removeAttribute("aria-hidden");
}

/**
 * Only neutralize known orphan markers and body-level nodes outside the React tree.
 * Does not walk or remove nodes inside #__next.
 */
function neutralizeOrphanedOverlays() {
  const markerSelectors = [
    "[data-auth-overlay]",
    "[data-scroll-lock-backdrop]",
    "[data-page-loading-overlay]",
  ];

  for (const selector of markerSelectors) {
    document.querySelectorAll(selector).forEach((node) => {
      if (!(node instanceof HTMLElement)) return;
      if (shouldPreserveNode(node)) return;
      neutralizeOverlayStyles(node);
    });
  }

  // Orphan overlays from credential UI are usually direct children of body, not inside #__next.
  document.body.childNodes.forEach((node) => {
    if (!(node instanceof HTMLElement)) return;
    if (node.id === "__next") return;
    if (shouldPreserveNode(node)) return;
    if (isOrphanedBlockingOverlay(node)) {
      neutralizeOverlayStyles(node);
    }
    node.querySelectorAll("*").forEach((child) => {
      if (!(child instanceof HTMLElement)) return;
      if (shouldPreserveNode(child)) return;
      if (isOrphanedBlockingOverlay(child)) {
        neutralizeOverlayStyles(child);
      }
    });
  });
}

/** Dev-only: set window.__SMM_DISABLE_OVERLAY_CLEANUP = true to skip cleanup for diagnosis. */
function isCleanupDisabled(): boolean {
  if (typeof window === "undefined") return false;
  return (
    (window as Window & { __SMM_DISABLE_OVERLAY_CLEANUP?: boolean })
      .__SMM_DISABLE_OVERLAY_CLEANUP === true
  );
}

export type InteractionBlockerReport = {
  url: string;
  viewport: [number, number];
  centerPoint: [number, number];
  topElement: {
    tag: string;
    className: string;
    id: string;
    role: string | null;
    zIndex: string;
    position: string;
    opacity: string;
    backgroundColor: string;
    pointerEvents: string;
    outerHTML: string;
  } | null;
  parentChain: Array<{
    tag: string;
    className: string;
    id: string;
    role: string | null;
    style: string | null;
    zIndex: string;
    position: string;
    pointerEvents: string;
    opacity: string;
    backgroundColor: string;
  }>;
  largePointerTargets: Array<{
    tag: string;
    className: string;
    id: string;
    role: string | null;
    zIndex: string;
    position: string;
    opacity: string;
    backgroundColor: string;
    pointerEvents: string;
    rect: [number, number, number, number];
    dataAttributes: string;
  }>;
  fixedLayers: Array<{
    tag: string;
    className: string;
    id: string;
    role: string | null;
    zIndex: string;
    backgroundColor: string;
    pointerEvents: string;
    opacity: string;
    backdropFilter: string;
    rect: [number, number, number, number];
    dataAttributes: string;
    outerHTML: string;
  }>;
};

/** Run the same hit-test DevTools uses to find the click-blocking layer. */
export function diagnoseInteractionBlocker(): InteractionBlockerReport {
  if (typeof document === "undefined" || typeof window === "undefined") {
    return {
      url: "",
      viewport: [0, 0],
      centerPoint: [0, 0],
      topElement: null,
      parentChain: [],
      largePointerTargets: [],
      fixedLayers: [],
    };
  }

  const x = window.innerWidth / 2;
  const y = window.innerHeight / 2;
  const el = document.elementFromPoint(x, y);
  const style = el instanceof HTMLElement ? window.getComputedStyle(el) : null;

  const parentChain: InteractionBlockerReport["parentChain"] = [];
  let node: Element | null = el;
  while (node instanceof HTMLElement) {
    const s = window.getComputedStyle(node);
    parentChain.push({
      tag: node.tagName,
      className: typeof node.className === "string" ? node.className : "",
      id: node.id,
      role: node.getAttribute("role"),
      style: node.getAttribute("style"),
      zIndex: s.zIndex,
      position: s.position,
      pointerEvents: s.pointerEvents,
      opacity: s.opacity,
      backgroundColor: s.backgroundColor,
    });
    node = node.parentElement;
  }

  const largePointerTargets = [...document.querySelectorAll("*")]
    .map((candidate) => {
      if (!(candidate instanceof HTMLElement)) return null;
      const s = window.getComputedStyle(candidate);
      const r = candidate.getBoundingClientRect();
      return {
        tag: candidate.tagName,
        className: typeof candidate.className === "string" ? candidate.className : "",
        id: candidate.id,
        role: candidate.getAttribute("role"),
        zIndex: s.zIndex,
        position: s.position,
        opacity: s.opacity,
        backgroundColor: s.backgroundColor,
        pointerEvents: s.pointerEvents,
        rect: [r.x, r.y, r.width, r.height] as [number, number, number, number],
        dataAttributes: [...candidate.attributes]
          .filter((attr) => attr.name.startsWith("data-"))
          .map((attr) => `${attr.name}=${attr.value}`)
          .join(","),
      };
    })
    .filter(
      (item) =>
        item !== null &&
        item.rect[2] > window.innerWidth * 0.8 &&
        item.rect[3] > window.innerHeight * 0.8 &&
        item.pointerEvents !== "none",
    )
    .sort((a, b) => (Number(b!.zIndex) || 0) - (Number(a!.zIndex) || 0))
    .slice(0, 20) as InteractionBlockerReport["largePointerTargets"];

  const fixedLayers = [...document.querySelectorAll("*")]
    .filter((candidate) => {
      if (!(candidate instanceof HTMLElement)) return false;
      const s = window.getComputedStyle(candidate);
      if (s.position !== "fixed" && s.position !== "absolute") return false;
      const r = candidate.getBoundingClientRect();
      return r.width >= window.innerWidth * 0.85 && r.height >= window.innerHeight * 0.85;
    })
    .map((candidate) => {
      const s = window.getComputedStyle(candidate);
      const r = candidate.getBoundingClientRect();
      return {
        tag: candidate.tagName,
        className: typeof candidate.className === "string" ? candidate.className : "",
        id: candidate.id,
        role: candidate.getAttribute("role"),
        zIndex: s.zIndex,
        backgroundColor: s.backgroundColor,
        pointerEvents: s.pointerEvents,
        opacity: s.opacity,
        backdropFilter: s.backdropFilter,
        rect: [r.x, r.y, r.width, r.height] as [number, number, number, number],
        dataAttributes: [...candidate.attributes]
          .filter((attr) => attr.name.startsWith("data-"))
          .map((attr) => `${attr.name}=${attr.value}`)
          .join(","),
        outerHTML: candidate.outerHTML.slice(0, 300),
      };
    })
    .sort((a, b) => (Number(b.zIndex) || 0) - (Number(a.zIndex) || 0));

  return {
    url: window.location.href,
    viewport: [window.innerWidth, window.innerHeight],
    centerPoint: [x, y],
    topElement:
      el instanceof HTMLElement && style
        ? {
            tag: el.tagName,
            className: typeof el.className === "string" ? el.className : "",
            id: el.id,
            role: el.getAttribute("role"),
            zIndex: style.zIndex,
            position: style.position,
            opacity: style.opacity,
            backgroundColor: style.backgroundColor,
            pointerEvents: style.pointerEvents,
            outerHTML: el.outerHTML.slice(0, 300),
          }
        : null,
    parentChain,
    largePointerTargets,
    fixedLayers,
  };
}

export function cleanupDocumentInteractionBlockers() {
  if (typeof document === "undefined") return;
  if (isCleanupDisabled()) return;

  const { body, documentElement: html } = document;

  clearRootInteractionLocks(body);
  clearRootInteractionLocks(html);

  neutralizeOrphanedOverlays();
}

function hasOrphanMarkerNodes(): boolean {
  return (
    document.querySelector(
      "[data-auth-overlay], [data-scroll-lock-backdrop], [data-page-loading-overlay]",
    ) !== null
  );
}

function hasBodyLevelBlockingOverlay(): boolean {
  let found = false;
  document.body.childNodes.forEach((node) => {
    if (found || !(node instanceof HTMLElement)) return;
    if (node.id === "__next") return;
    if (isOrphanedBlockingOverlay(node)) found = true;
  });
  return found;
}

export function hasDocumentInteractionBlockers(): boolean {
  if (typeof document === "undefined") return false;

  const { body, documentElement: html } = document;

  if (
    body.style.pointerEvents === "none" ||
    html.style.pointerEvents === "none" ||
    window.getComputedStyle(body).pointerEvents === "none" ||
    window.getComputedStyle(html).pointerEvents === "none"
  ) {
    return true;
  }
  if (body.hasAttribute("inert") || html.hasAttribute("inert")) return true;
  if (body.getAttribute("aria-hidden") === "true" || html.getAttribute("aria-hidden") === "true") {
    return true;
  }
  if (body.hasAttribute("data-scroll-locked") || html.hasAttribute("data-scroll-locked")) {
    return true;
  }
  if (hasOrphanMarkerNodes()) return true;
  return hasBodyLevelBlockingOverlay();
}

/** Run cleanup immediately and on delayed retries while credential UI may still be settling. */
export function scheduleDocumentInteractionCleanup(
  delaysMs: number[] = CLEANUP_RETRY_MS,
): () => void {
  if (typeof window === "undefined") return () => {};

  const timers = delaysMs.map((delay) =>
    window.setTimeout(() => cleanupDocumentInteractionBlockers(), delay),
  );

  return () => {
    timers.forEach((timer) => window.clearTimeout(timer));
  };
}

/** No-op: mutation-driven cleanup removed to avoid racing React. Use post-auth cleanup only. */
export function watchForInteractionBlockers(): () => void {
  return () => {};
}

/**
 * Wait for Chrome credential UI / focus restoration before post-login navigation.
 * Resolves when the window regains focus or after a short fallback timeout.
 */
export function waitForCredentialUiToSettle(maxWaitMs = 300): Promise<void> {
  if (typeof window === "undefined") return Promise.resolve();

  return new Promise((resolve) => {
    let settled = false;

    const finish = () => {
      if (settled) return;
      settled = true;
      window.removeEventListener("focus", onFocus);
      window.removeEventListener("visibilitychange", onVisibilityChange);
      window.clearTimeout(fallbackTimer);
      cleanupDocumentInteractionBlockers();
      scheduleDocumentInteractionCleanup([0, 100, 500, 1500, 3000]);
      resolve();
    };

    const onFocus = () => {
      requestAnimationFrame(() => {
        requestAnimationFrame(finish);
      });
    };

    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") onFocus();
    };

    const fallbackTimer = window.setTimeout(finish, maxWaitMs);

    window.addEventListener("focus", onFocus);
    window.addEventListener("visibilitychange", onVisibilityChange);

    if (document.hasFocus()) {
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          window.setTimeout(finish, 120);
        });
      });
    }
  });
}
