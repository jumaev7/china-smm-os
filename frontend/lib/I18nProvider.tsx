"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  DEFAULT_LOCALE,
  detectBrowserLocale,
  isLocale,
  readStoredLocale,
  translate,
  writeStoredLocale,
  type Locale,
} from "@/lib/i18n";
import { usersApi } from "@/lib/api";

type I18nContextValue = {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: string, params?: Record<string, string | number>) => string;
  ready: boolean;
};

const I18nContext = createContext<I18nContextValue | null>(null);

function resolveInitialLocale(): Locale {
  return readStoredLocale() ?? detectBrowserLocale();
}

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(DEFAULT_LOCALE);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function bootstrap() {
      const local = resolveInitialLocale();
      try {
        const res = await usersApi.getSettings();
        const serverLang = res.data.preferred_language;
        const next = isLocale(serverLang) ? serverLang : local;
        if (!cancelled) {
          setLocaleState(next);
          writeStoredLocale(next);
          if (typeof document !== "undefined") {
            document.documentElement.lang = next;
          }
        }
      } catch {
        if (!cancelled) {
          setLocaleState(local);
          writeStoredLocale(local);
          if (typeof document !== "undefined") {
            document.documentElement.lang = local;
          }
        }
      } finally {
        if (!cancelled) setReady(true);
      }
    }

    bootstrap();
    return () => {
      cancelled = true;
    };
  }, []);

  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next);
    writeStoredLocale(next);
    if (typeof document !== "undefined") {
      document.documentElement.lang = next;
    }
    usersApi.updateLanguage(next).catch(() => {
      /* localStorage remains source of truth offline */
    });
  }, []);

  const t = useCallback(
    (key: string, params?: Record<string, string | number>) => translate(locale, key, params),
    [locale],
  );

  const value = useMemo(
    () => ({ locale, setLocale, t, ready }),
    [locale, setLocale, t, ready],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nContextValue {
  const ctx = useContext(I18nContext);
  if (!ctx) {
    throw new Error("useI18n must be used within I18nProvider");
  }
  return ctx;
}

export function useTranslation() {
  const { t, locale, setLocale, ready } = useI18n();
  return { t, locale, setLocale, ready };
}
