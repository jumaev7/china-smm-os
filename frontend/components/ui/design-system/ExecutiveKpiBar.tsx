import { cn } from "@/lib/utils";
import { HealthIndicator } from "./HealthIndicator";

export type ExecutiveKpiItem = {
  label: string;
  value: string | number;
  href?: string;
  hint?: string;
};

export function ExecutiveKpiBar({
  items,
  healthScore,
  healthLabel = "Business health",
  className,
}: {
  items: ExecutiveKpiItem[];
  healthScore?: number;
  healthLabel?: string;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "rounded-2xl border border-navy-100/80 bg-gradient-to-br from-white via-white to-brand-50/30 p-4 shadow-card",
        className,
      )}
    >
      <div className="flex flex-col lg:flex-row lg:items-center gap-4">
        {healthScore != null && (
          <div className="flex items-center gap-4 shrink-0 lg:pr-6 lg:border-r border-gray-100">
            <HealthIndicator score={healthScore} size="md" label={healthLabel} />
          </div>
        )}
        <div className="flex-1 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 min-w-0">
          {items.map((item) => (
            <div
              key={item.label}
              className="rounded-xl bg-white/80 border border-gray-100/80 px-3 py-2.5 hover:border-brand-200/50 transition-colors"
            >
              <p className="kpi-label truncate">{item.label}</p>
              <p className="text-lg font-semibold text-navy-900 tabular-nums mt-0.5 truncate">
                {item.value}
              </p>
              {item.hint && (
                <p className="text-[10px] text-gray-400 mt-0.5 truncate">{item.hint}</p>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
