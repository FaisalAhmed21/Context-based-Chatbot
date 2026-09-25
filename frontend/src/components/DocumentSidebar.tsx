"use client";

import type { DocumentOut } from "@/lib/api";

type Props = {
  documents: DocumentOut[];
  scopeIds: string[];
  viewerId: string | null;
  onToggleScope: (id: string) => void;
  onView: (id: string) => void;
  onDelete: (id: string) => void;
  onReingest?: (id: string) => void;
  onSelectAllReady: () => void;
};

const STATUS_LABEL: Record<string, string> = {
  pending: "Queued",
  parsing: "Parsing",
  chunking: "Chunking",
  embedding: "Embedding",
  ready: "Ready",
  failed: "Failed",
};

export function DocumentSidebar({
  documents,
  scopeIds,
  viewerId,
  onToggleScope,
  onView,
  onDelete,
  onReingest,
  onSelectAllReady,
}: Props) {
  const readyCount = documents.filter((d) => d.status === "ready").length;

  return (
    <aside className="flex h-full flex-col gap-3">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-stone-500">
          Knowledge base
        </h2>
        {readyCount > 1 && (
          <button
            type="button"
            onClick={onSelectAllReady}
            className="text-[10px] font-medium text-teal-800 hover:underline"
          >
            Scope all ready
          </button>
        )}
      </div>
      <p className="text-[11px] leading-snug text-stone-500">
        Check docs to include in chat. Click a name to preview. Re-index updates vectors
        without retraining.
      </p>
      <ul className="space-y-2 overflow-y-auto">
        {documents.length === 0 && (
          <li className="text-sm text-stone-500">No uploads yet.</li>
        )}
        {documents.map((d) => {
          const inScope = scopeIds.includes(d.id);
          const viewing = d.id === viewerId;
          const ready = d.status === "ready";
          return (
            <li key={d.id}>
              <div
                className={`group rounded-xl border px-3 py-2 transition ${
                  viewing
                    ? "border-teal-700 bg-teal-50"
                    : inScope
                      ? "border-teal-600/40 bg-white"
                      : "border-stone-200 bg-white/70 hover:border-stone-300"
                }`}
              >
                <div className="flex items-start gap-2">
                  <input
                    type="checkbox"
                    className="mt-1 accent-teal-800"
                    checked={inScope}
                    disabled={!ready}
                    onChange={() => onToggleScope(d.id)}
                    title={ready ? "Include in chat scope" : "Wait until ready"}
                  />
                  <button
                    type="button"
                    className="min-w-0 flex-1 text-left"
                    onClick={() => onView(d.id)}
                  >
                    <p className="truncate text-sm font-medium text-stone-900">
                      {d.filename}
                    </p>
                    <p className="mt-0.5 text-[11px] text-stone-500">
                      {STATUS_LABEL[d.status] || d.status}
                      {d.page_count != null ? ` · ${d.page_count} pages` : ""}
                      {d.chunk_count != null ? ` · ${d.chunk_count} chunks` : ""}
                      {inScope ? " · in chat" : ""}
                    </p>
                    {d.status === "failed" && d.error_message && (
                      <p className="mt-1 line-clamp-2 text-[11px] text-red-700">
                        {d.error_message}
                      </p>
                    )}
                  </button>
                </div>
                <div className="mt-1 flex gap-3 opacity-0 transition group-hover:opacity-100">
                  {onReingest && (ready || d.status === "failed") && (
                    <button
                      type="button"
                      onClick={() => onReingest(d.id)}
                      className="text-[11px] text-stone-500 hover:text-teal-800"
                    >
                      Re-index
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => onDelete(d.id)}
                    className="text-[11px] text-stone-400 hover:text-red-700"
                  >
                    Remove
                  </button>
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}
