function resolveApiUrl(): string {

  if (process.env.NEXT_PUBLIC_API_URL) return process.env.NEXT_PUBLIC_API_URL;
  return "/backend";
}

const API_URL = resolveApiUrl();
const TOKEN_KEY = "grounded_access_token";

function authHeaders(): HeadersInit {
  if (typeof window === "undefined") return {};
  const token = window.localStorage.getItem(TOKEN_KEY);
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export type DocumentStatus =
  | "pending"
  | "parsing"
  | "chunking"
  | "embedding"
  | "ready"
  | "failed";

export type DocumentOut = {
  id: string;
  filename: string;
  status: DocumentStatus;
  page_count: number | null;
  chunk_count: number | null;
  error_message: string | null;
  content_type?: string | null;
};

export type Citation = {
  document_id: string;
  document_name?: string | null;
  page_number?: number | null;
  section_title?: string | null;
  chunk_id?: string | null;
  snippet?: string | null;
  timestamp_start?: number | null;
  timestamp_end?: number | null;
};

export type ChatMessage = {
  id?: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  refused?: boolean;
};

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text();
    try {
      const json = JSON.parse(text) as { detail?: unknown };
      if (typeof json.detail === "string") throw new Error(json.detail);
      if (Array.isArray(json.detail)) {
        const msg = json.detail
          .map((d) =>
            typeof d === "object" && d && "msg" in d
              ? String((d as { msg: string }).msg)
              : JSON.stringify(d),
          )
          .join("; ");
        throw new Error(msg || text || res.statusText);
      }
    } catch (e) {
      if (e instanceof Error && !(e instanceof SyntaxError)) throw e;
    }
    throw new Error(text || res.statusText);
  }
  return res.json() as Promise<T>;
}

export async function listDocuments(): Promise<DocumentOut[]> {
  return handle(await fetch(`${API_URL}/documents`, { headers: authHeaders() }));
}

export async function uploadDocument(file: File): Promise<DocumentOut> {
  const form = new FormData();
  form.append("file", file);
  return handle(
    await fetch(`${API_URL}/documents/upload`, {
      method: "POST",
      headers: authHeaders(),
      body: form,
    }),
  );
}

export async function ingestFromUrl(url: string, title?: string): Promise<DocumentOut> {
  return handle(
    await fetch(`${API_URL}/documents/from-url`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ url, title }),
    }),
  );
}

export async function reingestDocument(id: string): Promise<DocumentOut> {
  return handle(
    await fetch(`${API_URL}/documents/${id}/reingest`, {
      method: "POST",
      headers: authHeaders(),
    }),
  );
}

export async function getDocumentStatus(id: string): Promise<DocumentOut> {
  return handle(
    await fetch(`${API_URL}/documents/${id}/status`, { headers: authHeaders() }),
  );
}

export async function deleteDocument(id: string): Promise<void> {
  await handle(
    await fetch(`${API_URL}/documents/${id}`, {
      method: "DELETE",
      headers: authHeaders(),
    }),
  );
}

