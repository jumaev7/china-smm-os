"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname, useParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  assistantApi,
  AssistantChatMessage,
  AssistantPageContext,
  AssistantSuggestedPatch,
  clientsApi,
  contentApi,
  ContentItem,
} from "@/lib/api";
import { Bot, GripHorizontal, Send, X } from "lucide-react";
import toast from "react-hot-toast";
import { cn } from "@/lib/utils";
import {
  loadAssistantPreferences,
  saveAssistantPreferences,
} from "@/lib/assistantPreferences";

const POS_KEY = "smm_assistant_pos";
const DEFAULT_POS = { right: 24, bottom: 24 };

type ChatTurn = AssistantChatMessage;

function detectPageType(pathname: string): AssistantPageContext["page_type"] {
  if (/^\/content\/[^/]+/.test(pathname)) return "content_detail";
  if (pathname.startsWith("/content")) return "content";
  if (/^\/clients\/[^/]+/.test(pathname)) return "client_detail";
  if (pathname.startsWith("/clients")) return "clients";
  if (pathname.startsWith("/calendar")) return "calendar";
  return "other";
}

function buildSummary(content?: ContentItem | null, clientName?: string): string | undefined {
  const parts: string[] = [];
  if (clientName) parts.push(`Client: ${clientName}`);
  if (content) {
    parts.push(`Content ${content.status}`);
    if (content.media_file_type) parts.push(content.media_file_type);
    if (content.caption_short_ru) parts.push("has RU caption");
  }
  return parts.length ? parts.join(" · ") : undefined;
}

