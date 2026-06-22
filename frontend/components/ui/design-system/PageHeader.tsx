import { type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export function PageHeader({
  title,
  subtitle,
  icon: Icon,
  iconClassName = "text-brand-600 dark-tenant:text-violet-400",
  actions,
  badge,
  className,
}: {
  title: string;
  subtitle?: string;
  icon?: LucideIcon;
  iconClassName?: string;
  actions?: React.ReactNode;
  badge?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col sm:flex-row sm:items-start justify-between gap-4",
        className,
      )}
    >
      <div className="min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          {Icon && (
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-50 border border-brand-100 shadow-sm shrink-0 dark-tenant:bg-violet-500/10 dark-tenant:border-violet-500/20">
              <Icon size={20} className={iconClassName} />
            </span>
          )}
          <div>
            <h1 className="page-title flex items-center gap-2">
              {title}
              {badge}
            </h1>
            {subtitle && <p className="page-subtitle mt-1">{subtitle}</p>}
          </div>
        </div>
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2 shrink-0">{actions}</div>}
    </div>
  );
}

export function PageSection({
  title,
  description,
  action,
  children,
  className,
}: {
  title: string;
  description?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("space-y-3", className)}>
      <div className="flex items-start justify-between gap-2">
        <div>
          <h2 className="section-title">{title}</h2>
          {description && <p className="text-xs text-gray-500 mt-0.5 dark-tenant:text-slate-500">{description}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

export function PageShell({
  children,
  wide,
  className,
}: {
  children: React.ReactNode;
  wide?: boolean;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "p-6 mx-auto space-y-6 animate-fade-in",
        wide ? "max-w-7xl" : "max-w-6xl",
        className,
      )}
    >
      {children}
    </div>
  );
}
