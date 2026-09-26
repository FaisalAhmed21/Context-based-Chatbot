"use client";

import { useEffect, useRef, useState } from "react";
import type { ChatMessage, Citation } from "@/lib/api";
import { CitationList } from "@/components/CitationChip";

type Props = {
  messages: ChatMessage[];
  streaming: boolean;
  disabled?: boolean;
  onSend: (text: string) => void;
  onCitationClick?: (c: Citation) => void;
};

export function ChatWindow({
  messages,
  streaming,
  disabled,
  onSend,
  onCitationClick,
}: Props) {
  const [draft, setDraft] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streaming]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-1 py-2">
        {messages.length === 0 && (
          <p className="rounded-lg bg-[#F9F5F3]/50 px-4 py-3 text-sm text-stone-600">
            Hello! I'm ready to answer any questions about your uploaded documents.
          </p>
        )}
        {messages.map((m, i) => (
          <div
            key={m.id || i}
            className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[92%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                m.role === "user"
                  ? "bg-[#B87A5D] text-white shadow-sm"
                  : m.refused
                    ? "border border-amber-200 bg-[#F9F5F3] text-[#8A665A]"
                    : "border border-stone-200 bg-white text-stone-800 shadow-sm"
              }`}
            >
              {m.refused && (
                <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-[#A07A6C]">
                  Insufficient context
                </p>
              )}
              {streaming &&
                i === messages.length - 1 &&
                m.role === "assistant" &&
                m.content === "Thinking…" && (
                  <span className="mr-2 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-[#F9F5F3]0" />
                )}
              <p className="whitespace-pre-wrap">{m.content}</p>
              {!!m.citations?.length && (
                <CitationList
                  citations={m.citations}
                  onClick={onCitationClick}
                />
              )}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <form
        className="mt-3 flex gap-2 border-t border-stone-200 pt-3"
        onSubmit={(e) => {
          e.preventDefault();
          const text = draft.trim();
          if (!text || disabled || streaming) return;
          setDraft("");
          onSend(text);
        }}
      >
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          disabled={disabled || streaming}
          placeholder={
            disabled ? "Upload & wait for Ready…" : "Ask a question…"
          }
          className="min-w-0 flex-1 rounded-xl border border-stone-300 bg-stone-50 px-3 py-2.5 text-sm outline-none focus:border-[#B87A5D] focus:bg-white transition-colors disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={disabled || streaming || !draft.trim()}
          className="rounded-xl bg-[#B87A5D] px-5 py-2.5 text-sm font-medium text-white hover:bg-[#A36B50] disabled:opacity-40 transition-colors shadow-sm"
        >
          Send
        </button>
      </form>
    </div>
  );
}
