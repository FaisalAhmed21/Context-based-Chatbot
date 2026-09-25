# Grounded — RAG Chatbot

Context-grounded multimodal QA: upload PDF / image / video / text / web pages, ask questions, get answers **only** from your knowledge base — or an explicit refusal when context is insufficient.

## What makes this different

1. **Hybrid retrieval + reranking** — dense + BM25 → RRF → cross-encoder
2. **Honest refusal** — relevance gate + groundedness check (not prompt-only)
3. **Modality-ready pipeline** — `DocumentLoader` → `RawElement` → `Chunk` (PDF, image, Whisper video, text, web)
4. **Lightweight GraphRAG** — entity/relation expand for multi-hop on contracts/manuals
5. **Google Sign-In only** — optional; no passwords / API-key auth
6. **Auto Docling** — hard layouts escalate to Docling; simple PDFs stay on the fast path

## Stack

| Layer | Choice |
|---|---|
| Frontend | Next.js 15 + Tailwind |
| Backend | FastAPI + structured logging |
| Auth | Google Identity Services → session JWT |
| Parse | `PDF_PARSER=auto` · pymupdf4llm · Docling (hard) · vision · Whisper · HTML |
| Chunking | Structure-aware + contextual prefix |
| Embeddings | fastembed `BAAI/bge-small-en-v1.5` (local) |
| Retrieval | Hybrid → RRF → rerank → GraphRAG expand → agentic 2nd hop |
| Eval | LLM-judge + optional RAGAS + `/eval/tune` threshold sweep |
| Vectors | On-disk Qdrant / Compose |
| Relational | SQLite locally · Postgres in Docker |
| LLM | Groq → Gemini fallback |

## Quick start (no Docker)

### 1. Backend (use a venv — do not install into global Python)

```bash
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1     # Windows PowerShell
pip install -e ".[ingestion]"
# optional: pip install -e ".[advanced]"   # Docling
# optional: pip install -e ".[eval]"       # RAGAS
copy ..\.env.example .env
# set GROQ_API_KEY=...
uvicorn app.main:app --reload --port 8000
```

> Always activate `.venv` before `pip install` / `uvicorn`. That keeps packages
> out of your global Python and avoids version conflicts with other projects.

Google Sign-In: see [docs/GOOGLE_AUTH.md](docs/GOOGLE_AUTH.md).

API docs: [http://localhost:8000/docs](http://localhost:8000/docs)

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Deploy (production)

See **[docs/DEPLOY.md](docs/DEPLOY.md)** for the full guide.

**Recommended:** VPS + `docker-compose.prod.yml` + Caddy HTTPS.

```bash
cp .env.production.example .env.production
# edit DOMAIN, secrets, GROQ_API_KEY, GOOGLE_CLIENT_ID
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
```

Local full stack (no HTTPS):

```bash
docker compose up --build
```

Google Sign-In: [docs/GOOGLE_AUTH.md](docs/GOOGLE_AUTH.md).

## Eval & threshold tuning

With a ready document scoped in the UI:

- **Run eval** — held-out Q&A (`backend/app/eval/test_qa_sets/example.json`) → faithfulness / refusal / context metrics (+ RAGAS if installed)
- **Tune threshold** — sweeps `RELEVANCE_THRESHOLD` and prints a recommendation

CLI:

```bash
cd backend
python -m app.eval.ragas_eval --document-id <UUID>
python -m app.eval.ragas_eval --document-id <UUID> --tune
```

## API (mandatory clean frontend↔backend contract)

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/auth/google` | Exchange Google ID token → session JWT |
| `GET` | `/auth/me` | Auth status |
| `GET` | `/auth/config` | Public `{auth_enabled, google_client_id}` |
| `POST` | `/documents/upload` | PDF / image / video / text → async ingest |
| `POST` | `/documents/from-url` | Ingest a public web page |
| `POST` | `/documents/{id}/reingest` | Re-index without model retraining |
| `GET` | `/documents/{id}/status` | Parse/chunk/embed progress |
| `GET` | `/documents` | List knowledge-base docs |
| `GET` | `/documents/{id}/file` | Serve original media (`?token=` when auth on) |
| `DELETE` | `/documents/{id}` | Remove doc + vectors + graph |
| `POST` | `/chat/sessions` | Create session (conversation memory) |
| `POST` | `/chat/{id}/message` | Ask (SSE or JSON) |
| `GET` | `/chat/{id}/history` | Session history |
| `POST` | `/eval/run` | Run held-out eval |
| `POST` | `/eval/tune` | Sweep relevance thresholds |
| `GET` | `/eval/summary` | Gate-failure observability |
| `GET` | `/docs` | OpenAPI / Swagger |

## Feature checklist

| Feature | Status |
|---|---|
| Intelligent grounded retrieval | Yes — hybrid + gates |
| Conversation memory (session) | Yes — history → query rewrite |
| Multi-format KB | PDF, image, video/audio, text, URL |
| KB updates without retraining | `POST …/reingest` replaces vectors only |
| Auth | Google Sign-In only (`AUTH_ENABLED`) |
| API documentation | FastAPI `/docs` + `/redoc` |
| Backend logger | Structured stdout logger |
| Citation UX | Page jump + snippet highlight in PDF text layer |
| Docling for hard layouts | `PDF_PARSER=auto` |
| Eval + threshold tune | UI buttons + `/eval/*` |

## Grounding contract

> Answer **only** from retrieved context. If insufficient:  
> `I don't have enough context in the document to answer that.`

## License

MIT — add when you publish.
