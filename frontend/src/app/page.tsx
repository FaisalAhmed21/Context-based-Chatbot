"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ChatWindow } from "@/components/ChatWindow";
import { DocumentSidebar } from "@/components/DocumentSidebar";
import { GoogleSignInButton } from "@/components/GoogleSignInButton";
import { PDFViewer } from "@/components/PDFViewer";
import { UploadZone } from "@/components/UploadZone";
import {
  type ChatMessage,
  type Citation,
  type DocumentOut,
  clearSession,
  createSession,
  deleteDocument,
  getAuthConfig,
  getAuthMe,
  getDocumentStatus,
  getEvalSummary,
  getStoredAccessToken,
  listDocuments,
  listSessions,
  getSessionHistory,
  reingestDocument,
  runEval,
  setStoredAccessToken,
  signInWithGoogle,
  streamMessage,
  tuneEval,
  type EvalSummary,
} from "@/lib/api";

export default function HomePage() {
  const [documents, setDocuments] = useState<DocumentOut[]>([]);
  const [sessions, setSessions] = useState<{id: string, title: string, created_at: string, document_ids?: string[]}[]>([]);
  const [scopeIds, setScopeIds] = useState<string[]>([]);
  const [viewerId, setViewerId] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [page, setPage] = useState(1);
  const [seekSeconds, setSeekSeconds] = useState<number | null>(null);
  const [highlightKey, setHighlightKey] = useState(0);
  const [highlightText, setHighlightText] = useState<string | null>(null);
  const [bootError, setBootError] = useState<string | null>(null);
  const [evalSummary, setEvalSummary] = useState<EvalSummary | null>(null);
  const [evalBusy, setEvalBusy] = useState(false);
  const [evalNote, setEvalNote] = useState<string | null>(null);
  const [authLabel, setAuthLabel] = useState<string | null>(null);
  const [authPicture, setAuthPicture] = useState<string | null>(null);
  const [authEnabled, setAuthEnabled] = useState(false);
  const [googleClientId, setGoogleClientId] = useState<string | null>(null);
  const [signedIn, setSignedIn] = useState(false);

  const viewer = useMemo(
    () => documents.find((d) => d.id === viewerId) || null,
    [documents, viewerId],
  );

  const scopeReady = useMemo(
    () =>
      scopeIds.filter((id) =>
        documents.some((d) => d.id === id && d.status === "ready"),
      ),
    [scopeIds, documents],
  );

  const needsGoogle = authEnabled && !signedIn;

  const refresh = useCallback(async () => {
    try {
      const cfg = await getAuthConfig().catch(() => null);
      if (cfg) {
        setAuthEnabled(cfg.auth_enabled);
        setGoogleClientId(
          cfg.google_client_id ||
            process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID ||
            null,
        );
      } else {
        setGoogleClientId(process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID || null);
      }

      const token = getStoredAccessToken();
      if (cfg?.auth_enabled && !token) {
        setSignedIn(false);
        setAuthLabel(null);
        setDocuments([]);
        setBootError(null);
        return;
      }

      const me = await getAuthMe().catch(() => null);
      if (me) {
        setAuthEnabled(me.auth_enabled);
        setAuthLabel(me.label);
        setAuthPicture(me.picture || null);
        setSignedIn(!!me.user_id || !me.auth_enabled);
        if (me.auth_enabled && !me.user_id) {
          setSignedIn(false);
          return;
        }
      }

      const docs = await listDocuments();
      setDocuments(docs);
      setBootError(null);
      setScopeIds((prev) => {
        if (prev.length) return prev.filter((id) => docs.some((d) => d.id === id));
        const firstReady = docs.find((d) => d.status === "ready") || docs[0];
        return firstReady ? [firstReady.id] : [];
      });
      setViewerId((prev) => {
        if (prev && docs.some((d) => d.id === prev)) return prev;
        const firstReady = docs.find((d) => d.status === "ready") || docs[0];
        return firstReady?.id || null;
      });
      const summary = await getEvalSummary().catch(() => null);
      setEvalSummary(summary);

      const pastSessions = await listSessions().catch(() => []);
      setSessions(pastSessions);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "API unreachable";
      if (/401|Sign in with Google/i.test(msg)) {
        setSignedIn(false);
        setBootError(null);
        return;
      }
      setBootError(
        e instanceof Error
          ? `API unreachable (${e.message}). Start the backend on :8000.`
          : "API unreachable",
      );
    }
  }, []);

  const loadSession = async (id: string) => {
    try {
      const history = await getSessionHistory(id);
      setMessages(history);
      setSessionId(id);
      const session = sessions.find((s) => s.id === id);
      if (session && session.document_ids) {
        setScopeIds(session.document_ids);
      }
    } catch (e) {
      setBootError(e instanceof Error ? e.message : "Failed to load session");
    }
  };

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const pending = documents.filter(
      (d) => d.status !== "ready" && d.status !== "failed",
    );
    if (pending.length === 0) return;
    const t = setInterval(async () => {
      const updates = await Promise.all(
        pending.map((d) => getDocumentStatus(d.id).catch(() => d)),
      );
      setDocuments((prev) =>
        prev.map((d) => updates.find((u) => u.id === d.id) || d),
      );
    }, 1500);
    return () => clearInterval(t);
  }, [documents]);

  useEffect(() => {
    if (scopeReady.length === 0 || needsGoogle) {
      setSessionId(null);
      return;
    }
    let cancelled = false;
    const key = scopeReady.slice().sort().join(",");
    (async () => {
      try {
        const s = await createSession(scopeReady);
        if (!cancelled) {
          setSessionId(s.id);
          setMessages([]);
          setPage(1);
          setSeekSeconds(null);
          setHighlightText(null);
        }
      } catch {

      }
    })();
    return () => {
      cancelled = true;
      void key;
    };
  }, [scopeReady.join(","), needsGoogle]); 

  const onGoogleCredential = async (credential: string) => {
    try {
      const res = await signInWithGoogle(credential);
      setStoredAccessToken(res.access_token);
      setAuthLabel(res.user.label);
      setAuthPicture(res.user.picture || null);
      setSignedIn(true);
      setBootError(null);
      await refresh();
    } catch (e) {
      setBootError(e instanceof Error ? e.message : "Google sign-in failed");
    }
  };

  const onSignOut = () => {
    clearSession();
    setSignedIn(false);
    setAuthLabel(null);
    setAuthPicture(null);
    setDocuments([]);
    setMessages([]);
    setSessionId(null);
  };

  const onSend = async (text: string) => {
    if (!sessionId || scopeReady.length === 0) return;
    setMessages((m) => [...m, { role: "user", content: text }]);
    setStreaming(true);
    setMessages((m) => [
      ...m,
      { role: "assistant", content: "Thinking…", citations: [] },
    ]);

    try {
      let firstToken = true;
      const final = await streamMessage(
        sessionId,
        text,
        (token) => {
          setMessages((m) => {
            const copy = [...m];
            const last = copy[copy.length - 1];
            if (last?.role === "assistant") {
              copy[copy.length - 1] = {
                ...last,
                content: firstToken ? token : last.content + token,
              };
              firstToken = false;
            }
            return copy;
          });
        },
        { documentIds: scopeReady },
      );

      setMessages((m) => {
        const copy = [...m];
        copy[copy.length - 1] = {
          role: "assistant",
          content: final.answer,
          citations: final.citations,
          refused: final.refused,
        };
        return copy;
      });
      const summary = await getEvalSummary().catch(() => null);
      if (summary) setEvalSummary(summary);
    } catch (e) {
      setMessages((m) => {
        const copy = [...m];
        copy[copy.length - 1] = {
          role: "assistant",
          content: e instanceof Error ? e.message : "Request failed",
          refused: true,
        };
        return copy;
      });
    } finally {
      setStreaming(false);
    }
  };

  const onCitation = (c: Citation) => {
    if (c.document_id) setViewerId(c.document_id);
    setHighlightText(c.snippet || null);
    if (c.timestamp_start != null) {
      setSeekSeconds(c.timestamp_start);
      setHighlightKey((k) => k + 1);
    } else if (c.page_number) {
      setPage(c.page_number);
      setSeekSeconds(null);
      setHighlightKey((k) => k + 1);
    } else {
      setHighlightKey((k) => k + 1);
    }
  };

  const onRunEval = async () => {
    if (!scopeReady.length) return;
    setEvalBusy(true);
    setEvalNote(null);
    try {
      const result = await runEval(scopeReady);
      const faith = result.faithfulness;
      const refuse = result.refusal_accuracy;
      setEvalNote(
        `Eval n=${result.n} · faithfulness ${faith} · refusal ${refuse}` +
          (result.ragas && typeof result.ragas === "object"
            ? " · RAGAS attempted"
            : ""),
      );
      const summary = await getEvalSummary().catch(() => null);
      if (summary) setEvalSummary(summary);
    } catch (e) {
      setEvalNote(e instanceof Error ? e.message : "Eval failed");
    } finally {
      setEvalBusy(false);
    }
  };

  const onTune = async () => {
    if (!scopeReady.length) return;
    setEvalBusy(true);
    setEvalNote(null);
    try {
      const result = await tuneEval(scopeReady);
      setEvalNote(
        `Recommended RELEVANCE_THRESHOLD=${result.recommended_threshold} ` +
          `(current ${result.current_threshold}). Update backend .env and restart.`,
      );
    } catch (e) {
      setEvalNote(e instanceof Error ? e.message : "Tune failed");
    } finally {
      setEvalBusy(false);
    }
  };

  return (
    <div className="relative min-h-screen overflow-hidden bg-slate-50">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_top_right,_var(--tw-gradient-stops))] from-amber-100/60 via-stone-100/50 to-orange-50/40" />
      <div className="pointer-events-none absolute inset-0 opacity-[0.03] [background-image:url('data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%224%22 height=%224%22><rect fill=%22%23000%22 width=%221%22 height=%221%22/></svg>')]" />

      <div className="relative mx-auto flex min-h-screen max-w-[1500px] flex-col gap-6 px-4 py-6 md:px-8">
        <header className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="font-display text-4xl tracking-tight md:text-5xl font-extrabold bg-gradient-to-r from-[#B0897B] to-[#9A7B73] bg-clip-text text-transparent drop-shadow-sm">
              OmniCentricBot
            </h1>
            <p className="mt-2 max-w-xl text-sm text-slate-600 font-medium">
              Upload your documents and chat instantly. I can read PDFs, images, and text to help you find answers with perfect accuracy.
            </p>
          </div>
          <div className="flex flex-col items-end gap-2">
            <div className="flex flex-wrap items-center justify-end gap-2">
              {authEnabled && signedIn && (
                <>
                  {authPicture && (

                    <img
                      src={authPicture}
                      alt=""
                      className="h-7 w-7 rounded-full border border-stone-200"
                    />
                  )}
                  <span className="text-[11px] text-stone-600">{authLabel}</span>
                  <button
                    type="button"
                    onClick={onSignOut}
                    className="rounded-lg border border-stone-300 bg-white px-2 py-1 text-[11px] text-stone-700 hover:border-teal-600"
                  >
                    Sign out
                  </button>
                </>
              )}
              {authEnabled && !signedIn && googleClientId && (
                <GoogleSignInButton
                  clientId={googleClientId}
                  onCredential={onGoogleCredential}
                />
              )}
              {authEnabled && !signedIn && !googleClientId && (
                <p className="max-w-[220px] text-right text-[11px] text-[#A07A6C]">
                  Set GOOGLE_CLIENT_ID on the backend (and NEXT_PUBLIC_GOOGLE_CLIENT_ID).
                </p>
              )}
            </div>
          </div>
        </header>

        {bootError && (
          <div className="rounded-xl border border-[#EAD8D0] bg-[#F9F5F3] px-4 py-3 text-sm text-[#75554B]">
            {bootError}
          </div>
        )}

        {needsGoogle && (
          <div className="rounded-2xl border border-stone-200 bg-white/90 px-6 py-12 text-center shadow-sm">
            <p className="font-display text-2xl text-stone-900">Sign in to continue</p>
            <p className="mx-auto mt-2 max-w-md text-sm text-stone-600">
              Grounded uses Google Sign-In only — no passwords or API keys. Your
              documents stay scoped to your account.
            </p>
            <div className="mt-6 flex justify-center">
              {googleClientId ? (
                <GoogleSignInButton
                  clientId={googleClientId}
                  onCredential={onGoogleCredential}
                />
              ) : (
                <p className="max-w-sm text-sm text-[#8A665A]">
                  Missing Google Client ID. Follow{" "}
                  <span className="font-medium">docs/GOOGLE_AUTH.md</span> — set
                  GOOGLE_CLIENT_ID in backend/.env and NEXT_PUBLIC_GOOGLE_CLIENT_ID
                  in frontend/.env.local, then restart both servers.
                </p>
              )}
            </div>
            <p className="mx-auto mt-6 max-w-md text-[11px] leading-relaxed text-stone-500">
              Tip: in Google Cloud, add the exact origin from your browser bar
              (e.g. http://localhost:3000) under Authorized JavaScript origins.
            </p>
          </div>
        )}

        {!needsGoogle && scopeReady.length > 1 && (
          <p className="rounded-xl border border-teal-200 bg-teal-50/80 px-4 py-2 text-xs text-teal-900">
            Chat scoped to {scopeReady.length} documents — answers can cite across them.
          </p>
        )}

        {!needsGoogle && (
          <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[260px_1fr_1fr] lg:gap-6 lg:h-[calc(100vh-180px)]">
            <div className="rounded-3xl border border-white/60 bg-white/70 p-5 shadow-lg shadow-amber-900/5 backdrop-blur-xl flex flex-col min-h-0 min-w-0 overflow-y-auto custom-scrollbar">
              <UploadZone
                onUploaded={(doc) => {
                  setDocuments((prev) => [doc, ...prev.filter((d) => d.id !== doc.id)]);
                  setViewerId(doc.id);
                  setScopeIds((prev) =>
                    prev.includes(doc.id) ? prev : [...prev, doc.id],
                  );
                }}
              />
              <div className="mt-6 h-px bg-stone-200/70" />
              <div className="mt-4 flex-1 overflow-y-auto custom-scrollbar pr-2">
                <DocumentSidebar
                  documents={documents}
                  scopeIds={scopeIds}
                  viewerId={viewerId}
                  onToggleScope={(id) => {
                    setScopeIds((prev) =>
                      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
                    );
                  }}
                  onView={(id) => {
                    setViewerId(id);
                    setPage(1);
                    setSeekSeconds(null);
                    setHighlightText(null);
                  }}
                  onSelectAllReady={() => {
                    const ids = documents
                      .filter((d) => d.status === "ready")
                      .map((d) => d.id);
                    setScopeIds(ids);
                  }}
                  onReingest={async (id) => {
                    const doc = await reingestDocument(id);
                    setDocuments((prev) => prev.map((d) => (d.id === id ? doc : d)));
                  }}
                  onDelete={async (id) => {
                    await deleteDocument(id);
                    setDocuments((prev) => prev.filter((d) => d.id !== id));
                    setScopeIds((prev) => prev.filter((x) => x !== id));
                    if (viewerId === id) setViewerId(null);
                  }}
                />
              </div>
            </div>

            <div className="min-h-[360px] lg:min-h-0 flex flex-col min-w-0 rounded-3xl border border-white/60 bg-white/70 shadow-lg shadow-amber-900/5 backdrop-blur-xl overflow-hidden">
              <PDFViewer
                documentId={viewer?.id || null}
                filename={viewer?.filename || null}
                contentType={viewer?.content_type}
                page={page}
                pageCount={viewer?.page_count}
                onPageChange={setPage}
                highlightKey={highlightKey}
                highlightText={highlightText}
                seekSeconds={seekSeconds}
              />
            </div>

            <div className="flex flex-col min-h-[420px] lg:min-h-0 min-w-0 rounded-3xl border border-white/60 bg-white/70 p-5 shadow-lg shadow-amber-900/5 backdrop-blur-xl overflow-y-auto custom-scrollbar">
              <div className="mb-4 flex items-center justify-between border-b border-stone-200/70 pb-3">
                <h2 className="text-sm font-bold tracking-wide text-stone-800 flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-[#F9F5F3]0 shadow-[0_0_8px_rgba(216,180,160,0.6)] animate-pulse"></span>
                  OmniCentric Chat
                </h2>

                {sessions.length > 0 && (
                  <select
                    className="rounded border border-stone-200 bg-white px-2 py-1 text-[11px] text-stone-600 outline-none"
                    value={sessionId || ""}
                    onChange={(e) => {
                      if (e.target.value) {
                        loadSession(e.target.value);
                      }
                    }}
                  >
                    <option value="" disabled>Recent chats...</option>
                    {sessions.map((s) => (
                      <option key={s.id} value={s.id}>
                        {new Date(s.created_at).toLocaleDateString()} - {s.title || "Chat"} ({s.document_ids?.length || 0} docs)
                      </option>
                    ))}
                  </select>
                )}
              </div>
              <ChatWindow
                messages={messages}
                streaming={streaming}
                disabled={scopeReady.length === 0 || !sessionId}
                onSend={onSend}
                onCitationClick={onCitation}
              />
            </div>
          </div>
        )}

        <p className="pb-4 text-center text-[11px] text-stone-500">
          API docs:{" "}
          <a
            className="text-teal-800 underline"
            href={`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/docs`}
            target="_blank"
            rel="noreferrer"
          >
            /docs
          </a>
        </p>
      </div>
    </div>
  );
}
