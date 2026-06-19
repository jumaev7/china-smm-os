const RAW_BACKEND_PATTERNS = [
  "sorry",
  "too many clients",
  "connection refused",
  "connection reset",
  "could not connect",
  "operationalerror",
  "sqlalchemy",
  "asyncpg",
  "traceback",
  "internal server error",
];

const API_PARTIAL_SECTIONS = new Set([
  "inbox",
  "tasks",
  "content_ready",
  "content_scheduled",
  "clients_waiting",
  "invoices",
  "active_deals",
  "won_deals",
  "lost_deals",
  "pipeline",
  "followups",
  "billing",
  "deal_risks",
  "operator_tasks_today",
]);

export function isRawBackendErrorMessage(raw: string): boolean {
  const lower = raw.toLowerCase();
  return RAW_BACKEND_PATTERNS.some((pattern) => lower.includes(pattern));
}

function isApiPartialSectionToken(token: string): boolean {
  const normalized = token.trim().toLowerCase();
  if (API_PARTIAL_SECTIONS.has(normalized)) return true;
  // Backend safe_section names (e.g. marketplace_integrations) — never show raw in UI.
  return /^[a-z][a-z0-9_]*$/.test(normalized);
}

/** Map one partial-error token to a safe display line. */
export function formatPartialErrorLine(
  raw: string,
  unavailableLabel: string,
): string {
  const token = raw.trim();
  if (!token) return unavailableLabel;

  if (isRawBackendErrorMessage(token)) return unavailableLabel;

  const colonIdx = token.indexOf(":");
  if (colonIdx === -1) {
    return isApiPartialSectionToken(token) ? unavailableLabel : token;
  }

  const section = token.slice(0, colonIdx).trim();
  const detail = token.slice(colonIdx + 1).trim();

  if (isApiPartialSectionToken(section) || isRawBackendErrorMessage(detail)) {
    return unavailableLabel;
  }

  return token;
}

export function formatPartialErrorsForDisplay(
  errors: string[],
  unavailableLabel: string,
): string {
  const lines = errors.map((entry) => formatPartialErrorLine(entry, unavailableLabel));
  const unique = [...new Set(lines.filter(Boolean))];
  if (unique.length === 0) return unavailableLabel;
  if (unique.length === 1) return unique[0];
  return unique.join(" · ");
}
