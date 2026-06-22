import Link from "next/link";
import { ArrowRight, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  dashboardMetricLabelClass,
  dashboardMetricTileClass,
  dashboardMetricValueClass,
  type DashboardMetricTone,
} from "@/lib/dashboardMetricStyles";

export function SectionCard({
  title,
  icon: Icon,
  iconClassName = "text-violet-400",
  href,
  linkLabel = "View all",
  children,
  className,
  footer,
}: {
  title: string;
  icon?: LucideIcon;
  iconClassName?: string;
  href?: string;
  linkLabel?: string;
  children: React.ReactNode;
  className?: string;
  footer?: React.ReactNode;
}) {
  return (
    <div className={cn("card-premium p-5 space-y-4", className)}>
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-semibold text-navy-900 dark-tenant:text-slate-100 flex items-center gap-2">
          {Icon && <Icon size={16} className={iconClassName} />}
          {title}
        </p>
        {href && (
          <Link
            href={href}
            className="text-xs text-brand-700 hover:text-brand-900 dark-tenant:text-violet-400 dark-tenant:hover:text-violet-300 flex items-center gap-1 transition-colors"
          >
            {linkLabel}
            <ArrowRight size={12} />
          </Link>
        )}
      </div>
      {children}
      {footer}
    </div>
  );
}

export function StatTile({
  label,
  value,
  href,
  tone = "neutral",
  className,
}: {
  label: string;
  value: string | number;
  href?: string;
  tone?: DashboardMetricTone | "info" | "success" | "warning" | "danger" | "violet";
  className?: string;
}) {
  const resolvedTone: DashboardMetricTone =
    tone === "info"
      ? "sky"
      : tone === "success"
        ? "success"
        : tone === "warning"
          ? "warning"
          : tone === "danger"
            ? "danger"
            : tone === "violet"
              ? "violet"
              : tone;

  const inner = (
    <>
      <p className={dashboardMetricValueClass(resolvedTone, "lg")}>{value}</p>
      <p className={cn(dashboardMetricLabelClass(resolvedTone), "mt-0.5 opacity-90")}>{label}</p>
    </>
  );

  const tileClass = cn(
    dashboardMetricTileClass(resolvedTone, { link: !!href }),
    "block text-left",
    className,
  );

  if (href) {
    return (
      <Link href={href} className={tileClass}>
        {inner}
      </Link>
    );
  }

  return <div className={tileClass}>{inner}</div>;
}