export async function createSession(documentIds?: string[], title?: string): Promise<{ id: string }> {
  const res = await fetch(`${API_URL}/chat/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ document_ids: documentIds, title }),
  });
  if (!res.ok) throw new Error("Failed to create session");
  return res.json() as Promise<{ id: string }>;
}

export async function listSessions(): Promise<{ id: string; title: string; created_at: string; document_ids: string[] }[]> {
  const res = await fetch(`${API_URL}/chat/sessions`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error("Failed to fetch sessions");
  return res.json() as Promise<{ id: string; title: string; created_at: string; document_ids: string[] }[]>;
}

export async function getSessionHistory(sessionId: string): Promise<ChatMessage[]> {
  const res = await fetch(`${API_URL}/chat/${sessionId}/history`, {
    headers: authHeaders(),
  });
  if (!res.ok) return [];
  const msgs = (await res.json()) as ChatMessage[];
  return msgs.map((m) => ({
    id: m.id,
    role: m.role,
    content: m.content,
    citations: m.citations,
    refused: m.refused,
  }));
}

export async function sendMessage(
  sessionId: string,
  content: string,
  opts?: { documentIds?: string[]; stream?: boolean },
): Promise<ChatMessage> {
  return handle(
    await fetch(`${API_URL}/chat/${sessionId}/message`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({
        content,
        document_ids: opts?.documentIds,
        stream: false,
      }),
    }),
  );
}

export async function streamMessage(
  sessionId: string,
  content: string,
  onToken: (token: string) => void,
  opts?: { documentIds?: string[] },
): Promise<{ answer: string; citations: Citation[]; refused: boolean }> {
  const res = await fetch(`${API_URL}/chat/${sessionId}/message`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({
      content,
      document_ids: opts?.documentIds,
      stream: true,
    }),
  });

  if (!res.ok) {
    throw new Error(await res.text());
  }

  if (!res.body) {
    throw new Error("No response body");
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  return new Promise(async (resolve, reject) => {
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        let currentEvent = "message";
        for (const line of lines) {
          if (line.startsWith("event: ")) {
            currentEvent = line.slice(7).trim();
          } else if (line.startsWith("data: ")) {
            const dataStr = line.slice(6).trim();
            if (!dataStr) continue;
            try {
              const data = JSON.parse(dataStr);
              if (currentEvent === "token" && data.token) {
                onToken(data.token);
              } else if (currentEvent === "done") {
                resolve({
                  answer: data.answer || "",
                  citations: data.citations || [],
                  refused: !!data.refused,
                });
                return;
              }
            } catch {

            }
          }
        }
      }

      resolve({ answer: "", citations: [], refused: true });
    } catch (e) {
      reject(e);
    }
  });
}

export function documentFileUrl(id: string): string {
  const base = `${API_URL}/documents/${id}/file`;
  if (typeof window === "undefined") return base;
  const token = window.localStorage.getItem(TOKEN_KEY);
  if (!token) return base;
  const sep = base.includes("?") ? "&" : "?";
  return `${base}${sep}token=${encodeURIComponent(token)}`;
}

export type EvalSummary = {
  total_gate_events: number;
  by_gate: Record<string, number>;
  suggested_relevance_threshold?: number | null;
  recent: Array<{
    gate: string;
    question: string;
    top_score: number | null;
    created_at: string | null;
  }>;
};

export async function getEvalSummary(): Promise<EvalSummary> {
  return handle(await fetch(`${API_URL}/eval/summary`, { headers: authHeaders() }));
}

export async function getAuthConfig(): Promise<{
  auth_enabled: boolean;
  provider: string;
  google_client_id: string | null;
}> {
  return handle(await fetch(`${API_URL}/auth/config`));
}

export async function getAuthMe(): Promise<{
  auth_enabled: boolean;
  provider?: string;
  user_id: string | null;
  label: string;
  email?: string | null;
  picture?: string | null;
}> {
  return handle(await fetch(`${API_URL}/auth/me`, { headers: authHeaders() }));
}

export async function signInWithGoogle(credential: string): Promise<{
  access_token: string;
  user: { id: string; email: string | null; label: string; picture?: string | null };
}> {
  return handle(
    await fetch(`${API_URL}/auth/google`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ credential }),
    }),
  );
}

export function getStoredAccessToken(): string {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem(TOKEN_KEY) || "";
}

export function setStoredAccessToken(token: string | null): void {
  if (typeof window === "undefined") return;
  if (token && token.trim()) window.localStorage.setItem(TOKEN_KEY, token.trim());
  else window.localStorage.removeItem(TOKEN_KEY);
}

export function clearSession(): void {
  setStoredAccessToken(null);
}

export async function runEval(documentIds: string[]): Promise<Record<string, unknown>> {
  return handle(
    await fetch(`${API_URL}/eval/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ document_ids: documentIds }),
    }),
  );
}

export async function tuneEval(
  documentIds: string[],
): Promise<Record<string, unknown>> {
  return handle(
    await fetch(`${API_URL}/eval/tune`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ document_ids: documentIds }),
    }),
  );
}

export function getStoredApiKey(): string {
  return "";
}

export function setStoredApiKey(): void {

}
