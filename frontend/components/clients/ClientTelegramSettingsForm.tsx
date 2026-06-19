"use client";
import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { clientsApi, Client } from "@/lib/api";
import { MessageCircle, Send } from "lucide-react";
import toast from "react-hot-toast";

type PublishType = "channel" | "supergroup" | "";

interface Props {
  client: Client;
  onSaved: () => void;
}

function formFromClient(client: Client) {
  return {
    telegram_group_id: client.telegram_group_id ?? "",
    telegram_group_title: client.telegram_group_title ?? "",
    telegram_workflow_mode: client.telegram_workflow_mode ?? "auto_create_from_media",
    operator_auto_draft_enabled: Boolean(client.operator_auto_draft_enabled),
    telegram_publish_chat_id: client.telegram_publish_chat_id ?? "",
    telegram_publish_title: client.telegram_publish_title ?? "",
    telegram_publish_type: (client.telegram_publish_type ?? "") as PublishType,
    use_publish_destination: Boolean(client.telegram_publish_chat_id),
  };
}

export function ClientTelegramSettingsForm({ client, onSaved }: Props) {
  const [form, setForm] = useState(() => formFromClient(client));

  useEffect(() => {
    setForm(formFromClient(client));
  }, [client]);

  const mutation = useMutation({
    mutationFn: () =>
      clientsApi.update(client.id, {
        telegram_group_id: form.telegram_group_id.trim() || null,
        telegram_group_title: form.telegram_group_title.trim() || null,
        telegram_workflow_mode: form.telegram_workflow_mode,
        operator_auto_draft_enabled: form.operator_auto_draft_enabled,
        telegram_publish_chat_id: form.use_publish_destination
          ? form.telegram_publish_chat_id.trim() || null
          : null,
        telegram_publish_title: form.use_publish_destination
          ? form.telegram_publish_title.trim() || null
          : null,
        telegram_publish_type: form.use_publish_destination && form.telegram_publish_type
          ? form.telegram_publish_type
          : null,
      }),
    onSuccess: () => {
      toast.success("Telegram settings saved");
      onSaved();
    },
    onError: (err: { response?: { data?: { detail?: string | { msg?: string }[] } } }) => {
      const detail = err.response?.data?.detail;
      const msg =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((d) => (typeof d === "object" && d && "msg" in d ? d.msg : String(d))).join(", ")
            : "Failed to save Telegram settings";
      toast.error(msg);
    },
  });

  const set =
    (key: keyof typeof form) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
      const value =
        e.target.type === "checkbox"
          ? (e.target as HTMLInputElement).checked
          : e.target.value;
      setForm((prev) => ({ ...prev, [key]: value }));
    };

  return (
    <div className="card p-5 mb-5">
      <h2 className="text-sm font-semibold text-gray-800 mb-4 flex items-center gap-2">
        <MessageCircle size={16} className="text-violet-600" />
        Telegram settings
      </h2>

      <div className="grid gap-6 md:grid-cols-2">
        {/* Intake group */}
        <div className="space-y-3 rounded-lg border border-violet-100 bg-violet-50/40 p-4">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-violet-800">
            Intake group
          </h3>
          <p className="text-xs text-violet-700/90">
            Linked Telegram group where the client and admin send materials (buffer workflow).
          </p>
          <div>
            <label className="label">Group title</label>
            <input
              className="input"
              value={form.telegram_group_title}
              onChange={set("telegram_group_title")}
              placeholder="e.g. Client materials group"
            />
          </div>
          <div>
            <label className="label">Group chat ID</label>
            <input
              className="input font-mono text-sm"
              value={form.telegram_group_id}
              onChange={set("telegram_group_id")}
              placeholder="-1001234567890"
            />
          </div>
          <div>
            <label className="label">Workflow</label>
            <select
              className="input"
              value={form.telegram_workflow_mode}
              onChange={set("telegram_workflow_mode")}
            >
              <option value="admin_controlled_buffer">Buffer (admin-controlled)</option>
              <option value="auto_create_from_media">Auto create from media</option>
            </select>
          </div>
          <div className="rounded-lg border border-emerald-100 bg-emerald-50/50 p-3 space-y-2">
            <label className="flex items-start gap-2 text-sm text-gray-800 cursor-pointer">
              <input
                type="checkbox"
                className="mt-1 rounded border-gray-300"
                checked={form.operator_auto_draft_enabled}
                onChange={set("operator_auto_draft_enabled")}
              />
              <span>
                <span className="font-medium">AI Auto Draft from Telegram Inbox</span>
                <p className="text-xs text-gray-600 mt-1 font-normal">
                  When enabled, AI will create draft posts from new Telegram materials automatically.
                  Nothing is published without admin approval.
                </p>
              </span>
            </label>
          </div>
        </div>

        {/* Publish destination */}
        <div className="space-y-3 rounded-lg border border-sky-100 bg-sky-50/40 p-4">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-sky-800 flex items-center gap-1.5">
            <Send size={13} />
            Telegram publish destination
          </h3>
          <p className="text-xs text-sky-800/90">
            Channel or supergroup where posts are published when no explicit publishing account is
            selected.
          </p>
          <label className="flex items-start gap-2 text-sm text-gray-700 cursor-pointer">
            <input
              type="checkbox"
              className="mt-1 rounded border-gray-300"
              checked={form.use_publish_destination}
              onChange={set("use_publish_destination")}
            />
            <span>Use as default Telegram publish destination</span>
          </label>
          <div className={form.use_publish_destination ? "space-y-3" : "space-y-3 opacity-50 pointer-events-none"}>
            <div>
              <label className="label">Chat ID / channel username</label>
              <input
                className="input font-mono text-sm"
                value={form.telegram_publish_chat_id}
                onChange={set("telegram_publish_chat_id")}
                placeholder="@my_channel"
              />
              <p className="text-[11px] text-gray-500 mt-1">
                Examples: <span className="font-mono">@my_channel</span>,{" "}
                <span className="font-mono">-1003980920346</span>
              </p>
            </div>
            <div>
              <label className="label">Title</label>
              <input
                className="input"
                value={form.telegram_publish_title}
                onChange={set("telegram_publish_title")}
                placeholder="e.g. Brand official channel"
              />
            </div>
            <div>
              <label className="label">Type</label>
              <select
                className="input"
                value={form.telegram_publish_type}
                onChange={set("telegram_publish_type")}
              >
                <option value="">— Select —</option>
                <option value="channel">channel</option>
                <option value="supergroup">supergroup</option>
              </select>
            </div>
          </div>
        </div>
      </div>

      <div className="mt-4 flex justify-end">
        <button
          type="button"
          className="btn-primary text-xs"
          disabled={mutation.isPending}
          onClick={() => mutation.mutate()}
        >
          {mutation.isPending ? "Saving…" : "Save Telegram settings"}
        </button>
      </div>
    </div>
  );
}
