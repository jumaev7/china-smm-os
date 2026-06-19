"use client";

import { useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import {
  ArrowLeft,
  Archive,
  CheckCircle,
  ClipboardList,
  Loader2,
  Pencil,
  Save,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  PlaybookStatus,
  PlaybookStepType,
  salesPlaybooksApi,
  SalesPlaybookStep,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { ErrorState, LoadingState } from "@/components/ui/PageStates";

const STATUS_STYLE: Record<PlaybookStatus, string> = {
  draft: "bg-gray-100 text-gray-700",
  active: "bg-emerald-100 text-emerald-800",
  archived: "bg-stone-100 text-stone-600",
};

const STEP_TYPE_LABELS: Record<PlaybookStepType, string> = {
  outreach: "Outreach",
  follow_up: "Follow-up",
  proposal: "Proposal",
  call: "Call",
  internal_task: "Internal task",
};

const STEP_TYPES: PlaybookStepType[] = ["outreach", "follow_up", "proposal", "call", "internal_task"];

export default function PlaybookDetailPage() {
  const { id } = useParams<{ id: string }>();
  const qc = useQueryClient();
  const [editingStepId, setEditingStepId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState<Partial<SalesPlaybookStep>>({});

  const { data: playbook, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["sales-playbook", id],
    queryFn: () => salesPlaybooksApi.get(id).then((r) => r.data),
  });

  const updateMutation = useMutation({
    mutationFn: (data: Parameters<typeof salesPlaybooksApi.update>[1]) =>
      salesPlaybooksApi.update(id, data).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sales-playbook", id] });
      qc.invalidateQueries({ queryKey: ["sales-playbooks"] });
      toast.success("Playbook updated");
    },
    onError: (err: Error) => toast.error(err.message || "Update failed"),
  });

  const updateStepMutation = useMutation({
    mutationFn: ({ stepId, data }: { stepId: string; data: Parameters<typeof salesPlaybooksApi.updateStep>[1] }) =>
      salesPlaybooksApi.updateStep(stepId, data).then((r) => r.data),
    onSuccess: () => {
      setEditingStepId(null);
      qc.invalidateQueries({ queryKey: ["sales-playbook", id] });
      toast.success("Step updated");
    },
    onError: (err: Error) => toast.error(err.message || "Step update failed"),
  });

  const startEditStep = (step: SalesPlaybookStep) => {
    setEditingStepId(step.id);
    setEditForm({
      title: step.title,
      instructions: step.instructions ?? "",
      template_text: step.template_text ?? "",
      delay_days: step.delay_days ?? 0,
      step_type: step.step_type,
    });
  };

  if (isLoading) return <LoadingState message="Loading playbook…" className="min-h-[40vh]" />;
  if (isError || !playbook) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "Playbook not found"}
        onRetry={() => refetch()}
        className="min-h-[40vh]"
      />
    );
  }

  const steps = [...(playbook.steps ?? [])].sort((a, b) => a.step_order - b.step_order);

  return (
    <div className="p-6 max-w-3xl mx-auto space-y-5">
      <div>
        <Link href="/sales-playbooks" className="text-xs text-gray-500 hover:text-gray-800 flex items-center gap-1 mb-2">
          <ArrowLeft size={12} />
          All playbooks
        </Link>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
              <ClipboardList size={20} className="text-violet-600" />
              {playbook.name}
            </h1>
            {playbook.description && (
              <p className="text-sm text-gray-500 mt-1">{playbook.description}</p>
            )}
            <p className="text-[10px] text-gray-400 mt-1">
              {playbook.product_category && `${playbook.product_category} · `}
              {playbook.buyer_type && `${playbook.buyer_type} · `}
              {playbook.country} · {playbook.channel} · {playbook.language.toUpperCase()}
              {playbook.demo_mode && " · Demo mode"}
            </p>
          </div>
          <span className={cn("text-xs px-2 py-1 rounded-full capitalize", STATUS_STYLE[playbook.status])}>
            {playbook.status}
          </span>
        </div>
      </div>

      <div className="card p-4 flex flex-wrap gap-2">
        {playbook.status !== "active" && playbook.status !== "archived" && (
          <button
            type="button"
            disabled={updateMutation.isPending}
            onClick={() => updateMutation.mutate({ status: "active" })}
            className="text-xs px-3 py-1.5 rounded border border-emerald-300 bg-emerald-50 text-emerald-900 flex items-center gap-1"
          >
            <CheckCircle size={12} />
            Activate
          </button>
        )}
        {playbook.status !== "archived" && (
          <button
            type="button"
            disabled={updateMutation.isPending}
            onClick={() => updateMutation.mutate({ status: "archived" })}
            className="text-xs px-3 py-1.5 rounded border border-gray-200 flex items-center gap-1"
          >
            <Archive size={12} />
            Archive
          </button>
        )}
        {playbook.status === "archived" && (
          <button
            type="button"
            disabled={updateMutation.isPending}
            onClick={() => updateMutation.mutate({ status: "draft" })}
            className="text-xs px-3 py-1.5 rounded border border-gray-200"
          >
            Restore to draft
          </button>
        )}
      </div>

      <div className="card p-4 space-y-4">
        <p className="text-xs font-semibold text-gray-900">Steps timeline</p>
        {steps.length === 0 ? (
          <p className="text-sm text-gray-500">No steps yet.</p>
        ) : (
          <ol className="space-y-4">
            {steps.map((step, idx) => (
              <li key={step.id} className="relative pl-6">
                {idx < steps.length - 1 && (
                  <span className="absolute left-[9px] top-6 bottom-0 w-px bg-gray-200" />
                )}
                <span className="absolute left-0 top-1 w-[18px] h-[18px] rounded-full bg-violet-100 border border-violet-300 text-[9px] font-bold text-violet-800 flex items-center justify-center">
                  {step.step_order}
                </span>

                {editingStepId === step.id ? (
                  <div className="rounded-lg border border-violet-200 bg-violet-50/30 p-3 space-y-2">
                    <select
                      className="input text-xs w-full"
                      value={editForm.step_type ?? step.step_type}
                      onChange={(e) => setEditForm((f) => ({ ...f, step_type: e.target.value as PlaybookStepType }))}
                    >
                      {STEP_TYPES.map((t) => (
                        <option key={t} value={t}>{STEP_TYPE_LABELS[t]}</option>
                      ))}
                    </select>
                    <input
                      className="input text-sm w-full"
                      value={editForm.title ?? ""}
                      onChange={(e) => setEditForm((f) => ({ ...f, title: e.target.value }))}
                    />
                    <textarea
                      className="input text-xs w-full min-h-[60px]"
                      placeholder="Instructions"
                      value={String(editForm.instructions ?? "")}
                      onChange={(e) => setEditForm((f) => ({ ...f, instructions: e.target.value }))}
                    />
                    <textarea
                      className="input text-xs w-full min-h-[80px] font-mono"
                      placeholder="Template text"
                      value={String(editForm.template_text ?? "")}
                      onChange={(e) => setEditForm((f) => ({ ...f, template_text: e.target.value }))}
                    />
                    <div className="flex items-center gap-2">
                      <label className="text-[10px] text-gray-500">Delay (days)</label>
                      <input
                        type="number"
                        min={0}
                        className="input text-xs w-20"
                        value={editForm.delay_days ?? 0}
                        onChange={(e) => setEditForm((f) => ({ ...f, delay_days: Number(e.target.value) }))}
                      />
                    </div>
                    <div className="flex gap-2">
                      <button
                        type="button"
                        disabled={updateStepMutation.isPending}
                        onClick={() =>
                          updateStepMutation.mutate({
                            stepId: step.id,
                            data: {
                              title: editForm.title,
                              instructions: editForm.instructions ?? undefined,
                              template_text: editForm.template_text ?? undefined,
                              delay_days: editForm.delay_days ?? undefined,
                              step_type: editForm.step_type,
                            },
                          })
                        }
                        className="text-xs px-2 py-1 rounded border border-emerald-300 bg-emerald-50 flex items-center gap-1"
                      >
                        {updateStepMutation.isPending ? <Loader2 size={10} className="animate-spin" /> : <Save size={10} />}
                        Save
                      </button>
                      <button type="button" className="text-xs px-2 py-1 rounded border" onClick={() => setEditingStepId(null)}>
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="rounded-lg border border-gray-200 bg-white p-3 space-y-1.5">
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <p className="text-sm font-medium text-gray-900">{step.title}</p>
                        <p className="text-[10px] text-violet-700 capitalize">
                          {STEP_TYPE_LABELS[step.step_type]}
                          {step.delay_days != null && step.delay_days > 0 && ` · Day ${step.delay_days}`}
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={() => startEditStep(step)}
                        className="text-[10px] px-2 py-0.5 rounded border border-gray-200 flex items-center gap-1"
                      >
                        <Pencil size={10} />
                        Edit
                      </button>
                    </div>
                    {step.instructions && (
                      <p className="text-xs text-gray-600">{step.instructions}</p>
                    )}
                    {step.template_text && (
                      <pre className="text-[11px] text-gray-700 whitespace-pre-wrap bg-gray-50 rounded p-2 font-sans">
                        {step.template_text}
                      </pre>
                    )}
                  </div>
                )}
              </li>
            ))}
          </ol>
        )}
      </div>

      <p className="text-[10px] text-gray-400 text-center">
        Updated {format(parseISO(playbook.updated_at), "MMM d, yyyy HH:mm")}
      </p>
    </div>
  );
}
