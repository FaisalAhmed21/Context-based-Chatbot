"use client";

import type { Citation } from "@/lib/api";

type Props = {
  citations: Citation[];
  onClick?: (citation: Citation) => void;
};

function formatTs(s: number): string {
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${sec.toString().padStart(2, "0")}`;
}

function uniqueByPage(citations: Citation[]): Citation[] {
  const map = new Map<string, Citation>();
  for (const c of citations) {
    const key = `${c.document_id}:${c.page_number ?? "x"}:${c.timestamp_start ?? "x"}`;
    if (!map.has(key)) map.set(key, c);
  }
  return Array.from(map.values());
}

export function CitationList({ citations, onClick }: Props) {
  const unique = uniqueByPage(citations);
  if (!unique.length) return null;

  const docName = unique[0]?.document_name;

  return (
    <div className="mt-3 border-t border-stone-100 pt-2">
      <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-stone-500">
        Sources{docName ? ` · ${docName}` : ""}
      </p>
      <div className="flex flex-wrap gap-1.5">
        {unique.map((c, j) => {
          let pageLabel: string;
          if (c.timestamp_start != null) {
            pageLabel = `@ ${formatTs(c.timestamp_start)}`;
          } else if (c.page_number != null) {
            pageLabel = `Page ${c.page_number}`;
          } else {
            pageLabel = c.section_title || "Source";
          }
          const section =
            c.timestamp_start == null && c.section_title
              ? ` — ${c.section_title}`
              : "";
          return (
            <button
              key={`${c.document_id}-${c.page_number}-${c.timestamp_start}-${j}`}
              type="button"
              title={c.snippet || "Jump to source"}
              onClick={() => onClick?.(c)}
              className="group max-w-full rounded-lg border border-stone-200 bg-stone-50 px-2.5 py-1.5 text-left text-xs text-stone-700 transition hover:border-teal-600 hover:bg-teal-50 hover:text-teal-950"
            >
              <span className="font-medium text-teal-800 group-hover:underline">
                {pageLabel}
              </span>
              {section && <span className="text-stone-500">{section}</span>}
              {c.snippet && (
                <span className="mt-0.5 block truncate text-[11px] leading-snug text-stone-500">
                  {c.snippet}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}

