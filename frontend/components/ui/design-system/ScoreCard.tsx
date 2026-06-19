import { cn } from "@/lib/utils";
import { healthScoreVariant } from "@/lib/design-system";
import { StatusBadge } from "./StatusBadge";

export function ScoreCard({
  title,
  score,
  subtitle,
  metrics,
  className,
  children,
}: {
  title: string;
  score: number;
  subtitle?: string;
  metrics?: { label: string; value: string | number }[];
  className?: string;
  children?: React.ReactNode;
}) {
  const variant = healthScoreVariant(score);

  return (
    <div className={cn("card-premium p-5 space-y-4", className)}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-navy-900">{title}</h3>
          {subtitle && <p className="text-xs text-gray-500 mt-0.5">{subtitle}</p>}
        </div>
        <StatusBadge variant={variant} dot>
          {score}%
        </StatusBadge>
      </div>
      <div className="h-2 rounded-full bg-gray-100 overflow-hidden">
        <div
          className={cn(
            "h-full rounded-full transition-all duration-500",
            variant === "success" && "bg-gradient-to-r from-success-500 to-success-400",
            variant === "warning" && "bg-gradient-to-r from-warning-500 to-warning-400",
            variant === "danger" && "bg-gradient-to-r from-danger-500 to-danger-400",
          )}
          style={{ width: `${Math.min(100, Math.max(0, score))}%` }}
        />
      </div>
      {metrics && metrics.length > 0 && (
        <div className="grid grid-cols-2 gap-2 pt-1">
          {metrics.map((m) => (
            <div key={m.label} className="rounded-lg bg-gray-50/80 border border-gray-100 px-3 py-2">
              <p className="text-[10px] uppercase tracking-wide text-gray-400">{m.label}</p>
              <p className="text-sm font-semibold text-navy-900 tabular-nums mt-0.5">{m.value}</p>
            </div>
          ))}
        </div>
      )}
      {children}
    </div>
  );
}
