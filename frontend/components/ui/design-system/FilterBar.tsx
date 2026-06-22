import { cn } from "@/lib/utils";

export type FilterOption = {
  label: string;
  value: string;
};

export function FilterBar({
  options,
  value,
  onChange,
  className,
}: {
  options: FilterOption[];
  value: string;
  onChange: (value: string) => void;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "inline-flex flex-wrap gap-1 rounded-xl border border-gray-200/90 bg-white p-1",
        "dark-tenant:border-white/[0.08] dark-tenant:bg-surface-dark-elevated/60",
        className,
      )}
      role="tablist"
    >
      {options.map((opt) => {
        const active = value === opt.value;
        return (
          <button
            key={opt.value || "__all__"}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(opt.value)}
            className={cn(
              "px-3 py-1.5 text-xs font-medium rounded-lg transition-all duration-150",
              active
                ? "bg-brand-600 text-white shadow-sm dark-tenant:bg-violet-600 dark-tenant:shadow-glow"
                : "text-gray-600 hover:bg-gray-50 hover:text-gray-900 dark-tenant:text-slate-400 dark-tenant:hover:bg-white/[0.04] dark-tenant:hover:text-slate-200",
            )}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

export function ActionBar({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-3 rounded-xl border border-gray-100 bg-white/60 px-4 py-3",
        "dark-tenant:border-white/[0.06] dark-tenant:bg-surface-dark-card/40",
        className,
      )}
    >
      {children}
    </div>
  );
}
