import ru from "@/locales/ru.json";
import en from "@/locales/en.json";
import zh from "@/locales/zh.json";

export const LOCALES = ["ru", "en", "zh"] as const;
export type Locale = (typeof LOCALES)[number];

export const DEFAULT_LOCALE: Locale = "ru";
export const LOCALE_STORAGE_KEY = "china-smm-ui-locale";

export type Messages = typeof ru;

const CATALOG: Record<Locale, Messages> = { ru, en: en as Messages, zh: zh as Messages };

const loggedMissing = new Set<string>();

export function isLocale(value: string | null | undefined): value is Locale {
  return LOCALES.includes(value as Locale);
}

export function detectBrowserLocale(): Locale {
  if (typeof navigator === "undefined") return DEFAULT_LOCALE;
  const lang = navigator.language.toLowerCase();
  if (lang.startsWith("zh")) return "zh";
  if (lang.startsWith("en")) return "en";
  if (lang.startsWith("ru")) return "ru";
  return DEFAULT_LOCALE;
}

export function readStoredLocale(): Locale | null {
  if (typeof window === "undefined") return null;
  const stored = window.localStorage.getItem(LOCALE_STORAGE_KEY);
  return isLocale(stored) ? stored : null;
}

export function writeStoredLocale(locale: Locale): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(LOCALE_STORAGE_KEY, locale);
}

function getNestedValue(obj: Record<string, unknown>, key: string): string | undefined {
  const parts = key.split(".");
  let cur: unknown = obj;
  for (const part of parts) {
    if (cur == null || typeof cur !== "object") return undefined;
    cur = (cur as Record<string, unknown>)[part];
  }
  return typeof cur === "string" ? cur : undefined;
}

function interpolate(text: string, params?: Record<string, string | number>): string {
  if (!params) return text;
  return text.replace(/\{\{(\w+)\}\}/g, (_, name: string) =>
    params[name] != null ? String(params[name]) : "",
  );
}

export function translate(
  locale: Locale,
  key: string,
  params?: Record<string, string | number>,
): string {
  const primary = getNestedValue(CATALOG[locale] as unknown as Record<string, unknown>, key);
  if (primary) return interpolate(primary, params);

  if (locale !== DEFAULT_LOCALE) {
    const fallback = getNestedValue(
      CATALOG[DEFAULT_LOCALE] as unknown as Record<string, unknown>,
      key,
    );
    if (fallback) {
      if (typeof window !== "undefined" && !loggedMissing.has(`${locale}:${key}`)) {
        loggedMissing.add(`${locale}:${key}`);
        console.warn(`[I18N] missing key: ${key} (locale=${locale}, fallback=ru)`);
      }
      return interpolate(fallback, params);
    }
  }

  if (typeof window !== "undefined" && !loggedMissing.has(`missing:${key}`)) {
    loggedMissing.add(`missing:${key}`);
    console.warn(`[I18N] missing key: ${key}`);
  }
  return key;
}

export function flattenMessageKeys(obj: Record<string, unknown>, prefix = ""): string[] {
  const keys: string[] = [];
  for (const [k, v] of Object.entries(obj)) {
    const path = prefix ? `${prefix}.${k}` : k;
    if (typeof v === "string") {
      keys.push(path);
    } else if (v && typeof v === "object" && !Array.isArray(v)) {
      keys.push(...flattenMessageKeys(v as Record<string, unknown>, path));
    }
  }
  return keys;
}

export function allMessageKeys(): string[] {
  return flattenMessageKeys(ru as unknown as Record<string, unknown>).sort();
}

/** Standalone helper — in React components prefer `useTranslation().t` for live locale updates. */
export function t(key: string, params?: Record<string, string | number>): string {
  const locale =
    typeof window !== "undefined" ? (readStoredLocale() ?? DEFAULT_LOCALE) : DEFAULT_LOCALE;
  return translate(locale, key, params);
}

export { CATALOG };
