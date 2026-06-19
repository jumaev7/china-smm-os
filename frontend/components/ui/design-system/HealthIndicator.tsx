import { cn } from "@/lib/utils";
import { healthScoreVariant } from "@/lib/design-system";

const RING_COLORS: Record<string, string> = {
  success: "border-success-400 text-success-700",
  warning: "border-warning-400 text-warning-700",
  danger: "border-danger-400 text-danger-700",
};

const BAR_COLORS: Record<string, string> = {
  success: "bg-success-500",
  warning: "bg-warning-500",
  danger: "bg-danger-500",
};

export function HealthIndicator({
  score,
  label,
  size = "md",
  showBar = true,
}: {
  score: number;
  label?: string;
  size?: "sm" | "md" | "lg";
  showBar?: boolean;
}) {
  const variant = healthScoreVariant(score);
  const dim =
    size === "lg" ? "w-24 h-24 text-3xl border-[5px]" : size === "sm" ? "w-14 h-14 text-lg border-2" : "w-20 h-20 text-2xl border-[4px]";

  return (
    <div className="flex items-center gap-3">
      <div
        className={cn(
          "rounded-full border font-bold tabular-nums flex items-center justify-center bg-white shadow-sm",
          dim,
          RING_COLORS[variant],
        )}
        role="img"
        aria-label={label ? `${label}: ${score}` : `Health score ${score}`}
      >
        {Math.round(score)}
      </div>
      {(label || showBar) && (
        <div className="space-y-1.5 min-w-[100px]">
          {label && <p className="text-xs font-semibold text-navy-800">{label}</p>}
          {showBar && (
            <div className="h-1.5 w-full max-w-[120px] rounded-full bg-gray-100 overflow-hidden">
              <div
                className={cn("h-full rounded-full transition-all", BAR_COLORS[variant])}
                style={{ width: `${Math.min(100, Math.max(0, score))}%` }}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
