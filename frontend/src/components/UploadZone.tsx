"use client";

import { useCallback, useRef, useState } from "react";
import type { DocumentOut } from "@/lib/api";
import { ingestFromUrl, uploadDocument } from "@/lib/api";

type Props = {
  onUploaded: (doc: DocumentOut) => void;
};

const STAGES = ["parsing", "chunking", "embedding", "ready"] as const;
const ACCEPT =
  ".pdf,.png,.jpg,.jpeg,.webp,.gif,.txt,.md,.markdown,.csv,.html,application/pdf,image/*,text/*";

function isAllowed(file: File): boolean {
  const n = file.name.toLowerCase();
  return (
    n.endsWith(".pdf") ||
    /\.(png|jpe?g|webp|gif|bmp)$/.test(n) ||
    /\.(txt|md|markdown|csv|json|log|html?)$/.test(n)
  );
}

export function UploadZone({ onUploaded }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [url, setUrl] = useState("");

  const handleFile = useCallback(
    async (file: File) => {
      if (!isAllowed(file)) {
        setError("Upload PDF, image, or text file (≤25MB).");
        return;
      }
      setError(null);
      setBusy(true);
      try {
        const doc = await uploadDocument(file);
        onUploaded(doc);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Upload failed");
      } finally {
        setBusy(false);
      }
    },
    [onUploaded],
  );

  const handleUrl = useCallback(async () => {
    const trimmed = url.trim();
    if (!trimmed) return;
    setError(null);
    setBusy(true);
    try {
      const doc = await ingestFromUrl(trimmed);
      onUploaded(doc);
      setUrl("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "URL ingest failed");
    } finally {
      setBusy(false);
    }
  }, [url, onUploaded]);

  return (
    <div className="space-y-3">
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          const file = e.dataTransfer.files?.[0];
          if (file) void handleFile(file);
        }}
        disabled={busy}
        className={`w-full rounded-xl border border-dashed px-6 py-8 text-left transition flex flex-col items-center justify-center text-center ${
          dragging
            ? "border-[#B87A5D] bg-[#F9F5F3]/80"
            : "border-stone-300 bg-stone-50/50 hover:border-[#B87A5D] hover:bg-stone-50"
        } disabled:opacity-60`}
      >
        <p className="font-display text-lg font-medium text-stone-800">Upload Document</p>
        <p className="mt-2 max-w-sm text-sm text-stone-500">
          Drop a PDF, image, or text file here.
        </p>
        {busy && (
          <p className="mt-4 text-xs font-medium uppercase tracking-wide text-[#A07A6C]">
            Uploading…
          </p>
        )}
      </button>
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT}
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) void handleFile(file);
          e.target.value = "";
        }}
      />

      <div className="flex gap-2">
        <input
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="Or paste a web page URL…"
          disabled={busy}
          className="min-w-0 flex-1 rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm outline-none focus:border-[#B87A5D]"
          onKeyDown={(e) => {
            if (e.key === "Enter") void handleUrl();
          }}
        />
        <button
          type="button"
          disabled={busy || !url.trim()}
          onClick={() => void handleUrl()}
          className="rounded-lg bg-[#B87A5D] px-4 py-2 text-xs font-medium text-white hover:bg-[#A36B50] disabled:opacity-40 transition-colors"
        >
          Add
        </button>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}
    </div>
  );
}

