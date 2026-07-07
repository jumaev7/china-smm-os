"use client";

import { cn } from "@/lib/utils";

export function OnboardingFormField({
  label,
  hint,
  error,
  required,
  children,
  className,
}: {
  label: string;
  hint?: string;
  error?: string;
  required?: boolean;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <label className={cn("block", className)}>
      <span className="text-sm font-medium text-gray-700 dark-tenant:text-slate-300">
        {label}
        {required ? <span className="text-red-500 ml-0.5">*</span> : null}
      </span>
      {hint ? (
        <span className="block text-xs text-gray-500 mt-0.5 dark-tenant:text-slate-500">{hint}</span>
      ) : null}
      <div className="mt-1.5">{children}</div>
      {error ? (
        <p className="mt-1.5 text-xs text-red-600 flex items-center gap-1 dark-tenant:text-red-400" role="alert">
          {error}
        </p>
      ) : null}
    </label>
  );
}

export function OnboardingTextInput({
  value,
  onChange,
  type = "text",
  placeholder,
  error,
  disabled,
  id,
  onBlur,
}: {
  value: string;
  onChange: (v: string) => void;
  type?: string;
  placeholder?: string;
  error?: boolean;
  disabled?: boolean;
  id?: string;
  onBlur?: () => void;
}) {
  return (
    <input
      id={id}
      type={type}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      onBlur={onBlur}
      placeholder={placeholder}
      disabled={disabled}
      className={cn(
        "w-full rounded-xl border px-4 py-2.5 text-sm transition-colors",
        "bg-white text-navy-900 placeholder:text-gray-400",
        "focus:outline-none focus:ring-2 focus:ring-brand-500/30 focus:border-brand-300",
        "disabled:opacity-50 disabled:cursor-not-allowed",
        "dark-tenant:bg-surface-dark-elevated dark-tenant:text-slate-100 dark-tenant:border-white/[0.1]",
        "dark-tenant:focus:ring-violet-500/30 dark-tenant:focus:border-violet-500/40",
        error ? "border-red-300 dark-tenant:border-red-500/40" : "border-slate-200 dark-tenant:border-white/[0.08]",
      )}
    />
  );
}

export function OnboardingSelect({
  value,
  onChange,
  options,
  placeholder,
  error,
  disabled,
}: {
  value: string;
  onChange: (v: string) => void;
  options: { label: string; value: string }[];
  placeholder?: string;
  error?: boolean;
  disabled?: boolean;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled}
      className={cn(
        "w-full rounded-xl border px-4 py-2.5 text-sm transition-colors appearance-none",
        "bg-white text-navy-900",
        "focus:outline-none focus:ring-2 focus:ring-brand-500/30 focus:border-brand-300",
        "disabled:opacity-50",
        "dark-tenant:bg-surface-dark-elevated dark-tenant:text-slate-100 dark-tenant:border-white/[0.1]",
        error ? "border-red-300" : "border-slate-200",
      )}
    >
      {placeholder ? (
        <option value="" disabled>
          {placeholder}
        </option>
      ) : null}
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

export function AutosaveIndicator({ status }: { status: "idle" | "saving" | "saved" | "error" }) {
  if (status === "idle") return null;
  return (
    <span
      className={cn(
        "text-xs font-medium tabular-nums transition-opacity",
        status === "saving" && "text-gray-400 animate-pulse dark-tenant:text-slate-500",
        status === "saved" && "text-emerald-600 dark-tenant:text-emerald-400",
        status === "error" && "text-red-600 dark-tenant:text-red-400",
      )}
      role="status"
      aria-live="polite"
    >
      {status === "saving" ? "Saving…" : status === "saved" ? "Saved" : "Save failed — retry"}
    </span>
  );
}
