import { cn } from "@/lib/utils";
import { healthScoreVariant } from "@/lib/design-system";

export function MatchScoreIndicator({
  score,
  confidence,
  size = "md",
  showConfidence = false,
  className,
}: {
  score: number;
  confidence?: number;
  size?: "sm" | "md";
  showConfidence?: boolean;
  className?: string;
}) {
  const variant = healthScoreVariant(score);
  const barColor =
    variant === "success"
      ? "bg-emerald-500"
      : variant === "warning"
        ? "bg-amber-500"
        : "bg-red-500";

  return (
    <div className={cn("space-y-1", className)}>
      <div className="flex items-center justify-between gap-2">
        <span
          className={cn(
            "font-semibold tabular-nums",
            size === "sm" ? "text-xs" : "text-sm",
            variant === "success" && "text-emerald-700",
            variant === "warning" && "text-amber-700",
            variant === "danger" && "text-red-700",
          )}
        >
          {score}%
        </span>
        {showConfidence && confidence != null && (
          <span className="text-[10px] text-gray-400">conf {confidence}%</span>
        )}
      </div>
      <div className={cn("rounded-full bg-gray-100 overflow-hidden", size === "sm" ? "h-1" : "h-1.5")}>
        <div
          className={cn("h-full rounded-full transition-all", barColor)}
          style={{ width: `${Math.min(100, Math.max(0, score))}%` }}
        />
      </div>
    </div>
  );
}
