"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import { MessageSquarePlus, Send } from "lucide-react";
import toast from "react-hot-toast";
import { platformOpsApi } from "@/lib/api";
import { AdminAuthGuard } from "@/components/auth/AdminAuthGuard";
import { readActiveSession, hasStoredAdminToken } from "@/lib/session-sync";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import { PageHeader, PageShell } from "@/components/ui/design-system";

const CATEGORIES = ["ui", "performance", "content", "crm", "communication", "ai", "billing", "other"];
const TYPES = [
  { value: "bug", label: "Bug Report" },
  { value: "feature_request", label: "Feature Request" },
  { value: "suggestion", label: "Suggestion" },
];

export default function FeedbackPage() {
  const isAdminView = readActiveSession() === "admin" && hasStoredAdminToken();
  return isAdminView ? (
    <AdminAuthGuard requireAdmin>
      <FeedbackAdminView />
    </AdminAuthGuard>
  ) : (
    <FeedbackTenantView />
  );
}

function FeedbackTenantView() {
  const qc = useQueryClient();
  const [form, setForm] = useState({
    feedback_type: "bug",
    category: "ui",
    title: "",
    description: "",
  });

  const { data: myFeedback, isLoading } = useQuery({
    queryKey: ["my-feedback"],
    queryFn: () => platformOpsApi.listMyFeedback().then((r) => r.data),
  });

  const submitMutation = useMutation({
    mutationFn: () => platformOpsApi.submitFeedback(form).then((r) => r.data),
    onSuccess: () => {
      toast.success("Feedback submitted — thank you!");
      setForm({ feedback_type: "bug", category: "ui", title: "", description: "" });
      qc.invalidateQueries({ queryKey: ["my-feedback"] });
    },
    onError: () => toast.error("Failed to submit feedback"),
  });

  return (
    <PageShell>
      <PageHeader
        title="Feedback Center"
        subtitle="Report bugs, request features, or share suggestions"
        icon={MessageSquarePlus}
      />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white border border-gray-200 rounded-xl p-4 space-y-3">
          <select
            className="border rounded-lg px-3 py-2 text-sm w-full"
            value={form.feedback_type}
            onChange={(e) => setForm({ ...form, feedback_type: e.target.value })}
          >
            {TYPES.map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </select>
          <select
            className="border rounded-lg px-3 py-2 text-sm w-full"
            value={form.category}
            onChange={(e) => setForm({ ...form, category: e.target.value })}
          >
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
          <input
            className="border rounded-lg px-3 py-2 text-sm w-full"
            placeholder="Title"
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
          />
          <textarea
            className="border rounded-lg px-3 py-2 text-sm w-full"
            placeholder="Describe the issue or idea..."
            rows={4}
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
          />
          <button
            type="button"
            disabled={!form.title.trim() || !form.description.trim() || submitMutation.isPending}
            onClick={() => submitMutation.mutate()}
            className="inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm disabled:opacity-50"
          >
            <Send className="w-4 h-4" />
            Submit
          </button>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl p-4">
          <h3 className="font-medium text-gray-900 mb-3">Your submissions</h3>
          {isLoading ? (
            <LoadingState />
          ) : (myFeedback?.items?.length ?? 0) === 0 ? (
            <EmptyState title="No feedback yet" />
          ) : (
            <ul className="space-y-3">
              {myFeedback?.items.map((item) => (
                <li key={item.id} className="border-b border-gray-100 pb-3">
                  <div className="font-medium text-sm">{item.title}</div>
                  <div className="text-xs text-gray-500">
                    {item.feedback_type} · {item.category} · {format(parseISO(item.created_at), "MMM d, yyyy")}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </PageShell>
  );
}

function FeedbackAdminView() {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["all-feedback"],
    queryFn: () => platformOpsApi.listFeedback({ limit: 100 }).then((r) => r.data),
  });

  if (isLoading) return <LoadingState />;
  if (isError) return <ErrorState message={String(error)} onRetry={refetch} />;

  const items = data?.items ?? [];

  return (
    <PageShell>
      <PageHeader
        title="Feedback Center"
        subtitle="All pilot factory feedback submissions"
        icon={MessageSquarePlus}
      />
      {items.length === 0 ? (
        <EmptyState title="No feedback yet" />
      ) : (
        <div className="space-y-3">
          {items.map((item) => (
            <div key={item.id} className="bg-white border border-gray-200 rounded-xl p-4">
              <div className="flex justify-between gap-2">
                <span className="font-medium">{item.title}</span>
                <span className="text-xs text-gray-500">
                  {format(parseISO(item.created_at), "MMM d, yyyy HH:mm")}
                </span>
              </div>
              <div className="text-xs text-gray-500 mt-1">
                {item.feedback_type} · {item.category} · {item.status}
              </div>
              <p className="text-sm text-gray-700 mt-2">{item.description}</p>
            </div>
          ))}
        </div>
      )}
    </PageShell>
  );
}
