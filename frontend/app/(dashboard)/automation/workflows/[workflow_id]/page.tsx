"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { PageShell } from "@/components/ui/design-system";
import { ErrorState } from "@/components/ui/PageStates";
import {
  useWorkflowCatalog,
  useWorkflowDetail,
  useWorkflowMutations,
} from "@/lib/workflow-builder-hooks";
import { workflowsApi, type WorkflowTestResponse, type WorkflowValidateResponse } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useQuery } from "@tanstack/react-query";

type ConditionItem = {
  id: string;
  field: string;
  op: string;
  value?: unknown;
};

type ActionStep = {
  id: string;
  type: "action";
  action_type: string;
  config: Record<string, unknown>;
};

type DraftDefinition = {
  schema_version: number;
  trigger: { event: string };
  conditions: { operator: "all" | "any" | "none"; items: ConditionItem[] };
  steps: ActionStep[];
  failure_policy: "stop_on_failure";
};

function emptyDefinition(event: string): DraftDefinition {
  return {
    schema_version: 1,
    trigger: { event },
    conditions: { operator: "all", items: [] },
    steps: [],
    failure_policy: "stop_on_failure",
  };
}

function asDraft(raw: Record<string, unknown> | null | undefined, fallbackEvent: string): DraftDefinition {
  if (!raw || typeof raw !== "object") return emptyDefinition(fallbackEvent);
  const trigger = (raw.trigger as { event?: string } | undefined)?.event || fallbackEvent;
  const conditionsRaw = raw.conditions as { operator?: string; items?: ConditionItem[] } | undefined;
  const stepsRaw = Array.isArray(raw.steps) ? raw.steps : [];
  return {
    schema_version: 1,
    trigger: { event: trigger },
    conditions: {
      operator: (conditionsRaw?.operator as "all" | "any" | "none") || "all",
      items: Array.isArray(conditionsRaw?.items) ? conditionsRaw!.items : [],
    },
    steps: stepsRaw
      .filter((s): s is ActionStep => Boolean(s && typeof s === "object"))
      .map((s, i) => ({
        id: String((s as ActionStep).id || `step_${i + 1}`),
        type: "action",
        action_type: String((s as ActionStep).action_type || "create_notification"),
        config: ((s as ActionStep).config as Record<string, unknown>) || {},
      })),
    failure_policy: "stop_on_failure",
  };
}

