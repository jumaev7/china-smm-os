"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Plus, Workflow } from "lucide-react";
import { PageShell } from "@/components/ui/design-system";
import { ErrorState } from "@/components/ui/PageStates";
import { useWorkflowMutations, useWorkflowsList } from "@/lib/workflow-builder-hooks";
import { cn } from "@/lib/utils";

const STATUS_STYLES: Record<string, string> = {
  draft: "text-amber-800 bg-amber-50",
  published: "text-emerald-800 bg-emerald-50",
  paused: "text-slate-700 bg-slate-100",
  archived: "text-stone-600 bg-stone-100",
};

export default function WorkflowsListPage() {
  const router = useRouter();
  const { data, isLoading, isError, refetch } = useWorkflowsList();
  const { create } = useWorkflowMutations();

  const handleCreate = async () => {
    const created = await create.mutateAsync({
      name: "New workflow",
      description: "",
      definition: {
        schema_version: 1,
        trigger: { event: "tenant.content.publish_failed" },
        conditions: { operator: "all", items: [] },
        steps: [
          {
            id: "step_1",
            type: "action",
            action_type: "create_notification",
            config: {
              title: "Workflow alert: {resource_name}",
              body: "A publish failure matched this workflow.",
              category: "automation",
              severity: "warning",
            },
          },
        ],
        failure_policy: "stop_on_failure",
      },
    });
    router.push(`/automation/workflows/${created.id}`);
  };

  return (
    <PageShell>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm text-muted-foreground">
            <Link href="/automation" className="underline-offset-2 hover:underline">
              Automation Center
            </Link>
            {" / "}
            Workflows
          </p>
          <h1 className="mt-1 flex items-center gap-2 text-2xl font-semibold tracking-tight">
            <Workflow className="h-6 w-6" />
            Workflow Builder
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            Versioned multi-step workflows with a safe rules engine. Simple one-action
            automations remain on the Automation Center home.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void handleCreate()}
          disabled={create.isPending}
          className="inline-flex items-center gap-2 rounded-md bg-foreground px-3 py-2 text-sm font-medium text-background disabled:opacity-60"
        >
          <Plus className="h-4 w-4" />
          New workflow
        </button>
      </div>

      <div className="mb-4 flex flex-wrap gap-2 text-sm">
        <Link href="/automation" className="rounded-md border px-3 py-1.5 hover:bg-muted/50">
          Simple Automations
        </Link>
        <span className="rounded-md border border-foreground/20 bg-muted/40 px-3 py-1.5 font-medium">
          Workflows
        </span>
        <Link href="/automation" className="rounded-md border px-3 py-1.5 hover:bg-muted/50">
          Scheduler Jobs
        </Link>
        <Link href="/automation" className="rounded-md border px-3 py-1.5 hover:bg-muted/50">
          Executions
        </Link>
      </div>

      {isLoading && <p className="text-sm text-muted-foreground">Loading workflows…</p>}
      {isError && <ErrorState title="Failed to load workflows" onRetry={() => void refetch()} />}

      {!isLoading && !isError && (data?.items.length ?? 0) === 0 && (
        <div className="rounded-lg border border-dashed px-6 py-12 text-center">
          <p className="text-sm text-muted-foreground">No workflows yet. Create a draft to get started.</p>
        </div>
      )}

      <ul className="space-y-2">
        {data?.items.map((wf) => (
          <li key={wf.id}>
            <Link
              href={`/automation/workflows/${wf.id}`}
              className="flex flex-wrap items-center justify-between gap-3 rounded-lg border px-4 py-3 transition hover:bg-muted/30"
            >
              <div>
                <p className="font-medium">{wf.name}</p>
                <p className="text-xs text-muted-foreground">
                  {wf.trigger_event ?? "No trigger"} · rev {wf.draft_revision}
                  {wf.active_version_number != null ? ` · v${wf.active_version_number} published` : ""}
                </p>
              </div>
              <span className={cn("rounded px-2 py-0.5 text-xs font-medium capitalize", STATUS_STYLES[wf.status])}>
                {wf.status}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </PageShell>
  );
}
