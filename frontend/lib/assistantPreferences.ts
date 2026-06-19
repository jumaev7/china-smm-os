const PREFS_KEY = "smm_assistant_prefs";

export interface AssistantPreferences {
  autoApply: boolean;
}

/** Default ON — internal admin/owner workflow. */
const DEFAULT_PREFS: AssistantPreferences = { autoApply: true };

export function loadAssistantPreferences(): AssistantPreferences {
  if (typeof window === "undefined") return DEFAULT_PREFS;
  try {
    const raw = localStorage.getItem(PREFS_KEY);
    if (raw) return { ...DEFAULT_PREFS, ...JSON.parse(raw) };
  } catch {
    /* ignore */
  }
  return DEFAULT_PREFS;
}

export function saveAssistantPreferences(prefs: AssistantPreferences): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
  } catch {
    /* ignore */
  }
}
