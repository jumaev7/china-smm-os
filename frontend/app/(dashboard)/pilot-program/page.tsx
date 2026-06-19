"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import { Factory, Loader2, Plus, Trash2 } from "lucide-react";
import toast from "react-hot-toast";
import { platformOpsApi, PilotFactory, PilotFactoryStatus } from "@/lib/api";
import { AdminAuthGuard } from "@/components/auth/AdminAuthGuard";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import { PageHeader, PageShell } from "@/components/ui/design-system";

const STATUSES: PilotFactoryStatus[] = [
  "invited",
  "onboarding",
  "active",
  "feedback_phase",
  "completed",
];

const STATUS_VARIANT: Record<string, "success" | "warning" | "danger" | "neutral"> = {
  invited: "neutral",
  onboarding: "warning",
  active: "success",
  feedback_phase: "warning",
  completed: "success",
};

export default function PilotProgramPage() {
  return (
    <AdminAuthGuard requireAdmin>
      <PilotProgramContent />
    </AdminAuthGuard>
  );
}

function PilotProgramContent() {
  const qc = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({
    factory_name: "",
    country: "",
    industry: "",
    pilot_status: "invited" as PilotFactoryStatus,
    notes: "",
  });

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["pilot-program"],
    queryFn: () => platformOpsApi.listPilotFactories({ limit: 200 }).then((r) => r.data),
  });

  const createMutation = useMutation({
    mutationFn: () =>
      platformOpsApi.createPilotFactory({
        factory_name: form.factory_name.trim(),
        country: form.country.trim(),
        industry: form.industry.trim(),
        pilot_status: form.pilot_status,
        notes: form.notes.trim() || undefined,
      }).then((r) => r.data),
    onSuccess: () => {
      toast.success("Pilot factory added");
      setShowForm(false);
      setForm({ factory_name: "", country: "", industry: "", pilot_status: "invited", notes: "" });
      qc.invalidateQueries({ queryKey: ["pilot-program"] });
    },
    onError: () => toast.error("Failed to create pilot factory"),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => platformOpsApi.deletePilotFactory(id),
    onSuccess: () => {
      toast.success("Removed");
      qc.invalidateQueries({ queryKey: ["pilot-program"] });
    },
  });

  const updateStatus = useMutation({
    mutationFn: ({ id, status }: { id: string; status: PilotFactoryStatus }) =>
      platformOpsApi.updatePilotFactory(id, { pilot_status: status }).then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["pilot-program"] }),
  });

  if (isLoading) return <LoadingState />;
  if (isError) return <ErrorState message={String(error)} onRetry={refetch} />;

  const items = data?.items ?? [];

  return (
    <PageShell>
      <PageHeader
        title="Pilot Program"
        subtitle="Track real factory pilots — invited through completed"
        icon={Factory}
        actions={
          <button
            type="button"
            onClick={() => setShowForm(true)}
            className="inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700"
          >
            <Plus className="w-4 h-4" />
            Add Factory
          </button>
        }
      />

      {showForm && (
        <div className="mb-6 p-4 bg-white border border-gray-200 rounded-xl space-y-3">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <input
              className="border rounded-lg px-3 py-2 text-sm"
              placeholder="Factory name"
              value={form.factory_name}
              onChange={(e) => setForm({ ...form, factory_name: e.target.value })}
            />
            <input
              className="border rounded-lg px-3 py-2 text-sm"
              placeholder="Country"
              value={form.country}
              onChange={(e) => setForm({ ...form, country: e.target.value })}
            />
            <input
              className="border rounded-lg px-3 py-2 text-sm"
              placeholder="Industry"
              value={form.industry}
              onChange={(e) => setForm({ ...form, industry: e.target.value })}
            />
            <select
              className="border rounded-lg px-3 py-2 text-sm"
              value={form.pilot_status}
              onChange={(e) =>
                setForm({ ...form, pilot_status: e.target.value as PilotFactoryStatus })
              }
            >
              {STATUSES.map((s) => (
                <option key={s} value={s}>{s.replace("_", " ")}</option>
              ))}
            </select>
          </div>
          <textarea
            className="border rounded-lg px-3 py-2 text-sm w-full"
            placeholder="Notes"
            rows={2}
            value={form.notes}
            onChange={(e) => setForm({ ...form, notes: e.target.value })}
          />
          <div className="flex gap-2">
            <button
              type="button"
              disabled={!form.factory_name.trim() || createMutation.isPending}
              onClick={() => createMutation.mutate()}
              className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm disabled:opacity-50"
            >
              {createMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : "Save"}
            </button>
            <button type="button" onClick={() => setShowForm(false)} className="px-4 py-2 text-sm">
              Cancel
            </button>
          </div>
        </div>
      )}

      {items.length === 0 ? (
        <EmptyState title="No pilot factories yet" description="Add your first real factory pilot." />
      ) : (
        <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left text-gray-600">
              <tr>
                <th className="px-4 py-3">Factory</th>
                <th className="px-4 py-3">Country</th>
                <th className="px-4 py-3">Industry</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Score</th>
                <th className="px-4 py-3">Dates</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {items.map((row: PilotFactory) => (
                <tr key={row.id} className="border-t border-gray-100">
                  <td className="px-4 py-3 font-medium">{row.factory_name}</td>
                  <td className="px-4 py-3">{row.country || "—"}</td>
                  <td className="px-4 py-3">{row.industry || "—"}</td>
                  <td className="px-4 py-3">
                    <select
                      value={row.pilot_status}
                      onChange={(e) =>
                        updateStatus.mutate({
                          id: row.id,
                          status: e.target.value as PilotFactoryStatus,
                        })
                      }
                      className="text-xs border rounded px-2 py-1"
                    >
                      {STATUSES.map((s) => (
                        <option key={s} value={s}>{s.replace("_", " ")}</option>
                      ))}
                    </select>
                  </td>
                  <td className="px-4 py-3 tabular-nums">{row.success_score ?? "—"}</td>
                  <td className="px-4 py-3 text-gray-500 text-xs">
                    {row.start_date ? format(parseISO(row.start_date), "MMM d, yyyy") : "—"}
                    {row.end_date ? ` → ${format(parseISO(row.end_date), "MMM d, yyyy")}` : ""}
                  </td>
                  <td className="px-4 py-3">
                    <button
                      type="button"
                      onClick={() => deleteMutation.mutate(row.id)}
                      className="text-red-600 hover:text-red-800"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </PageShell>
  );
}
