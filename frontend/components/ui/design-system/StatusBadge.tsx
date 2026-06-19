import { cn } from "@/lib/utils";
import { STATUS_VARIANT_CLASSES, type StatusVariant } from "@/lib/design-system";

export function StatusBadge({
  variant = "neutral",
  children,
  className,
  dot,
}: {
  variant?: StatusVariant;
  children: React.ReactNode;
  className?: string;
  dot?: boolean;
}) {
  return (
    <span
      className={cn(
        "status-badge",
        STATUS_VARIANT_CLASSES[variant],
        className,
      )}
    >
      {dot && (
        <span
          className={cn(
            "w-1.5 h-1.5 rounded-full shrink-0",
            variant === "success" && "bg-success-600",
            variant === "warning" && "bg-warning-600",
            variant === "danger" && "bg-danger-600",
            variant === "info" && "bg-info-600",
            variant === "neutral" && "bg-gray-400",
          )}
        />
      )}
      {children}
    </span>
  );
}
