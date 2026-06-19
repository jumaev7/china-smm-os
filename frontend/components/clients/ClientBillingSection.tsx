"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import { CreditCard, Save } from "lucide-react";
import toast from "react-hot-toast";
import { billingApi, BillingStatus } from "@/lib/api";
import { BILLING_STATUS_CONFIG, cn } from "@/lib/utils";

interface Props {
  clientId: string;
  onSaved?: () => void;
}

function toDateInput(iso: string | null | undefined): string {
  if (!iso) return "";
  try {
    return format(parseISO(iso), "yyyy-MM-dd");
  } catch {
    return "";
  }
}

function dateInputToIso(value: string): string | null {
  if (!value) return null;
  return `${value}T00:00:00.000Z`;
}

function endDateInputToIso(value: string): string | null {
  if (!value) return null;
  return `${value}T23:59:59.000Z`;
}

export function ClientBillingSection({ clientId, onSaved }: Props) {
  const { data: billing, isLoading, refetch } = useQuery({
    queryKey: ["client-billing", clientId],
    queryFn: () => billingApi.getClientBilling(clientId).then((r) => r.data),
  });

  const [form, setForm] = useState({
    plan_name: "",
    monthly_fee: "",
    monthly_post_limit: "",
    billing_status: "active" as BillingStatus,
    billing_cycle_start: "",
    billing_cycle_end: "",
  });

  useEffect(() => {
    if (!billing) return;
    setForm({
      plan_name: billing.plan_name ?? "",
      monthly_fee: billing.monthly_fee != null ? String(billing.monthly_fee) : "",
      monthly_post_limit:
        billing.monthly_post_limit != null ? String(billing.monthly_post_limit) : "",
      billing_status: billing.billing_status,
      billing_cycle_start: toDateInput(billing.billing_cycle_start),
      billing_cycle_end: toDateInput(billing.billing_cycle_end),
    });
  }, [billing]);

  const saveMutation = useMutation({
    mutationFn: () =>
      billingApi.updateClientBilling(clientId, {
        plan_name: form.plan_name.trim() || null,
        monthly_fee: form.monthly_fee ? parseFloat(form.monthly_fee) : null,
        monthly_post_limit: form.monthly_post_limit
          ? parseInt(form.monthly_post_limit, 10)
          : null,
        billing_status: form.billing_status,
        billing_cycle_start: dateInputToIso(form.billing_cycle_start),
        billing_cycle_end: endDateInputToIso(form.billing_cycle_end),
      }),
    onSuccess: () => {
      toast.success("Billing saved");
      refetch();
      onSaved?.();
    },
    onError: () => toast.error("Failed to save billing"),
  });

  if (isLoading || !billing) {
    return (
      <div className="card p-5 mb-5 text-sm text-gray-400">Loading billing…</div>
    );
  }

  const usage = billing.usage;
  const limit = billing.monthly_post_limit;
  const published = usage.posts_published_this_cycle;
  const usagePct =
    limit && limit > 0 ? Math.min(100, Math.round((published / limit) * 100)) : null;

  const statusCfg = BILLING_STATUS_CONFIG[billing.billing_status];

  return (
    <div className="card p-5 mb-5">
      <h2 className="text-sm font-semibold text-gray-800 mb-4 flex items-center gap-2">
        <CreditCard size={16} className="text-amber-600" />
        Billing
        <span className={cn("text-[10px] px-2 py-0.5 rounded-full border font-medium", statusCfg.color)}>
          {statusCfg.label}
        </span>
        {billing.near_limit && (
          <span className="text-[10px] px-2 py-0.5 rounded-full border font-medium bg-orange-100 text-orange-800 border-orange-200">
            Near limit
          </span>
        )}
      </h2>

      <div className="grid gap-4 md:grid-cols-2 mb-5">
        <div className="space-y-3">
          <div>
            <label className="label">Plan</label>
            <input
              className="input"
              value={form.plan_name}
              onChange={(e) => setForm((f) => ({ ...f, plan_name: e.target.value }))}
              placeholder="e.g. Standard 20 posts"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label">Monthly fee (USD)</label>
              <input
                className="input"
                type="number"
                min={0}
                step={0.01}
                value={form.monthly_fee}
                onChange={(e) => setForm((f) => ({ ...f, monthly_fee: e.target.value }))}
                placeholder="0.00"
              />
            </div>
            <div>
              <label className="label">Post limit / cycle</label>
              <input
                className="input"
                type="number"
                min={0}
                value={form.monthly_post_limit}
                onChange={(e) => setForm((f) => ({ ...f, monthly_post_limit: e.target.value }))}
                placeholder="Unlimited"
              />
            </div>
          </div>
          <div>
            <label className="label">Billing status</label>
            <select
              className="input"
              value={form.billing_status}
              onChange={(e) =>
                setForm((f) => ({ ...f, billing_status: e.target.value as BillingStatus }))
              }
            >
              <option value="active">Active</option>
              <option value="unpaid">Unpaid</option>
              <option value="paused">Paused</option>
            </select>
          </div>
        </div>

        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label">Cycle start</label>
              <input
                className="input"
                type="date"
                value={form.billing_cycle_start}
                onChange={(e) => setForm((f) => ({ ...f, billing_cycle_start: e.target.value }))}
              />
            </div>
            <div>
              <label className="label">Cycle end</label>
              <input
                className="input"
                type="date"
                value={form.billing_cycle_end}
                onChange={(e) => setForm((f) => ({ ...f, billing_cycle_end: e.target.value }))}
              />
            </div>
          </div>

          <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 space-y-2">
            <p className="text-xs font-medium text-gray-700">Usage this cycle</p>
            <div className="grid grid-cols-3 gap-2 text-center text-xs">
              <div>
                <p className="text-lg font-semibold text-gray-900">{usage.posts_created_this_cycle}</p>
                <p className="text-gray-500">Created</p>
              </div>
              <div>
                <p className="text-lg font-semibold text-gray-900">{published}</p>
                <p className="text-gray-500">Published</p>
              </div>
              <div>
                <p className="text-lg font-semibold text-gray-900">
                  {usage.posts_remaining != null ? usage.posts_remaining : "∞"}
                </p>
                <p className="text-gray-500">Remaining</p>
              </div>
            </div>
            {usagePct != null && (
              <div>
                <div className="flex justify-between text-[11px] text-gray-500 mb-1">
                  <span>Published vs limit</span>
                  <span>{usagePct}%</span>
                </div>
                <div className="h-2 rounded-full bg-gray-200 overflow-hidden">
                  <div
                    className={cn(
                      "h-full rounded-full transition-all",
                      billing.near_limit ? "bg-orange-500" : "bg-brand-600",
                    )}
                    style={{ width: `${usagePct}%` }}
                  />
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="flex justify-end">
        <button
          type="button"
          className="btn-primary text-xs"
          disabled={saveMutation.isPending}
          onClick={() => saveMutation.mutate()}
        >
          <Save size={12} />
          {saveMutation.isPending ? "Saving…" : "Save billing"}
        </button>
      </div>
    </div>
  );
}
