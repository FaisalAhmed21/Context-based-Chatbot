# OmniCentricBot: Grounded RAG Platform

Welcome to **OmniCentricBot**, a state-of-the-art Context-Grounded Multimodal Retrieval-Augmented Generation (RAG) platform. 

This project allows you to build a highly intelligent, multimodal knowledge base by uploading PDFs, images, videos, text files, and web page URLs. The bot strictly answers questions **only** using the context provided in your uploaded documents, and is explicitly designed to refuse to answer rather than hallucinate if the context is insufficient.

## 🌟 What Makes This Exceptional?

1. **Strict Context Grounding (Zero Hallucination)**
   Unlike standard LLM chatbots, OmniCentricBot employs strict relevance gating and self-RAG groundedness checks. If the answer isn't in your documents, the bot honestly refuses to guess.
2. **Multimodal Capabilities**
   The platform processes far more than just text. It parses complex PDF layouts (via Docling), analyzes images, transcribes audio/video (via Whisper), and scrapes web pages, unifying them into a single queryable vector space.
3. **Advanced Hybrid Retrieval Pipeline**
   We combine Dense Vector Search (using `fastembed` Qdrant) with sparse BM25 keyword matching. Results are merged using Reciprocal Rank Fusion (RRF) and then passed through a Cross-Encoder Reranker to guarantee high-precision context retrieval.
4. **Interactive Citation UX**
   The frontend doesn't just give you an answer; it proves it. Clicking a citation jumps the integrated PDF viewer directly to the exact page and highlights the relevant snippet that informed the answer.
5. **Dynamic Evaluations & Auto-Tuning**
   Built-in evaluation endpoints allow you to run automated RAGAS-style metrics on held-out QA sets, and even automatically sweep and recommend optimal relevance thresholds for your specific dataset.

---

## 🛠 Tech Stack

| Layer | Technology |
|---|---|
| **Frontend** | Next.js 15 (React 19), TailwindCSS, React-PDF, Framer Motion |
| **Backend** | FastAPI (Python 3.11+), Uvicorn, SQLAlchemy |
| **Authentication**| Google Identity Services (OAuth2) with stateless JWTs |
| **Vector DB** | Qdrant (Local on-disk or Cloud) |
| **Relational DB** | SQLite (Local dev) / PostgreSQL (Production) |
| **Embeddings** | `BAAI/bge-small-en-v1.5` (via FastEmbed) |
| **LLM Engine** | Groq (Llama 3) / Gemini fallback |
| **Document Parsing**| PyMuPDF4LLM, Docling (Complex PDFs), Whisper (Audio) |

---

## 🚀 Quick Start Guide (Local Development)

You can run the entire stack locally without Docker for rapid development.

### 1. Backend Setup

It is highly recommended to use a Python virtual environment to prevent dependency conflicts.

```bash
cd backend
python -m venv .venv

# Activate the virtual environment:
# On Windows:
.\.venv\Scripts\Activate.ps1
# On macOS/Linux:
source .venv/bin/activate

# Install the core backend and ingestion dependencies
pip install -e ".[ingestion]"

# Duplicate the example environment file
cp ../.env.example .env
```

**Environment Configuration (`.env`)**
Open `.env` and configure your API keys:
* `GROQ_API_KEY`: Your Groq API key for the LLM.
* `AUTH_ENABLED`: Set to `false` for local testing, or `true` if you have configured a `GOOGLE_CLIENT_ID`.

**Start the Server**
```bash
uvicorn app.main:app --reload --port 8000
```
Your backend is now running! View the interactive OpenAPI documentation at [http://localhost:8000/docs](http://localhost:8000/docs).

### 2. Frontend Setup

In a new terminal window:

```bash
cd frontend
npm install
```

**Environment Configuration (`.env`)**
Create a `.env` file in the `frontend` directory if you need to override the API URL or provide a Google Client ID for frontend auth rendering.

**Start the Client**
```bash
npm run dev
```
Open [http://localhost:3000](http://localhost:3000) to view the application.

---

## 🔒 Authentication (Google Sign-In)

OmniCentricBot supports optional, secure authentication exclusively via Google Sign-In. No passwords or custom registration flows are required.

To enable authentication:
1. Go to the [Google Cloud Console](https://console.cloud.google.com/) and create OAuth 2.0 Client credentials.
2. Add your frontend domain (e.g., `http://localhost:3000`) to the **Authorized JavaScript origins**.
3. In your backend `.env`, set:
   ```env
   AUTH_ENABLED=true
   GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
   ```
4. In your frontend `.env`, set:
   ```env
   NEXT_PUBLIC_GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
   ```

When enabled, documents and chat sessions are strictly scoped to the user who created them.

---

## 🚢 Production Deployment

For production, the application is fully containerized. We recommend using Docker Compose with a reverse proxy like Caddy or Nginx for HTTPS.

1. Prepare your production environment file:
   ```bash
   cp .env.production.example .env.production
   ```
2. Edit `.env.production` to include your domain, secure random secrets, API keys, and Postgres credentials.
3. Build and launch the stack in detached mode:
   ```bash
   docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
   ```

*(Note: FastAPI Cloud and Vercel are also supported out-of-the-box for serverless deployments).*

---

## 📡 API Reference

The backend exposes a clean, documented REST API. For full schema details, visit the `/docs` endpoint on your running backend. 

### Core Endpoints

* **Documents**
  * `POST /documents/upload` - Upload and asynchronously ingest a media file.
  * `POST /documents/from-url` - Scrape and ingest a public webpage.
  * `GET /documents` - List all documents in the user's knowledge base.
  * `GET /documents/{id}/file` - Retrieve the original media file.
  * `DELETE /documents/{id}` - Safely cascade delete a document and its vectors.

* **Chat Sessions**
  * `POST /chat/sessions` - Create a new conversation memory scoped to specific documents.
  * `POST /chat/{id}/message` - Send a prompt and receive a streamed (SSE) or JSON response.
  * `GET /chat/{id}/history` - Fetch the full history of a chat session.
  * `DELETE /chat/{id}` - Delete a chat session.

* **Auth**
  * `POST /auth/google` - Exchange a Google ID token for a stateless session JWT.

---

## 🧪 Evaluations & Auto-Tuning

OmniCentricBot includes a built-in suite for evaluating RAG performance against held-out datasets (Faithfulness, Context Precision, Refusal Rates).

You can run evaluations via the API or CLI:
```bash
cd backend
# Run a standard evaluation on a document
python -m app.eval.ragas_eval --document-id <UUID>

# Sweep the relevance threshold hyperparameter and get an optimal recommendation
```
