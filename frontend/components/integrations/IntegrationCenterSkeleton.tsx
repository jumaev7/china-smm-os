"use client";

import { Skeleton } from "@/components/ui/Skeleton";

export function IntegrationCenterSkeleton() {
  return (
    <div className="space-y-6 animate-pulse" aria-busy="true" aria-label="Loading integrations">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-24 rounded-2xl" />
        ))}
      </div>
      <Skeleton className="h-10 w-full max-w-2xl rounded-xl" />
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-44 rounded-2xl" />
        ))}
      </div>
    </div>
  );
}
