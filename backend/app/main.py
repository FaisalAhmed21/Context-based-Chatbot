

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

app = FastAPI(
    title="Grounded — RAG Chatbot API",
    description=(
        "Context-grounded multimodal QA: upload PDF / image / video / text / web pages, "
        "ask questions, get answers **only** from your knowledge base — or an explicit "
        "refusal when context is insufficient.\n\n"
        "## Pipeline\n"
        "1. Ingestion: parse → structure-aware chunk → embed → Qdrant (+ optional GraphRAG)\n"
        "2. Retrieval: hybrid dense+BM25 → RRF → cross-encoder rerank → optional agentic hop\n"
        "3. Generation: grounded prompt + relevance gate + Self-RAG groundedness check\n\n"
        "## Auth\n"
        "Optional Google Sign-In only. Set `AUTH_ENABLED=true` + `GOOGLE_CLIENT_ID`, "
        "then `POST /auth/google` with the GIS credential and send "
        "`Authorization: Bearer <access_token>`.\n\n"
        "Interactive docs: `/docs` (Swagger) · `/redoc`"
    ),
    version="0.3.0",
    lifespan=lifespan,
    contact={"name": "Grounded RAG"},
    license_info={"name": "MIT"},
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

