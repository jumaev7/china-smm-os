import axios from "axios";
import { getApiErrorStatus } from "@/lib/api";

type TranslateFn = (key: string) => string;

const TECHNICAL_PATTERNS = [
  /timed?\s*out/i,
  /ECONNABORTED/i,
  /HTTP\s+\d{3}/i,
  /\/api\/v\d/i,
  /unknown endpoint/i,
  /localhost:\d+/i,
  /Server timed out/i,
  /Request timed out/i,
  /Cannot reach API/i,
];

export function isTechnicalErrorMessage(message: string): boolean {
  return TECHNICAL_PATTERNS.some((pattern) => pattern.test(message));
}

export function getUserFacingApiErrorMessage(
  err: unknown,
  t: TranslateFn,
): string {
  const status = getApiErrorStatus(err);
  const isTimeout =
    (axios.isAxiosError(err) &&
      (err.code === "ECONNABORTED" || status === 504 || status === 408)) ||
    (err instanceof Error && /timed?\s*out/i.test(err.message));

  if (isTimeout) return t("errors.timeout");
  if (status === 401) return t("errors.unauthorized");
  if (status === 403) return t("errors.forbidden");
  if (status === 500) return t("errors.generic");
  if (status === 503 || status === 502) return t("errors.serverBusy");
  if (axios.isAxiosError(err) && !err.response) return t("errors.network");
  return t("errors.generic");
}

export function sanitizeErrorMessage(message: string, t: TranslateFn): string {
  if (!message || isTechnicalErrorMessage(message)) {
    if (/timed?\s*out|504|408/i.test(message)) return t("errors.timeout");
    if (/401|unauthorized/i.test(message)) return t("errors.unauthorized");
    if (/403|forbidden/i.test(message)) return t("errors.forbidden");
    if (/cannot reach|network error/i.test(message)) return t("errors.network");
    if (/503|502|overloaded|temporarily unavailable/i.test(message)) return t("errors.serverBusy");
    return t("errors.generic");
  }
  return message;
}
