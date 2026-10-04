"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import { documentFileUrl } from "@/lib/api";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url,
).toString();

type Props = {
  documentId: string | null;
  filename: string | null;
  contentType?: string | null;
  page: number;
  onPageChange: (page: number) => void;
  pageCount?: number | null;
  highlightKey?: number;
  highlightText?: string | null;
  seekSeconds?: number | null;
};

function isImageName(name: string | null, contentType?: string | null): boolean {
  if (contentType?.startsWith("image/")) return true;
  if (!name) return false;
  return /\.(png|jpe?g|webp|gif|bmp)$/i.test(name);
}

function isVideoName(name: string | null, contentType?: string | null): boolean {
  if (contentType?.startsWith("video/") || contentType?.startsWith("audio/")) return true;
  if (!name) return false;
  return /\.(mp4|webm|mov|mkv|avi|mpeg|mp3|wav|m4a)$/i.test(name);
}

function isTextish(name: string | null, contentType?: string | null): boolean {
  if (contentType === "text/uri-list" || contentType?.startsWith("text/")) return true;
  if (!name) return false;
  return /\.(txt|md|markdown|csv|json|log|html?|url)$/i.test(name);
}

function formatTs(s: number): string {
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${sec.toString().padStart(2, "0")}`;
}

function norm(s: string): string {
  return s.toLowerCase().replace(/\s+/g, " ").trim();
}

function highlightSnippetInLayer(root: HTMLElement, snippet: string | null | undefined) {
  // Remove previous highlights — we use CSS classes instead of <mark> elements
  // to avoid disrupting react-pdf's absolute-positioned text layer (which causes blur)
  root.querySelectorAll(".citation-hl").forEach((el) => {
    el.classList.remove("citation-hl");
    (el as HTMLElement).style.removeProperty("background");
    (el as HTMLElement).style.removeProperty("border-radius");
    (el as HTMLElement).style.removeProperty("box-shadow");
  });
  // Also clean up legacy <mark> elements from previous version
  root.querySelectorAll("mark.citation-hl").forEach((el) => {
    const parent = el.parentNode;
    if (!parent) return;
    parent.replaceChild(document.createTextNode(el.textContent || ""), el);
    parent.normalize();
  });

  if (!snippet) return;
  const needle = norm(snippet).slice(0, 120);
  if (needle.length < 8) return;

  const unsortedSpans = Array.from(
    root.querySelectorAll(".react-pdf__Page__textContent span")
  ) as HTMLElement[];
  if (!unsortedSpans.length) return;

  const spans = unsortedSpans.sort((a, b) => {
    const yDiff = a.offsetTop - b.offsetTop;
    if (Math.abs(yDiff) > 5) return yDiff;
    return a.offsetLeft - b.offsetLeft;
  });

  const spacelessNeedle = snippet.toLowerCase().replace(/[^a-z0-9]/g, "").slice(0, 100);
  if (spacelessNeedle.length < 8) return;

  const charToSpan: HTMLElement[] = [];
  let spacelessHaystack = "";
  
  for (const el of spans) {
    const text = el.textContent || "";
    const spacelessText = text.toLowerCase().replace(/[^a-z0-9]/g, "");
    spacelessHaystack += spacelessText;
    for (let i = 0; i < spacelessText.length; i++) {
      charToSpan.push(el);
    }
  }

  let idx = spacelessHaystack.indexOf(spacelessNeedle);
  if (idx < 0) {
    const short = spacelessNeedle.slice(0, Math.min(30, spacelessNeedle.length));
    idx = spacelessHaystack.indexOf(short);
    if (idx < 0) return;
  }
  
  const endIdx = idx + spacelessNeedle.length;

  const toMark = new Set<HTMLElement>();
  for (let i = idx; i < endIdx && i < charToSpan.length; i++) {
    toMark.add(charToSpan[i]);
  }

  let first: HTMLElement | null = null;
  for (const el of Array.from(toMark).slice(0, 35)) {
    el.classList.add("citation-hl");
    el.style.background = "rgba(13, 148, 136, 0.25)";
    el.style.borderRadius = "2px";
    el.style.boxShadow = "0 0 0 2px rgba(13, 148, 136, 0.15)";
    if (!first) first = el;
  }
  first?.scrollIntoView({ behavior: "smooth", block: "center" });
}

export function PDFViewer({
  documentId,
  filename,
  contentType,
  page,
  onPageChange,
  pageCount: pageCountHint,
  highlightKey = 0,
  highlightText = null,
  seekSeconds = null,
}: Props) {
  const [numPages, setNumPages] = useState<number | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [flash, setFlash] = useState(false);
  const videoRef = useRef<HTMLMediaElement | null>(null);
  const pageWrapRef = useRef<HTMLDivElement | null>(null);

  const fileUrl = documentId ? documentFileUrl(documentId) : null;
  const imageMode = isImageName(filename, contentType);
  const videoMode = isVideoName(filename, contentType);
  const textMode = !imageMode && !videoMode && isTextish(filename, contentType);
  const pdfMode = !!fileUrl && !imageMode && !videoMode && !textMode;
  const total = imageMode || videoMode || textMode ? 1 : numPages ?? pageCountHint ?? null;
  const audioOnly =
    contentType?.startsWith("audio/") ||
    (!!filename && /\.(mp3|wav|m4a)$/i.test(filename));

  useEffect(() => {
    if (!highlightKey) return;
    setFlash(true);
    const t = setTimeout(() => setFlash(false), 900);
    return () => clearTimeout(t);
  }, [highlightKey, page, seekSeconds]);

  useEffect(() => {
    if (seekSeconds == null || !videoRef.current) return;
    try {
      videoRef.current.currentTime = Math.max(0, seekSeconds);
      void videoRef.current.play().catch(() => undefined);
    } catch {

    }
  }, [seekSeconds, highlightKey, documentId]);

  useEffect(() => {
    if (!pdfMode || !highlightKey) return;
    const t = setTimeout(() => {
      if (pageWrapRef.current) {
        highlightSnippetInLayer(pageWrapRef.current, highlightText);
      }
    }, 350);
    return () => clearTimeout(t);
  }, [pdfMode, highlightKey, highlightText, page]);

  const onLoadSuccess = useCallback(({ numPages: n }: { numPages: number }) => {
    setNumPages(n);
    setLoadError(null);
  }, []);

  return (
    <div className="flex h-full flex-col rounded-2xl border border-stone-200 bg-white/80">
      <div className="flex items-center justify-between border-b border-stone-200 px-4 py-2">
        <p className="truncate text-sm font-medium text-stone-800">
          {filename || "No document selected"}
        </p>
        {pdfMode && (
          <div className="flex items-center gap-2 text-xs text-stone-600">
            <button
              type="button"
              className="rounded border border-stone-300 px-2 py-0.5 disabled:opacity-40"
              disabled={page <= 1}
              onClick={() => onPageChange(Math.max(1, page - 1))}
            >
              Prev
            </button>
            <span>
              {page}
              {total ? ` / ${total}` : ""}
            </span>
            <button
              type="button"
              className="rounded border border-stone-300 px-2 py-0.5 disabled:opacity-40"
              disabled={!!total && page >= total}
              onClick={() => onPageChange(page + 1)}
            >
              Next
            </button>
          </div>
        )}
        {imageMode && (
          <span className="text-[11px] uppercase tracking-wide text-stone-500">Image</span>
        )}
        {videoMode && (
          <span className="text-[11px] uppercase tracking-wide text-stone-500">
            {audioOnly ? "Audio" : "Video"}
            {seekSeconds != null ? ` · ${formatTs(seekSeconds)}` : ""}
          </span>
        )}
        {textMode && (
          <span className="text-[11px] uppercase tracking-wide text-stone-500">Text / web</span>
        )}
      </div>

      <div className="relative flex flex-1 items-start justify-center overflow-auto bg-[radial-gradient(ellipse_at_top,_#f5f5f4,_#e7e5e4)] p-4">
        <div className="absolute inset-0 opacity-[0.07] [background-image:linear-gradient(to_right,#444_1px,transparent_1px),linear-gradient(to_bottom,#444_1px,transparent_1px)] [background-size:24px_24px]" />

        {!fileUrl && (
          <div className="relative z-[1] mx-auto mt-16 max-w-sm rounded bg-white/90 p-6 text-center shadow-sm">
            <p className="font-display text-lg text-white">Preview</p>
            <p className="mt-2 text-sm text-stone-600">
              Upload a PDF, image, video, or text. Citation chips jump to the page or
              timestamp and highlight the source snippet.
            </p>
          </div>
        )}

        {fileUrl && imageMode && (
          <div
            className={`relative z-[1] max-w-full transition ${
              flash ? "ring-2 ring-[#B87A5D] ring-offset-4" : ""
            }`}
          >
            {}
            <img
              src={fileUrl}
              alt={filename || "uploaded"}
              className="max-h-[70vh] max-w-full rounded shadow-md"
            />
          </div>
        )}

        {fileUrl && videoMode && (
          <div
            className={`relative z-[1] w-full max-w-xl transition ${
              flash ? "ring-2 ring-[#B87A5D] ring-offset-4" : ""
            }`}
          >
            {audioOnly ? (
              <audio
                ref={(el) => {
                  videoRef.current = el;
                }}
                src={fileUrl}
                controls
                className="w-full"
              />
            ) : (
              <video
                ref={(el) => {
                  videoRef.current = el;
                }}
                src={fileUrl}
                controls
                className="max-h-[70vh] w-full rounded shadow-md"
              />
            )}
            <p className="mt-2 text-center text-[11px] text-stone-500">
              Whisper transcript is indexed; click a citation to seek.
            </p>
          </div>
        )}

        {fileUrl && textMode && (
          <iframe
            title={filename || "text"}
            src={fileUrl}
            className={`relative z-[1] h-[70vh] w-full max-w-xl rounded border border-stone-200 bg-white shadow-md ${
              flash ? "ring-2 ring-[#B87A5D] ring-offset-4" : ""
            }`}
          />
        )}

        {fileUrl && pdfMode && (
          <div
            ref={pageWrapRef}
            className={`relative z-[1] transition ring-offset-2 ${
              flash ? "ring-2 ring-[#B87A5D] ring-offset-4" : ""
            }`}
          >
            <Document
              file={fileUrl}
              loading={
                <p className="rounded bg-white/90 px-4 py-3 text-sm text-stone-600">
                  Loading PDF…
                </p>
              }
              onLoadSuccess={onLoadSuccess}
              onLoadError={(err) => {
                const msg = err.message || "Failed to load PDF";
                setLoadError(msg.replace(/[\?&]token=[^"\s]+/g, ""));
              }}
              error={
                <p className="rounded border border-[#EAD8D0] bg-[#F9F5F3] px-4 py-3 text-sm text-[#75554B]">
                  {loadError || "Could not load PDF"}
                </p>
              }
            >
              <Page
                pageNumber={page}
                width={480}
                renderTextLayer
                renderAnnotationLayer
                className="shadow-md"
                onRenderTextLayerSuccess={() => {
                  if (pageWrapRef.current && highlightText) {
                    highlightSnippetInLayer(pageWrapRef.current, highlightText);
                  }
                }}
              />
            </Document>
          </div>
        )}
      </div>
    </div>
  );
}
