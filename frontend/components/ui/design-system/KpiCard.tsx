import Link from "next/link";
import { ArrowUpRight, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export function KpiCard({
  label,
  value,
  href,
  icon: Icon,
  iconClassName = "bg-brand-50 text-brand-600",
  sub,
  trend,
  className,
}: {
  label: string;
  value: string | number;
  href?: string;
  icon?: LucideIcon;
  iconClassName?: string;
  sub?: string;
  trend?: { value: string; positive?: boolean };
  className?: string;
}) {
  const inner = (
    <>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="kpi-label">{label}</p>
          <p className="kpi-value mt-1.5">{value}</p>
          {sub && <p className="text-[11px] text-gray-500 mt-1 truncate">{sub}</p>}
          {trend && (
            <p
              className={cn(
                "text-[11px] font-medium mt-1",
                trend.positive ? "text-success-700" : "text-gray-500",
              )}
            >
              {trend.value}
            </p>
          )}
        </div>
        {Icon && (
          <div
            className={cn(
              "w-10 h-10 rounded-xl flex items-center justify-center shrink-0 shadow-sm",
              iconClassName,
            )}
          >
            <Icon size={18} />
          </div>
        )}
      </div>
      {href && (
        <span className="absolute top-3 right-3 opacity-0 group-hover:opacity-100 transition-opacity text-brand-500">
          <ArrowUpRight size={14} />
        </span>
      )}
    </>
  );

  const cardClass = cn(
    "card-premium p-5 relative group transition-all duration-200",
    href && "hover:shadow-card-hover hover:border-brand-200/60 cursor-pointer",
    className,
  );

  if (href) {
    return (
      <Link href={href} className={cardClass}>
        {inner}
      </Link>
    );
  }

  return <div className={cardClass}>{inner}</div>;
}