export default function WorkflowEditorPage() {
  const params = useParams();
  const workflowId = String(params.workflow_id || "");
  const { data: workflow, isLoading, isError, refetch } = useWorkflowDetail(workflowId);
  const { data: catalog } = useWorkflowCatalog();
  const mutations = useWorkflowMutations(workflowId);

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [definition, setDefinition] = useState<DraftDefinition>(emptyDefinition("tenant.content.publish_failed"));
  const [revision, setRevision] = useState(1);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [validation, setValidation] = useState<WorkflowValidateResponse | null>(null);
  const [testResult, setTestResult] = useState<WorkflowTestResponse | null>(null);
  const [testPayloadText, setTestPayloadText] = useState('{"platform":"instagram","retryable":true}');

  const executionsQuery = useQuery({
    queryKey: ["workflow-executions", workflowId],
    queryFn: async () => (await workflowsApi.listExecutions(workflowId, { page_size: 20 })).data,
    enabled: Boolean(workflowId),
  });

  useEffect(() => {
    if (!workflow) return;
    setName(workflow.name);
    setDescription(workflow.description || "");
    setRevision(workflow.draft_revision);
    setDefinition(asDraft(workflow.draft_definition, workflow.trigger_event || "tenant.content.publish_failed"));
  }, [workflow]);

  const eventFields = useMemo(() => {
    const match = catalog?.events.find((e) => e.event === definition.trigger.event);
    return match?.fields ?? [];
  }, [catalog, definition.trigger.event]);

  const handleSave = async () => {
    setSaveError(null);
    try {
      const updated = await mutations.update.mutateAsync({
        id: workflowId,
        draft_revision: revision,
        name,
        description,
        definition: definition as unknown as Record<string, unknown>,
      });
      setRevision(updated.draft_revision);
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number; data?: { detail?: unknown } } })?.response?.status;
      const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      if (status === 409) {
        setSaveError("Draft conflict (409): another tab updated this workflow. Reload and retry.");
        await refetch();
      } else {
        setSaveError(typeof detail === "string" ? detail : "Save failed");
      }
    }
  };

  const handleValidate = async () => {
    const result = await mutations.validate.mutateAsync({
      id: workflowId,
      definition: definition as unknown as Record<string, unknown>,
    });
    setValidation(result);
  };

  const handlePublish = async () => {
    setSaveError(null);
    await handleSave();
    try {
      const published = await mutations.publish.mutateAsync(workflowId);
      setRevision(published.draft_revision);
      setValidation({ valid: true, errors: [], definition_hash: published.definition_hash });
      await refetch();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      setSaveError(typeof detail === "string" ? detail : JSON.stringify(detail) || "Publish failed");
    }
  };

  const handleTest = async () => {
    let payload: Record<string, unknown> = {};
    try {
      payload = JSON.parse(testPayloadText) as Record<string, unknown>;
    } catch {
      setSaveError("Test payload must be valid JSON with catalog fields only");
      return;
    }
    const result = await mutations.test.mutateAsync({ id: workflowId, synthetic_payload: payload });
    setTestResult(result);
  };

  const updateCondition = (index: number, patch: Partial<ConditionItem>) => {
    setDefinition((prev) => {
      const items = [...prev.conditions.items];
      items[index] = { ...items[index], ...patch };
      return { ...prev, conditions: { ...prev.conditions, items } };
    });
  };

  const updateStep = (index: number, patch: Partial<ActionStep>) => {
    setDefinition((prev) => {
      const steps = [...prev.steps];
      steps[index] = { ...steps[index], ...patch };
      return { ...prev, steps };
    });
  };

  if (isLoading) {
    return (
      <PageShell>
        <p className="text-sm text-muted-foreground">Loading workflow…</p>
      </PageShell>
    );
  }

  if (isError || !workflow) {
    return (
      <PageShell>
        <ErrorState title="Workflow not found" onRetry={() => void refetch()} />
      </PageShell>
    );
  }

  const canPublish = validation?.valid === true || workflow.draft_validation_status === "valid";

  return (
    <PageShell>
      <div className="mb-6">
        <p className="text-sm text-muted-foreground">
          <Link href="/automation" className="hover:underline">Automation Center</Link>
          {" / "}
          <Link href="/automation/workflows" className="hover:underline">Workflows</Link>
          {" / "}
          Editor
        </p>
        <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">{workflow.name}</h1>
            <p className="text-sm text-muted-foreground">
              Status: {workflow.status} · draft revision {revision}
              {workflow.active_version_number != null ? ` · active v${workflow.active_version_number}` : ""}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={() => void handleSave()} className="rounded-md border px-3 py-1.5 text-sm">
              Save draft
            </button>
            <button type="button" onClick={() => void handleValidate()} className="rounded-md border px-3 py-1.5 text-sm">
              Validate
            </button>
            <button
              type="button"
              onClick={() => void handlePublish()}
              disabled={!canPublish && validation?.valid !== true}
              className="rounded-md bg-foreground px-3 py-1.5 text-sm font-medium text-background disabled:opacity-50"
            >
              Publish
            </button>
            {workflow.status === "published" && (
              <button type="button" onClick={() => void mutations.pause.mutateAsync(workflowId)} className="rounded-md border px-3 py-1.5 text-sm">
                Pause
              </button>
            )}
            {workflow.status === "paused" && (
              <button type="button" onClick={() => void mutations.resume.mutateAsync(workflowId)} className="rounded-md border px-3 py-1.5 text-sm">
                Resume
              </button>
            )}
            <button type="button" onClick={() => void mutations.archive.mutateAsync(workflowId)} className="rounded-md border px-3 py-1.5 text-sm">
              Archive
            </button>
          </div>
        </div>
        {saveError && <p className="mt-2 text-sm text-red-700">{saveError}</p>}
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="space-y-6">
          <section className="space-y-3 rounded-lg border p-4">
            <h2 className="font-medium">Workflow details</h2>
            <label className="block text-sm">
              Name
              <input
                className="mt-1 w-full rounded-md border px-3 py-2"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            <label className="block text-sm">
              Description
              <textarea
                className="mt-1 w-full rounded-md border px-3 py-2"
                rows={2}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </label>
          </section>

          <section className="space-y-3 rounded-lg border p-4">
            <h2 className="font-medium">Trigger</h2>
            <select
              className="w-full rounded-md border px-3 py-2 text-sm"
              value={definition.trigger.event}
              onChange={(e) =>
                setDefinition((prev) => ({
                  ...prev,
                  trigger: { event: e.target.value },
                  conditions: { operator: "all", items: [] },
                }))
              }
            >
              {(catalog?.events ?? []).map((ev) => (
                <option key={ev.event} value={ev.event}>
                  {ev.event}
                </option>
              ))}
            </select>
          </section>

          <section className="space-y-3 rounded-lg border p-4">
            <div className="flex items-center justify-between">
              <h2 className="font-medium">Root conditions</h2>
              <select
                className="rounded-md border px-2 py-1 text-sm"
                value={definition.conditions.operator}
                onChange={(e) =>
                  setDefinition((prev) => ({
                    ...prev,
                    conditions: {
                      ...prev.conditions,
                      operator: e.target.value as "all" | "any" | "none",
                    },
                  }))
                }
              >
                <option value="all">all</option>
                <option value="any">any</option>
                <option value="none">none</option>
              </select>
            </div>
            {definition.conditions.items.map((item, index) => {
              const field = eventFields.find((f) => f.name === item.field);
              const operators = field?.operators ?? ["equals"];
              return (
                <div key={item.id} className="grid gap-2 rounded-md border p-3 md:grid-cols-4">
                  <select
                    className="rounded-md border px-2 py-1.5 text-sm"
                    value={item.field}
                    onChange={(e) => updateCondition(index, { field: e.target.value, op: "equals" })}
                  >
                    {eventFields.map((f) => (
                      <option key={f.name} value={f.name}>
                        {f.name}
                      </option>
                    ))}
                  </select>
                  <select
                    className="rounded-md border px-2 py-1.5 text-sm"
                    value={item.op}
                    onChange={(e) => updateCondition(index, { op: e.target.value })}
                  >
                    {operators.map((op) => (
                      <option key={op} value={op}>
                        {op}
                      </option>
                    ))}
                  </select>
                  <input
                    className="rounded-md border px-2 py-1.5 text-sm md:col-span-1"
                    value={item.value == null ? "" : String(item.value)}
                    onChange={(e) => {
                      const raw = e.target.value;
                      let value: unknown = raw;
                      if (field?.type === "boolean") value = raw === "true";
                      else if (field?.type === "integer") value = Number.parseInt(raw, 10);
                      else if (field?.type === "number") value = Number.parseFloat(raw);
                      updateCondition(index, { value });
                    }}
                    disabled={item.op === "exists" || item.op === "not_exists" || item.op === "is_true" || item.op === "is_false"}
                  />
                  <button
                    type="button"
                    className="rounded-md border px-2 py-1 text-sm"
                    onClick={() =>
                      setDefinition((prev) => ({
                        ...prev,
                        conditions: {
                          ...prev.conditions,
                          items: prev.conditions.items.filter((_, i) => i !== index),
                        },
                      }))
                    }
                  >
                    Remove
                  </button>
                </div>
              );
            })}
            <button
              type="button"
              className="rounded-md border px-3 py-1.5 text-sm"
              onClick={() => {
                const first = eventFields[0]?.name || "platform";
                setDefinition((prev) => ({
                  ...prev,
                  conditions: {
                    ...prev.conditions,
                    items: [
                      ...prev.conditions.items,
                      { id: `cond_${prev.conditions.items.length + 1}`, field: first, op: "equals", value: "" },
                    ],
                  },
                }));
              }}
            >
              Add condition
            </button>
          </section>

          <section className="space-y-3 rounded-lg border p-4">
            <div className="flex items-center justify-between">
              <h2 className="font-medium">Action steps (ordered)</h2>
              <button
                type="button"
                className="rounded-md border px-3 py-1.5 text-sm"
                onClick={() =>
                  setDefinition((prev) => ({
                    ...prev,
                    steps: [
                      ...prev.steps,
                      {
                        id: `step_${prev.steps.length + 1}`,
                        type: "action",
                        action_type: "create_notification",
                        config: { title: "Workflow step", category: "automation", severity: "info" },
                      },
                    ],
                  }))
                }
              >
                Add action
              </button>
            </div>
            {definition.steps.map((step, index) => (
              <div key={step.id} className="space-y-2 rounded-md border p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-xs text-muted-foreground">#{index + 1}</span>
                  <select
                    className="rounded-md border px-2 py-1.5 text-sm"
                    value={step.action_type}
                    onChange={(e) => updateStep(index, { action_type: e.target.value })}
                  >
                    {(catalog?.action_types ?? []).map((t) => (
                      <option key={t} value={t}>
                        {t}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    className="rounded-md border px-2 py-1 text-sm"
                    disabled={index === 0}
                    onClick={() =>
                      setDefinition((prev) => {
                        const steps = [...prev.steps];
                        [steps[index - 1], steps[index]] = [steps[index], steps[index - 1]];
                        return { ...prev, steps };
                      })
                    }
                  >
                    Up
                  </button>
                  <button
                    type="button"
                    className="rounded-md border px-2 py-1 text-sm"
                    disabled={index === definition.steps.length - 1}
                    onClick={() =>
                      setDefinition((prev) => {
                        const steps = [...prev.steps];
                        [steps[index + 1], steps[index]] = [steps[index], steps[index + 1]];
                        return { ...prev, steps };
                      })
                    }
                  >
                    Down
                  </button>
                  <button
                    type="button"
                    className="rounded-md border px-2 py-1 text-sm"
                    onClick={() =>
                      setDefinition((prev) => ({
                        ...prev,
                        steps: prev.steps.filter((_, i) => i !== index),
                      }))
                    }
                  >
                    Remove
                  </button>
                </div>
                {step.action_type === "create_notification" && (
                  <div className="grid gap-2 md:grid-cols-2">
                    <input
                      className="rounded-md border px-2 py-1.5 text-sm"
                      placeholder="Title"
                      value={String(step.config.title || "")}
                      onChange={(e) => updateStep(index, { config: { ...step.config, title: e.target.value } })}
                    />
                    <input
                      className="rounded-md border px-2 py-1.5 text-sm"
                      placeholder="Body"
                      value={String(step.config.body || "")}
                      onChange={(e) => updateStep(index, { config: { ...step.config, body: e.target.value } })}
                    />
                  </div>
                )}
                {step.action_type === "record_activity" && (
                  <input
                    className="w-full rounded-md border px-2 py-1.5 text-sm"
                    placeholder="Activity title"
                    value={String(step.config.title || "")}
                    onChange={(e) => updateStep(index, { config: { ...step.config, title: e.target.value } })}
                  />
                )}
                {step.action_type === "create_crm_lead" && (
                  <input
                    className="w-full rounded-md border px-2 py-1.5 text-sm"
                    placeholder="Name template"
                    value={String(step.config.name_template || "")}
                    onChange={(e) =>
                      updateStep(index, { config: { ...step.config, name_template: e.target.value } })
                    }
                  />
                )}
                {step.action_type === "update_customer_success_progress" && (
                  <input
                    className="w-full rounded-md border px-2 py-1.5 text-sm"
                    placeholder="Timeline title"
                    value={String(step.config.timeline_title || "")}
                    onChange={(e) =>
                      updateStep(index, { config: { ...step.config, timeline_title: e.target.value } })
                    }
                  />
                )}
              </div>
            ))}
          </section>

          <section className="space-y-3 rounded-lg border p-4">
            <h2 className="font-medium">Evaluate-only test</h2>
            <p className="text-xs text-muted-foreground">
              Synthetic payload must use catalog fields only. No production side effects.
            </p>
            <textarea
              className="w-full rounded-md border px-3 py-2 font-mono text-xs"
              rows={4}
              value={testPayloadText}
              onChange={(e) => setTestPayloadText(e.target.value)}
            />
            <button type="button" onClick={() => void handleTest()} className="rounded-md border px-3 py-1.5 text-sm">
              Run evaluate_only
            </button>
            {testResult && (
              <pre className="overflow-auto rounded-md bg-muted/50 p-3 text-xs">
                {JSON.stringify(testResult, null, 2)}
              </pre>
            )}
          </section>
        </div>

        <aside className="space-y-4">
          <section className="rounded-lg border p-4">
            <h2 className="font-medium">Validation</h2>
            {validation ? (
              <div className="mt-2 space-y-1 text-sm">
                <p className={cn(validation.valid ? "text-emerald-700" : "text-red-700")}>
                  {validation.valid ? "Valid" : "Invalid"}
                </p>
                {validation.errors.map((err) => (
                  <p key={`${err.code}-${err.path}`} className="text-xs text-red-700">
                    {err.path}: {err.message}
                  </p>
                ))}
              </div>
            ) : (
              <p className="mt-2 text-sm text-muted-foreground">Run validate before publish.</p>
            )}
          </section>

          <section className="rounded-lg border p-4">
            <h2 className="font-medium">Version history</h2>
            <ul className="mt-2 space-y-1 text-sm">
              {(workflow.recent_versions ?? []).map((v) => (
                <li key={v.id} className="flex justify-between gap-2">
                  <span>v{v.version_number}</span>
                  <span className="text-muted-foreground">{v.state}</span>
                </li>
              ))}
            </ul>
          </section>

          <section className="rounded-lg border p-4">
            <h2 className="font-medium">Executions</h2>
            <ul className="mt-2 space-y-1 text-sm">
              {(executionsQuery.data?.items ?? []).map((ex) => (
                <li key={ex.id} className="flex justify-between gap-2">
                  <span className="truncate">{ex.status}</span>
                  <span className="text-muted-foreground">{ex.trigger_event.split(".").pop()}</span>
                </li>
              ))}
              {(executionsQuery.data?.items.length ?? 0) === 0 && (
                <li className="text-muted-foreground">No executions yet</li>
              )}
            </ul>
          </section>
        </aside>
      </div>
    </PageShell>
  );
}
