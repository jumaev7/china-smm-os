"use client";

import { cn } from "@/lib/utils";

export interface BarChartDatum {
  label: string;
  value: number;
  sublabel?: string;
}

interface Props {
  data: BarChartDatum[];
  maxBars?: number;
  valueSuffix?: string;
  className?: string;
  barClassName?: string;
}

export function SimpleBarChart({
  data,
  maxBars = 14,
  valueSuffix = "",
  className,
  barClassName = "bg-brand-500",
}: Props) {
  const visible = data.slice(-maxBars);
  const max = Math.max(...visible.map((d) => d.value), 1);

  if (visible.length === 0) {
    return <p className="text-xs text-gray-400 py-6 text-center">No data yet</p>;
  }

  return (
    <div className={cn("flex items-end gap-1 h-36", className)}>
      {visible.map((d) => {
        const height = Math.max(4, Math.round((d.value / max) * 100));
        return (
          <div
            key={d.label}
            className="flex-1 min-w-0 flex flex-col items-center justify-end gap-1"
            title={`${d.label}: ${d.value}${valueSuffix}${d.sublabel ? ` — ${d.sublabel}` : ""}`}
          >
            <span className="text-[9px] text-gray-500 tabular-nums">{d.value > 0 ? d.value : ""}</span>
            <div
              className={cn("w-full rounded-t transition-all", barClassName)}
              style={{ height: `${height}%` }}
            />
            <span className="text-[8px] text-gray-400 truncate w-full text-center">{d.label}</span>
          </div>
        );
      })}
    </div>
  );
}

export function HorizontalBarChart({
  data,
  className,
  barClassName = "bg-brand-500",
}: {
  data: BarChartDatum[];
  className?: string;
  barClassName?: string;
}) {
  const max = Math.max(...data.map((d) => d.value), 1);

  if (data.length === 0) {
    return <p className="text-xs text-gray-400 py-4 text-center">No data yet</p>;
  }

  return (
    <div className={cn("space-y-2", className)}>
      {data.map((d) => {
        const width = Math.max(2, Math.round((d.value / max) * 100));
        return (
          <div key={d.label}>
            <div className="flex justify-between text-xs mb-0.5">
              <span className="font-medium text-gray-700 truncate">{d.label}</span>
              <span className="text-gray-500 tabular-nums shrink-0 ml-2">
                {d.value}
                {d.sublabel ? ` · ${d.sublabel}` : ""}
              </span>
            </div>
            <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
              <div
                className={cn("h-full rounded-full", barClassName)}
                style={{ width: `${width}%` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}
