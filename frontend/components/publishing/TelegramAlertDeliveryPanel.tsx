"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  TelegramAlertSettings,
  TelegramDeliveryItem,
  TelegramEnrollmentStatus,
  getApiErrorMessage,
  publishingApi,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { Bell, ExternalLink, Send, ShieldAlert, Smartphone } from "lucide-react";
import toast from "react-hot-toast";

const ALERT_TYPE_OPTIONS = [
  "operator_review",
  "exhausted",
  "terminal_failure",
  "stale_in_progress",
  "recovery",
  "repeated_failure",
] as const;

function formatWhen(value?: string | null) {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function secondsUntil(iso?: string | null) {
  if (!iso) return null;
  const ms = new Date(iso).getTime() - Date.now();
  return Math.max(0, Math.floor(ms / 1000));
}

export function TelegramAlertDeliveryPanel() {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({
    enabled: false,
    recipient_chat_id: "",
    recipient_label: "",
    allowed_chat_ids: "",
    severity_threshold: "warning",
    alert_types: [] as string[],
    quiet_hours_enabled: false,
    quiet_hours_start: "",
    quiet_hours_end: "",
    quiet_hours_timezone: "UTC",
    recovery_messages_enabled: false,
  });
  const [confirmTest, setConfirmTest] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const [confirmReplace, setConfirmReplace] = useState(false);
  const [deepLink, setDeepLink] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  const settingsQuery = useQuery({
    queryKey: ["publishing-telegram-alert-settings"],
    queryFn: () => publishingApi.getTelegramAlertSettings().then((r) => r.data),
  });

  const deliveriesQuery = useQuery({
    queryKey: ["publishing-telegram-alert-deliveries"],
    queryFn: () =>
      publishingApi.listTelegramAlertDeliveries({ page: 1, page_size: 10 }).then((r) => r.data),
    refetchInterval: 30_000,
  });

  const enrollmentQuery = useQuery({
    queryKey: ["publishing-telegram-enrollment"],
    queryFn: () => publishingApi.getTelegramEnrollment().then((r) => r.data),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (status === "pending_start" || status === "candidate_received") {
        const poll = Number(query.state.data?.poll_interval_seconds ?? 3);
        return Math.max(2000, Math.min(10_000, Math.round(poll * 1000)));
      }
      return false;
    },
  });

  const recipientsQuery = useQuery({
    queryKey: ["publishing-telegram-recipients"],
    queryFn: () =>
      publishingApi
        .listTelegramRecipients({ page: 1, page_size: 10, include_history: true })
        .then((r) => r.data),
  });

  useEffect(() => {
    const s = settingsQuery.data;
    if (!s) return;
    setForm({
      enabled: s.enabled,
      recipient_chat_id:
        s.recipient_chat_id != null ? String(s.recipient_chat_id) : "",
      recipient_label: s.recipient_label ?? "",
      allowed_chat_ids: (s.allowed_chat_ids ?? []).join(", "),
      severity_threshold: s.severity_threshold || "warning",
      alert_types: s.alert_types ?? [],
      quiet_hours_enabled: s.quiet_hours_enabled,
      quiet_hours_start: (s.quiet_hours_start || "").slice(0, 5),
      quiet_hours_end: (s.quiet_hours_end || "").slice(0, 5),
      quiet_hours_timezone: s.quiet_hours_timezone || "UTC",
      recovery_messages_enabled: s.recovery_messages_enabled,
    });
  }, [settingsQuery.data]);

  useEffect(() => {
    const id = window.setInterval(() => setTick((t) => t + 1), 1000);
    return () => window.clearInterval(id);
  }, []);

  const enrollment = enrollmentQuery.data;
  const remaining = useMemo(
    () => secondsUntil(enrollment?.expires_at),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [enrollment?.expires_at, tick],
  );

  const saveMutation = useMutation({
    mutationFn: () => {
      const allowlist = form.allowed_chat_ids
        .split(/[\s,]+/)
        .map((x) => x.trim())
        .filter(Boolean);
      const chatId = form.recipient_chat_id.trim();
      if (chatId && allowlist.length === 0) {
        allowlist.push(chatId);
      }
      return publishingApi
        .updateTelegramAlertSettings({
          enabled: form.enabled,
          recipient_chat_id: chatId || null,
          recipient_label: form.recipient_label.trim() || null,
          allowed_chat_ids: allowlist,
          severity_threshold: form.severity_threshold as "warning" | "critical" | "info",
          alert_types: form.alert_types.length
            ? (form.alert_types as TelegramAlertSettings["alert_types"] as never)
            : null,
          quiet_hours_enabled: form.quiet_hours_enabled,
          quiet_hours_start: form.quiet_hours_start || null,
          quiet_hours_end: form.quiet_hours_end || null,
          quiet_hours_timezone: form.quiet_hours_timezone || null,
          recovery_messages_enabled: form.recovery_messages_enabled,
        })
        .then((r) => r.data);
    },
    onSuccess: () => {
      toast.success("Telegram delivery settings saved");
      queryClient.invalidateQueries({ queryKey: ["publishing-telegram-alert-settings"] });
    },
    onError: (err) => toast.error(getApiErrorMessage(err)),
  });

  const testMutation = useMutation({
    mutationFn: () =>
      publishingApi.testTelegramAlertDelivery({ confirm: true }).then((r) => r.data),
    onSuccess: () => {
      toast.success("Test delivery enqueued (worker must be enabled to send)");
      setConfirmTest(false);
      queryClient.invalidateQueries({ queryKey: ["publishing-telegram-alert-deliveries"] });
    },
    onError: (err) => toast.error(getApiErrorMessage(err)),
  });

  const cancelMutation = useMutation({
    mutationFn: (id: string) => publishingApi.cancelTelegramAlertDelivery(id),
    onSuccess: () => {
      toast.success("Delivery cancelled");
      queryClient.invalidateQueries({ queryKey: ["publishing-telegram-alert-deliveries"] });
    },
    onError: (err) => toast.error(getApiErrorMessage(err)),
  });

  const retryMutation = useMutation({
    mutationFn: (id: string) => publishingApi.retryTelegramAlertDelivery(id),
    onSuccess: () => {
      toast.success("Delivery re-queued");
      queryClient.invalidateQueries({ queryKey: ["publishing-telegram-alert-deliveries"] });
    },
    onError: (err) => toast.error(getApiErrorMessage(err)),
  });

  const createEnrollmentMutation = useMutation({
    mutationFn: () => publishingApi.createTelegramEnrollment().then((r) => r.data),
    onSuccess: (data) => {
      setDeepLink(data.deep_link ?? null);
      setConfirmReplace(false);
      toast.success("Open Telegram and press Start on the bot");
      queryClient.invalidateQueries({ queryKey: ["publishing-telegram-enrollment"] });
    },
    onError: (err) => toast.error(getApiErrorMessage(err)),
  });

  const revokeEnrollmentMutation = useMutation({
    mutationFn: (id: string) => publishingApi.revokeTelegramEnrollment(id).then((r) => r.data),
    onSuccess: () => {
      setDeepLink(null);
      toast.success("Enrollment revoked");
      queryClient.invalidateQueries({ queryKey: ["publishing-telegram-enrollment"] });
    },
    onError: (err) => toast.error(getApiErrorMessage(err)),
  });

  const confirmEnrollmentMutation = useMutation({
    mutationFn: ({ id, replace }: { id: string; replace: boolean }) =>
      publishingApi
        .confirmTelegramEnrollment(id, { replace_existing: replace })
        .then((r) => r.data),
    onSuccess: () => {
      setDeepLink(null);
      setConfirmReplace(false);
      toast.success("Recipient confirmed. Delivery is still off until you enable it.");
      queryClient.invalidateQueries({ queryKey: ["publishing-telegram-enrollment"] });
      queryClient.invalidateQueries({ queryKey: ["publishing-telegram-alert-settings"] });
      queryClient.invalidateQueries({ queryKey: ["publishing-telegram-recipients"] });
    },
    onError: (err) => toast.error(getApiErrorMessage(err)),
  });

  const rejectEnrollmentMutation = useMutation({
    mutationFn: (id: string) => publishingApi.rejectTelegramEnrollment(id).then((r) => r.data),
    onSuccess: () => {
      setDeepLink(null);
      toast.success("Candidate rejected");
      queryClient.invalidateQueries({ queryKey: ["publishing-telegram-enrollment"] });
    },
    onError: (err) => toast.error(getApiErrorMessage(err)),
  });

  const removeRecipientMutation = useMutation({
    mutationFn: () => publishingApi.removeTelegramRecipient().then((r) => r.data),
    onSuccess: () => {
      setConfirmRemove(false);
      toast.success("Recipient removed");
      queryClient.invalidateQueries({ queryKey: ["publishing-telegram-recipients"] });
      queryClient.invalidateQueries({ queryKey: ["publishing-telegram-alert-settings"] });
      queryClient.invalidateQueries({ queryKey: ["publishing-telegram-enrollment"] });
    },
    onError: (err) => toast.error(getApiErrorMessage(err)),
  });

  const settings = settingsQuery.data;
  const deliveries = deliveriesQuery.data?.items ?? [];
  const recipients = recipientsQuery.data?.items ?? [];
  const activeLink = deepLink || enrollment?.deep_link || null;
  const enrollmentEnabled = Boolean(enrollment?.enrollment_enabled);
  const connected =
    Boolean(settings?.recipient_chat_id_masked) ||
    recipients.some((r) => r.status === "confirmed");

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4 sm:p-5 space-y-4">
      <div className="flex items-start gap-3">
        <Bell className="text-slate-600 mt-0.5 shrink-0" size={18} />
        <div className="space-y-1 min-w-0">
          <h2 className="text-base font-semibold text-gray-900">
            Telegram delivery (outbound)
          </h2>
          <p className="text-sm text-gray-500">
            Separate from in-app alerts. Sends only to an explicit numeric chat ID on the
            tenant allowlist — never to client intake groups or publish channels. Requires
            the global kill switch and tenant enablement.
          </p>
        </div>
      </div>

      <div className="flex flex-wrap gap-2 text-xs">
        <StatusPill
          ok={Boolean(settings?.global_telegram_enabled)}
          label={
            settings?.global_telegram_enabled
              ? "Global Telegram: on"
              : "Global Telegram: off (master kill switch)"
          }
        />
        <StatusPill
          ok={Boolean(settings?.delivery_effective)}
          label={
            settings?.delivery_effective
              ? "Effective delivery: ready"
              : "Effective delivery: blocked"
          }
        />
        <StatusPill
          ok={connected}
          label={`Recipient: ${settings?.recipient_chat_id_masked || "not set"}`}
        />
        <StatusPill
          ok={enrollmentEnabled}
          label={enrollmentEnabled ? "Self-enrollment: available" : "Self-enrollment: disabled"}
        />
      </div>

      {!settings?.global_telegram_enabled ? (
        <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          <ShieldAlert size={16} className="mt-0.5 shrink-0" />
          <span>
            Outbound Telegram remains disabled by the global{" "}
            <code className="text-xs">PUBLISH_ALERT_TELEGRAM_ENABLED</code> flag. Settings
            can be prepared, but nothing will enqueue or send until that flag is enabled.
          </span>
        </div>
      ) : null}

      <EnrollmentBlock
        enrollment={enrollment}
        enrollmentEnabled={enrollmentEnabled}
        connected={connected}
        activeLink={activeLink}
        remaining={remaining}
        confirmReplace={confirmReplace}
        onConfirmReplace={setConfirmReplace}
        onConnect={() => createEnrollmentMutation.mutate()}
        onOpenBot={() => {
          if (activeLink) window.open(activeLink, "_blank", "noopener,noreferrer");
        }}
        onRevoke={() => enrollment?.id && revokeEnrollmentMutation.mutate(enrollment.id)}
        onConfirm={(replace) =>
          enrollment?.id &&
          confirmEnrollmentMutation.mutate({ id: enrollment.id, replace })
        }
        onReject={() => enrollment?.id && rejectEnrollmentMutation.mutate(enrollment.id)}
        busy={
          createEnrollmentMutation.isPending ||
          revokeEnrollmentMutation.isPending ||
          confirmEnrollmentMutation.isPending ||
          rejectEnrollmentMutation.isPending
        }
      />

      {connected ? (
        <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-3 space-y-2">
          <div className="text-sm font-medium text-gray-900">Connected recipient</div>
          <p className="text-sm text-gray-600">
            {settings?.recipient_label || "Telegram operator"} · masked ID{" "}
            {settings?.recipient_chat_id_masked || "—"}
          </p>
          <p className="text-xs text-gray-500">
            Connecting does not enable notifications. Use the enable checkbox below as a
            separate action after global delivery is allowed.
          </p>
          {!confirmRemove ? (
            <button
              type="button"
              onClick={() => setConfirmRemove(true)}
              className="rounded-lg border border-red-200 bg-white px-3 py-1.5 text-sm text-red-700"
            >
              Remove / change recipient…
            </button>
          ) : (
            <div className="flex flex-wrap gap-2 items-center">
              <span className="text-xs text-red-800">
                Remove recipient and clear allowlist? Tenant delivery will be turned off.
              </span>
              <button
                type="button"
                disabled={removeRecipientMutation.isPending}
                onClick={() => removeRecipientMutation.mutate()}
                className="rounded-lg bg-red-600 px-3 py-1.5 text-sm text-white disabled:opacity-50"
              >
                Confirm remove
              </button>
              <button
                type="button"
                onClick={() => setConfirmRemove(false)}
                className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm"
              >
                Cancel
              </button>
            </div>
          )}
        </div>
      ) : null}

      {recipients.length > 0 ? (
        <div className="space-y-2">
          <h3 className="text-sm font-medium text-gray-800">Recipient history</h3>
          <ul className="space-y-1.5 text-sm">
            {recipients.map((r) => (
              <li key={r.id} className="text-gray-600">
                <span className="font-medium text-gray-800">{r.status}</span>
                {" · "}
                {r.telegram_display_name || r.telegram_username || "operator"}
                {" · "}
                {r.telegram_chat_id_masked || "—"}
                {" · "}
                {formatWhen(r.confirmed_at || r.created_at)}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <label className="text-xs text-gray-500 space-y-1 sm:col-span-2">
          <span>Numeric recipient chat ID (manual fallback)</span>
          <input
            className="w-full rounded-lg border border-gray-200 px-2.5 py-2 text-sm"
            value={form.recipient_chat_id}
            onChange={(e) => setForm((f) => ({ ...f, recipient_chat_id: e.target.value }))}
            placeholder="Prefer Connect Telegram above — not @username"
            inputMode="numeric"
          />
        </label>
        <label className="text-xs text-gray-500 space-y-1">
          <span>Label (metadata only)</span>
          <input
            className="w-full rounded-lg border border-gray-200 px-2.5 py-2 text-sm"
            value={form.recipient_label}
            onChange={(e) => setForm((f) => ({ ...f, recipient_label: e.target.value }))}
            placeholder="ops DM"
          />
        </label>
        <label className="text-xs text-gray-500 space-y-1">
          <span>Allowlist (comma-separated numeric IDs)</span>
          <input
            className="w-full rounded-lg border border-gray-200 px-2.5 py-2 text-sm"
            value={form.allowed_chat_ids}
            onChange={(e) => setForm((f) => ({ ...f, allowed_chat_ids: e.target.value }))}
            placeholder="Must include the recipient"
          />
        </label>
        <label className="text-xs text-gray-500 space-y-1">
          <span>Severity threshold</span>
          <select
            className="w-full rounded-lg border border-gray-200 px-2.5 py-2 text-sm"
            value={form.severity_threshold}
            onChange={(e) => setForm((f) => ({ ...f, severity_threshold: e.target.value }))}
          >
            <option value="info">Info and above</option>
            <option value="warning">Warning and above</option>
            <option value="critical">Critical only</option>
          </select>
        </label>
        <label className="inline-flex items-center gap-2 text-sm text-gray-700 mt-5">
          <input
            type="checkbox"
            checked={form.enabled}
            onChange={(e) => setForm((f) => ({ ...f, enabled: e.target.checked }))}
          />
          Enable tenant Telegram delivery
        </label>
        <label className="inline-flex items-center gap-2 text-sm text-gray-700 mt-5">
          <input
            type="checkbox"
            checked={form.recovery_messages_enabled}
            onChange={(e) =>
              setForm((f) => ({ ...f, recovery_messages_enabled: e.target.checked }))
            }
          />
          Send recovery messages (once per recovery alert)
        </label>
      </div>

      <div className="space-y-2">
        <div className="text-xs text-gray-500">Alert types (empty = all)</div>
        <div className="flex flex-wrap gap-2">
          {ALERT_TYPE_OPTIONS.map((t) => {
            const on = form.alert_types.includes(t);
            return (
              <button
                key={t}
                type="button"
                onClick={() =>
                  setForm((f) => ({
                    ...f,
                    alert_types: on
                      ? f.alert_types.filter((x) => x !== t)
                      : [...f.alert_types, t],
                  }))
                }
                className={cn(
                  "rounded-full border px-2.5 py-1 text-xs",
                  on
                    ? "border-slate-700 bg-slate-800 text-white"
                    : "border-gray-200 bg-white text-gray-600",
                )}
              >
                {t}
              </button>
            );
          })}
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-4 gap-3">
        <label className="inline-flex items-center gap-2 text-sm text-gray-700 sm:col-span-1">
          <input
            type="checkbox"
            checked={form.quiet_hours_enabled}
            onChange={(e) => setForm((f) => ({ ...f, quiet_hours_enabled: e.target.checked }))}
          />
          Quiet hours
        </label>
        <label className="text-xs text-gray-500 space-y-1">
          <span>Start</span>
          <input
            type="time"
            className="w-full rounded-lg border border-gray-200 px-2.5 py-2 text-sm"
            value={form.quiet_hours_start}
            onChange={(e) => setForm((f) => ({ ...f, quiet_hours_start: e.target.value }))}
          />
        </label>
        <label className="text-xs text-gray-500 space-y-1">
          <span>End</span>
          <input
            type="time"
            className="w-full rounded-lg border border-gray-200 px-2.5 py-2 text-sm"
            value={form.quiet_hours_end}
            onChange={(e) => setForm((f) => ({ ...f, quiet_hours_end: e.target.value }))}
          />
        </label>
        <label className="text-xs text-gray-500 space-y-1">
          <span>Timezone</span>
          <input
            className="w-full rounded-lg border border-gray-200 px-2.5 py-2 text-sm"
            value={form.quiet_hours_timezone}
            onChange={(e) => setForm((f) => ({ ...f, quiet_hours_timezone: e.target.value }))}
            placeholder="UTC"
          />
        </label>
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={saveMutation.isPending}
          onClick={() => saveMutation.mutate()}
          className="rounded-lg bg-slate-900 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          Save Telegram settings
        </button>
        {!confirmTest ? (
          <button
            type="button"
            onClick={() => setConfirmTest(true)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700"
          >
            <Send size={14} />
            Send test notification…
          </button>
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-amber-800">
              Confirm test? Refused while global delivery is off.
            </span>
            <button
              type="button"
              disabled={testMutation.isPending}
              onClick={() => testMutation.mutate()}
              className="rounded-lg bg-amber-600 px-3 py-2 text-sm text-white disabled:opacity-50"
            >
              Confirm send test
            </button>
            <button
              type="button"
              onClick={() => setConfirmTest(false)}
              className="rounded-lg border border-gray-200 px-3 py-2 text-sm"
            >
              Cancel
            </button>
          </div>
        )}
      </div>

      <div className="space-y-2 border-t border-gray-100 pt-4">
        <h3 className="text-sm font-medium text-gray-800">Recent Telegram delivery attempts</h3>
        {deliveriesQuery.isLoading ? (
          <p className="text-sm text-gray-500">Loading deliveries…</p>
        ) : null}
        {!deliveriesQuery.isLoading && deliveries.length === 0 ? (
          <p className="text-sm text-gray-500">
            No outbound Telegram deliveries yet. In-app alerts can exist without any Telegram
            send.
          </p>
        ) : null}
        <ul className="space-y-2">
          {deliveries.map((d) => (
            <DeliveryRow
              key={d.id}
              item={d}
              onCancel={() => cancelMutation.mutate(d.id)}
              onRetry={() => retryMutation.mutate(d.id)}
              busy={cancelMutation.isPending || retryMutation.isPending}
            />
          ))}
        </ul>
      </div>
    </section>
  );
}

function EnrollmentBlock({
  enrollment,
  enrollmentEnabled,
  connected,
  activeLink,
  remaining,
  confirmReplace,
  onConfirmReplace,
  onConnect,
  onOpenBot,
  onRevoke,
  onConfirm,
  onReject,
  busy,
}: {
  enrollment?: TelegramEnrollmentStatus;
  enrollmentEnabled: boolean;
  connected: boolean;
  activeLink: string | null;
  remaining: number | null;
  confirmReplace: boolean;
  onConfirmReplace: (v: boolean) => void;
  onConnect: () => void;
  onOpenBot: () => void;
  onRevoke: () => void;
  onConfirm: (replace: boolean) => void;
  onReject: () => void;
  busy: boolean;
}) {
  const status = enrollment?.status;
  const note =
    enrollment?.delivery_still_disabled_note ||
    "Connecting Telegram does not enable notifications.";

  return (
    <div className="rounded-lg border border-slate-200 px-3 py-3 space-y-3">
      <div className="flex items-start gap-2">
        <Smartphone size={16} className="mt-0.5 text-slate-600 shrink-0" />
        <div className="min-w-0 space-y-1">
          <h3 className="text-sm font-medium text-gray-900">Connect Telegram</h3>
          <p className="text-xs text-gray-500">{note}</p>
          <p className="text-xs text-gray-500">
            Only private Telegram accounts can enroll. Groups, channels, and bots are rejected.
            Max confirmed recipients: {enrollment?.max_confirmed_recipients ?? 1}.
          </p>
        </div>
      </div>

      {!enrollmentEnabled ? (
        <p className="text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
          Self-enrollment is disabled by{" "}
          <code className="text-xs">PUBLISH_ALERT_TELEGRAM_ENROLLMENT_ENABLED</code>. Manual
          numeric chat ID entry remains available below.
        </p>
      ) : null}

      {status === "pending_start" ? (
        <div className="space-y-2 text-sm text-gray-700">
          <p>
            Waiting for you to open the bot and press <strong>Start</strong>
            {remaining != null ? ` · expires in ${remaining}s` : ""}.
          </p>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={!activeLink || busy}
              onClick={onOpenBot}
              className="inline-flex items-center gap-1.5 rounded-lg bg-sky-700 px-3 py-2 text-sm text-white disabled:opacity-50"
            >
              <ExternalLink size={14} />
              Open Telegram bot
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={onRevoke}
              className="rounded-lg border border-gray-200 px-3 py-2 text-sm"
            >
              Cancel enrollment
            </button>
          </div>
        </div>
      ) : null}

      {status === "candidate_received" ? (
        <div className="space-y-2 text-sm text-gray-700">
          <p>
            Candidate detected:{" "}
            <strong>{enrollment?.telegram_display_name || "Telegram user"}</strong>
            {enrollment?.telegram_username ? ` (@${enrollment.telegram_username})` : ""}
            {" · "}
            masked ID {enrollment?.telegram_chat_id_masked || "—"}
          </p>
          <p className="text-xs text-gray-500">
            Confirm only if this is the intended personal operator account. Confirmation does
            not enable delivery.
          </p>
          <div className="flex flex-wrap gap-2">
            {!confirmReplace && connected ? (
              <button
                type="button"
                disabled={busy}
                onClick={() => onConfirmReplace(true)}
                className="rounded-lg bg-slate-900 px-3 py-2 text-sm text-white disabled:opacity-50"
              >
                Replace existing & confirm…
              </button>
            ) : (
              <button
                type="button"
                disabled={busy}
                onClick={() => onConfirm(Boolean(connected))}
                className="rounded-lg bg-slate-900 px-3 py-2 text-sm text-white disabled:opacity-50"
              >
                Confirm connection
              </button>
            )}
            <button
              type="button"
              disabled={busy}
              onClick={onReject}
              className="rounded-lg border border-red-200 px-3 py-2 text-sm text-red-700 disabled:opacity-50"
            >
              Reject
            </button>
          </div>
        </div>
      ) : null}

      {status === "expired" || status === "revoked" || status === "rejected" ? (
        <p className="text-sm text-gray-600">
          Last enrollment: {status}
          {enrollment?.rejection_reason_code
            ? ` (${enrollment.rejection_reason_code})`
            : ""}
          . Start a new connection when ready.
        </p>
      ) : null}

      {enrollmentEnabled && status !== "pending_start" && status !== "candidate_received" ? (
        <button
          type="button"
          disabled={busy}
          onClick={onConnect}
          className="rounded-lg bg-slate-900 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {connected ? "Connect a different Telegram account" : "Connect Telegram"}
        </button>
      ) : null}
    </div>
  );
}

function StatusPill({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span
      className={cn(
        "inline-flex rounded-full border px-2.5 py-1",
        ok
          ? "border-emerald-200 bg-emerald-50 text-emerald-800"
          : "border-slate-200 bg-slate-50 text-slate-700",
      )}
    >
      {label}
    </span>
  );
}

function DeliveryRow({
  item,
  onCancel,
  onRetry,
  busy,
}: {
  item: TelegramDeliveryItem;
  onCancel: () => void;
  onRetry: () => void;
  busy: boolean;
}) {
  const canCancel = ["pending", "retrying", "sending"].includes(item.status);
  const canRetry = ["failed", "exhausted", "cancelled"].includes(item.status);
  return (
    <li className="rounded-lg border border-gray-200 px-3 py-2 text-sm space-y-1">
      <div className="flex flex-wrap items-center gap-2 justify-between">
        <div className="font-medium text-gray-800">
          {item.status} · {item.message_kind} · attempt {item.attempt_number}/{item.max_attempts}
        </div>
        <div className="flex gap-2">
          {canCancel ? (
            <button
              type="button"
              disabled={busy}
              onClick={onCancel}
              className="text-xs text-red-700 hover:underline disabled:opacity-50"
            >
              Cancel
            </button>
          ) : null}
          {canRetry ? (
            <button
              type="button"
              disabled={busy}
              onClick={onRetry}
              className="text-xs text-slate-700 hover:underline disabled:opacity-50"
            >
              Retry
            </button>
          ) : null}
        </div>
      </div>
      <div className="text-xs text-gray-500">
        Chat {item.recipient_chat_id_masked || "—"} · {formatWhen(item.created_at)}
        {item.failure_code ? ` · ${item.failure_code}` : ""}
        {item.failure_message ? ` — ${item.failure_message}` : ""}
      </div>
    </li>
  );
}
