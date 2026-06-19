"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation } from "@tanstack/react-query";
import { Bot, Send } from "lucide-react";
import { tenantOnboardingApi } from "@/lib/api";
import { cn } from "@/lib/utils";

type ChatMessage = { role: "user" | "assistant"; text: string; route?: string | null };

export function OnboardingAssistant({ contextStep }: { contextStep?: string }) {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      role: "assistant",
      text: "Hi! I can guide you through setup. Ask: What should I do next?",
    },
  ]);

  const chat = useMutation({
    mutationFn: (message: string) =>
      tenantOnboardingApi.assistantChat(message, contextStep).then((r) => r.data),
    onSuccess: (data) => {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", text: data.reply, route: data.suggested_route },
      ]);
    },
  });

  function send() {
    const text = input.trim();
    if (!text || chat.isPending) return;
    setMessages((prev) => [...prev, { role: "user", text }]);
    setInput("");
    chat.mutate(text);
  }

  return (
    <div className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-100 bg-slate-50">
        <Bot size={18} className="text-brand-600" />
        <span className="text-sm font-semibold text-gray-800">Setup Assistant</span>
      </div>
      <div className="max-h-64 overflow-y-auto p-3 space-y-3">
        {messages.map((m, i) => (
          <div
            key={i}
            className={cn(
              "text-sm rounded-lg px-3 py-2",
              m.role === "user" ? "bg-brand-50 text-brand-900 ml-4" : "bg-slate-50 text-gray-800 mr-4",
            )}
          >
            {m.text}
            {m.route ? (
              <Link href={m.route} className="block mt-2 text-xs font-medium text-brand-600 hover:underline">
                Go to step →
              </Link>
            ) : null}
          </div>
        ))}
      </div>
      <div className="p-3 border-t border-slate-100 flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
          placeholder="Ask for help…"
          className="flex-1 text-sm rounded-lg border border-slate-200 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-brand-500/30"
        />
        <button
          type="button"
          onClick={send}
          disabled={chat.isPending}
          className="rounded-lg bg-brand-600 text-white p-2 hover:bg-brand-700 disabled:opacity-50"
          aria-label="Send"
        >
          <Send size={16} />
        </button>
      </div>
    </div>
  );
}
