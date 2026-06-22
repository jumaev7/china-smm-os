"use client";

import Link from "next/link";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import { CalendarClock, Check, Loader2, Pencil } from "lucide-react";
import toast from "react-hot-toast";
import {
  communicationHubApi,
  type CommunicationFollowUp,
  type FollowUpBucket,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import { PageHeader, PageSection, PageShell, StatusBadge } from "@/components/ui/design-system";
import { useTranslation } from "@/lib/I18nProvider";

const BUCKETS: { id: FollowUpBucket | ""; labelKey: string }[] = [
  { id: "", labelKey: "communicationsHub.followups.all" },
  { id: "overdue", labelKey: "communicationsHub.followups.overdue" },
  { id: "today", labelKey: "communicationsHub.followups.today" },
  { id: "upcoming", labelKey: "communicationsHub.followups.upcoming" },
];

function FollowUpCard({
  item,
  onComplete,
  onReschedule,
  completing,
}: {
  item: CommunicationFollowUp;
  onComplete: () => void;
  onReschedule: (dueDate: string, assignedUser?: string) => void;
  completing: boolean;
}) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const [dueLocal, setDueLocal] = useState(
    item.due_date ? format(parseISO(item.due_date), "yyyy-MM-dd'T'HH:mm") : "",
  );
  const [assignee, setAssignee] = useState(item.assigned_user ?? "");

  return (
    <div className="card p-4 space-y-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-gray-900">{item.title}</p>
          {item.thread_title && (
            <p className="text-xs text-gray-500 mt-0.5">
              {item.thread_title}
              {item.channel ? ` · ${item.channel}` : ""}
            </p>
          )}
        </div>
        <StatusBadge
          variant={item.is_overdue ? "danger" : item.status === "completed" ? "success" : "warning"}
        >
          {item.status}
        </StatusBadge>
      </div>
      {item.description && <p className="text-xs text-gray-600">{item.description}</p>}
      <p className="text-[11px] text-gray-400">
        {t("communicationsHub.due")}: {format(parseISO(item.due_date), "MMM d, yyyy HH:mm")}
      </p>

      {editing ? (
        <div className="space-y-2 pt-2 border-t border-gray-100">
          <input
            type="datetime-local"
            className="input text-sm w-full"
            value={dueLocal}
            onChange={(e) => setDueLocal(e.target.value)}
          />
          <input
            className="input text-sm w-full"
            placeholder={t("communicationsHub.assignee")}
            value={assignee}
            onChange={(e) => setAssignee(e.target.value)}
          />
          <div className="flex gap-2">
            <button
              type="button"
              className="btn-primary text-xs"
              onClick={() => {
                if (!dueLocal) return;
                onReschedule(new Date(dueLocal).toISOString(), assignee || undefined);
                setEditing(false);
              }}
            >
              {t("common.save")}
            </button>
            <button type="button" className="btn-secondary text-xs" onClick={() => setEditing(false)}>
              {t("common.cancel")}
            </button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2 pt-1">
          {item.assigned_user && (
            <span className="text-[10px] px-2 py-0.5 rounded bg-gray-50 text-gray-600">
              {item.assigned_user}
            </span>
          )}
          {item.status === "pending" && (
            <>
              <button
                type="button"
                className="btn-primary text-xs flex items-center gap-1"
                disabled={completing}
                onClick={onComplete}
              >
                {completing ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
                {t("communicationsHub.markCompleted")}
              </button>
              <button
                type="button"
                className="btn-secondary text-xs flex items-center gap-1"
                onClick={() => setEditing(true)}
              >
                <Pencil size={12} />
                {t("communicationsHub.reschedule")}
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}

export default function CommunicationsFollowupsPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [bucket, setBucket] = useState<FollowUpBucket | "">("");

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["communication-followups", bucket],
    queryFn: () =>
      communicationHubApi
        .listFollowups({ bucket: bucket || undefined, limit: 100 })
        .then((r) => r.data),
  });

  const completeMut = useMutation({
    mutationFn: (id: string) => communicationHubApi.completeFollowup(id),
    onSuccess: () => {
      toast.success(t("communicationsHub.followUpCompleted"));
      qc.invalidateQueries({ queryKey: ["communication-followups"] });
      qc.invalidateQueries({ queryKey: ["communication-hub-dashboard"] });
    },
    onError: () => toast.error(t("communicationsHub.actionError")),
  });

  const updateMut = useMutation({
    mutationFn: ({ id, due_date, assigned_user }: { id: string; due_date: string; assigned_user?: string }) =>
      communicationHubApi.updateFollowup(id, { due_date, assigned_user }),
    onSuccess: () => {
      toast.success(t("communicationsHub.followUpUpdated"));
      qc.invalidateQueries({ queryKey: ["communication-followups"] });
    },
    onError: () => toast.error(t("communicationsHub.actionError")),
  });

  const [completingId, setCompletingId] = useState<string | null>(null);

  return (
    <PageShell>
      <PageHeader
        title={t("communicationsHub.followupsTitle")}
        subtitle={t("communicationsHub.followupsSubtitle")}
        icon={CalendarClock}
      />

      <div className="flex flex-wrap gap-2 mt-4">
        {BUCKETS.map((b) => (
          <button
            key={b.id || "all"}
            type="button"
            onClick={() => setBucket(b.id)}
            className={cn(
              "text-sm px-3 py-1.5 rounded-lg border",
              bucket === b.id
                ? "bg-brand-50 border-brand-200 text-brand-800"
                : "border-gray-200 text-gray-600",
            )}
          >
            {t(b.labelKey)}
            {data && b.id === "overdue" && data.overdue_count > 0 && (
              <span className="ml-1 text-red-600">({data.overdue_count})</span>
            )}
            {data && b.id === "today" && data.today_count > 0 && (
              <span className="ml-1 text-amber-600">({data.today_count})</span>
            )}
          </button>
        ))}
      </div>

      {isLoading ? (
        <LoadingState message={t("communicationsHub.loadingFollowups")} className="mt-4" />
      ) : isError || !data ? (
        <ErrorState message={t("communicationsHub.loadError")} onRetry={() => refetch()} className="mt-4" />
      ) : data.items.length === 0 ? (
        <EmptyState
          title={t("communicationsHub.emptyFollowUps")}
          description={t("communicationsHub.emptyFollowUpsHint")}
          action={
            <Link href="/communications/inbox" className="btn-primary text-sm">
              {t("communicationsHub.openInbox")}
            </Link>
          }
          className="mt-4"
        />
      ) : (
        <PageSection title={t("communicationsHub.followupsList")} className="mt-4">
          <div className="grid md:grid-cols-2 gap-3">
            {data.items.map((item) => (
              <FollowUpCard
                key={item.id}
                item={item}
                completing={completingId === item.id}
                onComplete={() => {
                  setCompletingId(item.id);
                  completeMut.mutate(item.id, { onSettled: () => setCompletingId(null) });
                }}
                onReschedule={(dueDate, assignedUser) =>
                  updateMut.mutate({
                    id: item.id,
                    due_date: dueDate,
                    assigned_user: assignedUser,
                  })
                }
              />
            ))}
          </div>
        </PageSection>
      )}
    </PageShell>
  );
}