export function FloatingAssistant() {
  const pathname = usePathname();
  const params = useParams();
  const qc = useQueryClient();

  const contentId = typeof params?.id === "string" && pathname.startsWith("/content/")
    ? params.id
    : undefined;
  const clientIdFromRoute = typeof params?.id === "string" && pathname.startsWith("/clients/")
    ? params.id
    : undefined;

  const { data: contentItem } = useQuery({
    queryKey: ["content", contentId],
    queryFn: () => contentApi.get(contentId!).then((r) => r.data),
    enabled: !!contentId,
  });

  const resolvedClientId = clientIdFromRoute ?? contentItem?.client_id;

  const { data: client } = useQuery({
    queryKey: ["client", resolvedClientId],
    queryFn: () => clientsApi.get(resolvedClientId!).then((r) => r.data),
    enabled: !!resolvedClientId,
  });

  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [messages, setMessages] = useState<ChatTurn[]>([]);
  const [suggestedPatch, setSuggestedPatch] = useState<AssistantSuggestedPatch | null>(null);
  const [autoApply, setAutoApply] = useState(true);
  const [pos, setPos] = useState(DEFAULT_POS);
  const [dragging, setDragging] = useState(false);

  const dragState = useRef({
    pointerId: -1,
    startX: 0,
    startY: 0,
    originRight: DEFAULT_POS.right,
    originBottom: DEFAULT_POS.bottom,
    moved: false,
  });
  const listRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const posRef = useRef(pos);
  posRef.current = pos;

  useEffect(() => {
    try {
      const saved = localStorage.getItem(POS_KEY);
      if (saved) setPos(JSON.parse(saved));
    } catch {
      /* ignore */
    }
    setAutoApply(loadAssistantPreferences().autoApply);
  }, []);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, open]);

  const pageType = detectPageType(pathname);
  const pageContext: AssistantPageContext = {
    pathname,
    page_type: pageType,
    summary: buildSummary(contentItem, client?.company_name),
  };

  const onPointerDown = useCallback(
    (e: React.PointerEvent<HTMLButtonElement>) => {
      if (e.button !== 0) return;
      dragState.current = {
        pointerId: e.pointerId,
        startX: e.clientX,
        startY: e.clientY,
        originRight: pos.right,
        originBottom: pos.bottom,
        moved: false,
      };
      setDragging(true);
      buttonRef.current?.setPointerCapture(e.pointerId);
    },
    [pos.right, pos.bottom],
  );

  const onPointerMove = useCallback(
    (e: React.PointerEvent<HTMLButtonElement>) => {
      if (!dragging || dragState.current.pointerId !== e.pointerId) return;
      const dx = e.clientX - dragState.current.startX;
      const dy = e.clientY - dragState.current.startY;
      if (Math.abs(dx) > 4 || Math.abs(dy) > 4) dragState.current.moved = true;
      const maxRight = Math.max(8, window.innerWidth - 56);
      const maxBottom = Math.max(8, window.innerHeight - 56);
      setPos({
        right: Math.min(maxRight, Math.max(8, dragState.current.originRight - dx)),
        bottom: Math.min(maxBottom, Math.max(8, dragState.current.originBottom - dy)),
      });
    },
    [dragging],
  );

  const onPointerUp = useCallback(
    (e: React.PointerEvent<HTMLButtonElement>) => {
      if (dragState.current.pointerId !== e.pointerId) return;
      buttonRef.current?.releasePointerCapture(e.pointerId);
      setDragging(false);
      try {
        localStorage.setItem(POS_KEY, JSON.stringify(posRef.current));
      } catch {
        /* ignore */
      }
      if (!dragState.current.moved) setOpen((v) => !v);
    },
    [],
  );

  const toggleAutoApply = () => {
    const next = !autoApply;
    setAutoApply(next);
    saveAssistantPreferences({ autoApply: next });
  };

  const sendMessage = async () => {
    const text = input.trim();
    if (!text || sending) return;
    setInput("");
    setSuggestedPatch(null);
    const userTurn: ChatTurn = { role: "user", content: text };
    setMessages((prev) => [...prev, userTurn]);
    setSending(true);
    try {
      const res = await assistantApi.chat({
        message: text,
        page_context: pageContext,
        client_id: resolvedClientId,
        content_id: contentId,
        history: [...messages, userTurn].slice(-10),
        auto_apply: autoApply && !!contentId,
      });
      setMessages((prev) => [...prev, { role: "assistant", content: res.data.reply }]);
      if (res.data.applied && contentId) {
        await qc.invalidateQueries({ queryKey: ["content", contentId] });
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: "✅ Changes applied automatically" },
        ]);
      } else if (res.data.suggested_patch && contentId) {
        setSuggestedPatch(res.data.suggested_patch);
      }
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : "Assistant request failed");
    } finally {
      setSending(false);
    }
  };

  const applyPatch = async () => {
    if (!suggestedPatch || !contentId) return;
    if (!window.confirm("Apply assistant suggestions to this content item?")) return;
    try {
      await assistantApi.apply({ content_id: contentId, patch: suggestedPatch, auto: false });
      await qc.invalidateQueries({ queryKey: ["content", contentId] });
      setSuggestedPatch(null);
      toast.success("Changes applied");
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "✓ Changes applied to this content item." },
      ]);
    } catch {
      toast.error("Failed to apply changes");
    }
  };

  const quickPrompts = contentId
    ? ["Rewrite the RU caption", "Make hashtags better", "Suggest posting time"]
    : ["What can you help with?", "Tips for Uzbekistan Instagram"];

  return (
    <>
      {open && (
        <div
          data-keep-overlay
          className={cn(
            "fixed z-[100] flex flex-col bg-white border border-gray-200 shadow-2xl rounded-2xl overflow-hidden",
            "w-[min(100vw-1rem,22rem)] max-h-[min(70vh,32rem)]",
          )}
          style={{ right: pos.right, bottom: pos.bottom + 64 }}
        >
          <div className="flex items-center justify-between px-3 py-2.5 border-b border-gray-100 bg-brand-600 text-white gap-2">
            <div className="flex items-center gap-2 min-w-0">
              <Bot size={18} className="shrink-0" />
              <div className="min-w-0">
                <p className="text-sm font-semibold leading-tight">AI Assistant</p>
                <p className="text-[10px] text-brand-100 truncate">
                  {pageType === "content_detail" ? "Content detail" : pageType.replace("_", " ")}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              {contentId && (
                <button
                  type="button"
                  onClick={toggleAutoApply}
                  className={cn(
                    "text-[10px] px-2 py-0.5 rounded-full border transition-colors",
                    autoApply
                      ? "bg-white/20 border-white/40 text-white"
                      : "border-white/30 text-brand-100 hover:bg-white/10",
                  )}
                  title="When ON, caption and hashtag edits apply immediately"
                >
                  Auto Apply: {autoApply ? "ON" : "OFF"}
                </button>
              )}
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="p-1 rounded hover:bg-brand-500/50"
                aria-label="Close assistant"
              >
                <X size={16} />
              </button>
            </div>
          </div>

          <div ref={listRef} className="flex-1 overflow-y-auto p-3 space-y-2 text-sm min-h-[8rem]">
            {messages.length === 0 && (
              <p className="text-xs text-gray-500 leading-relaxed">
                Ask about captions, hashtags, translations, or this page&apos;s content.
                {contentId &&
                  (autoApply
                    ? " Edits apply automatically when Auto Apply is ON."
                    : " I can suggest edits you apply with one click.")}
              </p>
            )}
            {messages.map((m, i) => (
              <div
                key={i}
                className={cn(
                  "rounded-lg px-2.5 py-2 text-xs leading-relaxed whitespace-pre-wrap",
                  m.role === "user"
                    ? "bg-brand-50 text-brand-900 ml-6"
                    : "bg-gray-100 text-gray-800 mr-4",
                )}
              >
                {m.content}
              </div>
            ))}
            {sending && (
              <p className="text-xs text-gray-400 italic mr-4">Thinking…</p>
            )}
          </div>

          {suggestedPatch && contentId && !autoApply && (
            <div className="px-3 py-2 border-t border-amber-100 bg-amber-50">
              <p className="text-[10px] text-amber-800 mb-1.5 font-medium">Suggested changes</p>
              <button
                type="button"
                onClick={applyPatch}
                className="w-full text-xs font-medium py-1.5 rounded-lg bg-amber-600 text-white hover:bg-amber-700"
              >
                Apply changes
              </button>
            </div>
          )}

          <div className="px-2 py-2 border-t border-gray-100 flex flex-wrap gap-1">
            {quickPrompts.map((q) => (
              <button
                key={q}
                type="button"
                onClick={() => setInput(q)}
                className="text-[10px] px-2 py-0.5 rounded-full bg-gray-100 text-gray-600 hover:bg-gray-200"
              >
                {q}
              </button>
            ))}
          </div>

          <div className="flex gap-1.5 p-2 border-t border-gray-100">
            <input
              className="input text-xs py-1.5 flex-1 min-w-0"
              placeholder="Ask the assistant…"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  sendMessage();
                }
              }}
              disabled={sending}
            />
            <button
              type="button"
              onClick={sendMessage}
              disabled={sending || !input.trim()}
              className="shrink-0 p-2 rounded-lg bg-brand-600 text-white disabled:opacity-50 hover:bg-brand-700"
              aria-label="Send"
            >
              <Send size={14} />
            </button>
          </div>
        </div>
      )}

      <button
        ref={buttonRef}
        type="button"
        data-keep-overlay
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        className={cn(
          "fixed z-[101] w-14 h-14 rounded-full shadow-lg flex items-center justify-center",
          "bg-brand-600 text-white hover:bg-brand-700 touch-none select-none",
          dragging ? "cursor-grabbing scale-105" : "cursor-grab",
          open && "ring-2 ring-brand-300 ring-offset-2",
        )}
        style={{ right: pos.right, bottom: pos.bottom }}
        aria-label="Open AI assistant"
      >
        <Bot size={26} />
        <GripHorizontal
          size={12}
          className="absolute bottom-1.5 opacity-60"
        />
      </button>
    </>
  );
}
