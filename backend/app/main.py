

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, chat, documents, eval_api
from app.config import get_settings
from app.db.session import init_db
from app.ingestion.pipeline import ensure_upload_dir
from app.logging_config import setup_logging

@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level)
    ensure_upload_dir(settings.upload_dir)
    if settings.auth_enabled and not (settings.google_client_id or "").strip():
        print(
            "[warn] AUTH_ENABLED=true but GOOGLE_CLIENT_ID is empty — "
            "Google Sign-In will fail until you set it (see docs/GOOGLE_AUTH.md)"
        )
    try:
        await init_db()
    except Exception as exc:  

        print(f"[warn] Database init skipped/failed: {exc}")
    try:
        from app.retrieval.vector_store import ensure_collection

        ensure_collection()
    except Exception as exc:  
        print(f"[warn] Qdrant init skipped/failed: {exc}")
    yield

tags_metadata = [
    {
        "name": "Auth",
        "description": "Operations for handling Google OAuth authentication and session management.",
    },
    {
        "name": "Documents",
        "description": "Upload, parse, embed, and manage multimodal knowledge base documents (PDF, image, video, URL).",
    },
    {
        "name": "Chat",
        "description": "Context-grounded RAG chat sessions, streaming responses, and message history.",
    },
    {
        "name": "Evaluations",
        "description": "RAGAS-based eval metrics, precision/recall analysis, and hyperparameter tuning.",
    },
    {
        "name": "System",
        "description": "System liveness and health check probes.",
    },
]

app = FastAPI(
    title="OmniCentricBot API",
    description=(
        "Welcome to the **OmniCentricBot** API documentation!\n\n"
        "OmniCentricBot is a highly precise, context-grounded multimodal RAG (Retrieval-Augmented Generation) "
        "chatbot engine. It ensures answers are strictly derived from your uploaded documents (PDFs, Images, "
        "Web Pages) and explicitly refuses to hallucinate when context is insufficient.\n\n"
        "### Key Capabilities\n"
        "* **Multimodal Ingestion**: Structure-aware parsing for text, URLs, and binary formats.\n"
        "* **Hybrid Retrieval**: Dense vector search (Qdrant) combined with BM25 keyword matching and Reciprocal Rank Fusion (RRF).\n"
        "* **Cross-Encoder Reranking**: Advanced relevance filtering to drop low-quality context chunks.\n"
        "* **Self-RAG Groundedness**: In-flight verification ensures the LLM's response perfectly aligns with the provided context.\n\n"
        "### Getting Started\n"
        "1. **Authenticate** via `/auth/google` to receive a JWT.\n"
        "2. **Upload** a document using `/documents/upload`.\n"
        "3. **Create** a chat session scoped to your document IDs using `/chat/sessions`.\n"
        "4. **Stream** responses using `/chat/{session_id}/message`.\n\n"
    ),
    version="latest",
    openapi_version="3.0.0",
    openapi_tags=tags_metadata,
    lifespan=lifespan,
    contact={
        "name": "OmniCentricBot Team",
        "email": "faisal.ahmed.career@gmail.com",
    },
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins or ["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(documents.router)
app.include_router(chat.router)
app.include_router(eval_api.router)

@app.get("/health", tags=["system"], summary="Liveness probe")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "grounded-rag"}

