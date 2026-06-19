"use client";

import { Globe } from "lucide-react";
import { LOCALES, type Locale } from "@/lib/i18n";
import { useTranslation } from "@/lib/I18nProvider";
import { cn } from "@/lib/utils";

/** Native language names — always shown regardless of UI locale. */
export const LOCALE_OPTIONS: { code: Locale; label: string }[] = [
  { code: "ru", label: "Русский" },
  { code: "en", label: "English" },
  { code: "zh", label: "中文" },
];

export function localeNativeLabel(code: Locale): string {
  return LOCALE_OPTIONS.find((o) => o.code === code)?.label ?? code;
}

export function LanguageSwitcher({ className }: { className?: string }) {
  const { locale, setLocale, t, ready } = useTranslation();
  const currentLabel = localeNativeLabel(locale);

  return (
    <div
      className={cn("flex flex-wrap items-center gap-2 sm:gap-3", className)}
      role="group"
      aria-label={t("language.label")}
    >
      <div className="flex items-center gap-1.5 text-gray-500 shrink-0">
        <Globe size={15} className="text-brand-600" aria-hidden />
        <span className="text-xs font-medium text-gray-700 hidden sm:inline">{t("language.label")}:</span>
        <span className="text-xs font-semibold text-brand-800 sm:hidden">{currentLabel}</span>
      </div>

      <div className="inline-flex rounded-lg border border-gray-200 bg-gray-50 p-0.5 shadow-sm">
        {LOCALE_OPTIONS.map(({ code, label }) => {
          const active = locale === code;
          return (
            <button
              key={code}
              type="button"
              disabled={!ready}
              aria-pressed={active}
              aria-label={label}
              title={label}
              onClick={() => {
                if (code !== locale) setLocale(code);
              }}
              className={cn(
                "px-2.5 sm:px-3 py-1.5 text-xs font-medium rounded-md transition-all whitespace-nowrap",
                active
                  ? "bg-white text-brand-800 shadow-sm ring-1 ring-brand-100"
                  : "text-gray-600 hover:text-gray-900 hover:bg-white/60",
                !ready && "opacity-60 cursor-wait",
              )}
            >
              {label}
            </button>
          );
        })}
      </div>

      <span className="text-[10px] text-gray-400 hidden lg:inline tabular-nums">
        {currentLabel}
      </span>
    </div>
  );
}

/** Dropdown variant — same persistence, for compact spaces. */
export function LanguageSwitcherDropdown({ className }: { className?: string }) {
  const { locale, setLocale, t, ready } = useTranslation();

  return (
    <div className={cn("flex items-center gap-2", className)}>
      <Globe size={14} className="text-brand-600 shrink-0" />
      <select
        className="input text-xs py-1.5 h-9 min-w-[8.5rem] font-medium"
        value={locale}
        disabled={!ready}
        onChange={(e) => setLocale(e.target.value as Locale)}
        aria-label={t("language.label")}
      >
        {LOCALE_OPTIONS.map(({ code, label }) => (
          <option key={code} value={code}>
            {label}
          </option>
        ))}
      </select>
    </div>
  );
}

export { LOCALES };
