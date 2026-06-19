/** Local browser datetime ↔ UTC helpers for scheduling. */

/** Combine local date (YYYY-MM-DD) and time (HH:mm) → UTC ISO string. */
export function localDateTimeToUtcIso(date: string, time: string): string {
  const [year, month, day] = date.split("-").map(Number);
  const [hour, minute] = time.split(":").map(Number);
  const local = new Date(year, month - 1, day, hour, minute, 0, 0);
  return local.toISOString();
}

/** Format UTC ISO string in the user's local timezone. */
export function formatScheduledLocal(
  isoUtc: string,
  options: Intl.DateTimeFormatOptions = {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  },
): string {
  return new Date(isoUtc).toLocaleString(undefined, options);
}

/** UTC ISO → local YYYY-MM-DD for date inputs. */
export function utcIsoToLocalDate(isoUtc: string): string {
  const d = new Date(isoUtc);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/** UTC ISO → local HH:mm for time inputs. */
export function utcIsoToLocalTime(isoUtc: string): string {
  const d = new Date(isoUtc);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export const LOCAL_TIMEZONE_NOTE = "Times are shown in your local timezone";

export function clientTimezone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
}
