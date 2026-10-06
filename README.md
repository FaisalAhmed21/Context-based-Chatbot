# OmniCentricBot: Ultra-Fast Grounded RAG Platform

Welcome to **OmniCentricBot**, a high-performance, Context-Grounded Multimodal Retrieval-Augmented Generation (RAG) platform. 

This project allows you to build a searchable knowledge base by uploading PDFs, images, text files, and web page URLs. The bot answers questions **only** using the context provided in your uploaded documents, and is explicitly designed to refuse to answer rather than guess when the context is insufficient.

## Key Features

1. **Context-Grounded Answers (Refuses Instead of Guessing)**
   Rather than answering from the model's general knowledge, OmniCentricBot uses relevance gating to keep answers tied directly to your documents. If the answer isn't in your documents, the bot explicitly refuses instead of guessing or hallucinating.
2. **Lightning-Fast Instant Streaming**
   By disabling the secondary groundedness auditor, the chatbot begins streaming its answer to the screen in milliseconds, ensuring a snappy ChatGPT-like user experience while relying on the primary prompt for accuracy.
3. **Advanced Document & Image Parsing**
   The platform processes files specifically based on their type:
   - **PDFs:** Parsed into structured Markdown using **PyMuPDF4LLM**.
   - **Images:** Sent to the free **OCR.space Tesseract API** to extract text, bypassing cloud OS C++ restrictions and requiring absolutely no paid LLM vision tokens.
4. **Unified Ingestion Flow**
   Whether the raw text comes from a PDF, an image, or a text file, it all passes through the exact same downstream flow: 
   - Chunked into logical segments.
   - Embedded using local **FastEmbed** (`BAAI/bge-small-en-v1.5`).
   - Indexed instantly into a **Qdrant** Vector Database.
5. **Interactive Citation UX**
   The frontend doesn't just give you an answer; it shows its sources. Clicking a citation jumps the integrated PDF viewer directly to the exact page and highlights the relevant snippet that informed the answer.

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Frontend** | Next.js 16 (React 19), TailwindCSS, React-PDF |
| **Backend** | FastAPI (Python 3.10+), Uvicorn, SQLAlchemy |
| **Authentication**| Google Identity Services (OAuth2) with stateless JWTs |
| **Vector DB** | Qdrant (Local on-disk) |
| **Relational DB** | SQLite (Local dev) / PostgreSQL (Production) |
| **Embeddings** | `BAAI/bge-small-en-v1.5` (via Local FastEmbed) |
| **LLM Engine** | Groq (`qwen/qwen3.8-27b`) |
| **Image OCR** | OCR.space API (Tesseract Engine 2) |
| **Document Parsing**| PyMuPDF4LLM |

---

## Production Deployment (Vercel & FastAPI Cloud)

This project is deployed on Vercel (frontend) and FastAPI Cloud (backend).

### 1. Backend (FastAPI Cloud)
The backend runs on FastAPI Cloud. 
- API Base URL: `https://context-based-chatbot.fastapicloud.dev`
- API Documentation: `https://context-based-chatbot.fastapicloud.dev/docs`

Ensure the following critical backend environment variables are set in your FastAPI Cloud dashboard:
```env
# API Keys
GROQ_API_KEY=your_groq_key

# Models
LLM_PROVIDER=groq
LLM_MODEL=qwen/qwen3.8-27b

# Disable the slow groundedness auditor to guarantee instant streaming
GROUNDEDNESS_ENABLED=false

# Google Auth
AUTH_ENABLED=true
GOOGLE_CLIENT_ID=your_client_id
```

### 2. Frontend (Vercel)
The frontend is deployed on Vercel. 
Ensure the following environment variables are set in your Vercel dashboard:
* `NEXT_PUBLIC_API_URL`: `https://context-based-chatbot.fastapicloud.dev`
* `NEXT_PUBLIC_GOOGLE_CLIENT_ID`: Your Google OAuth client ID.

---

## Local Development (Optional)

If you wish to run the project locally for development purposes:

1. **Backend**:
   ```bash
   cd backend
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1   # Windows PowerShell; on macOS/Linux: source .venv/bin/activate
   pip install -e .
   cp ../.env.example .env
   uvicorn app.main:app --reload --port 8000
   ```
   *(Local API Docs will be available at `http://127.0.0.1:8000/docs`)*

2. **Frontend**:
   ```bash
   cd frontend
   npm install
   npm run dev
   ```
   *(Local UI will be available at `http://127.0.0.1:3000`)*

---

## Authentication (Google Sign-In)

OmniCentricBot uses Google Sign-In (OAuth2) for authentication, with stateless JWT sessions. No passwords or custom registration flows are required.

When enabled, documents and chat sessions are strictly scoped to the user who created them.

---

## API Reference

The backend exposes a clean, documented REST API. For full schema details, visit the `/docs` endpoint on your backend URL. 

### Core Endpoints

* **Documents**
  * `POST /documents/upload` - Upload and asynchronously ingest a media file (PDF, Image, Text).
  * `POST /documents/from-url` - Scrape and ingest a public webpage.
  * `POST /documents/{id}/reingest` - Re-index a document without full retraining.
  * `GET /documents` - List all documents in the user's knowledge base.
  * `GET /documents/{id}/status` - Check the processing status of a document.
  * `GET /documents/{id}/file` - Retrieve the original media file.
  * `DELETE /documents/{id}` - Delete a document and its vectors (cascade).

* **Chat Sessions**
  * `POST /chat/sessions` - Create a new conversation memory scoped to specific documents.
  * `GET /chat/sessions` - List all active chat sessions for the current user.
  * `POST /chat/{id}/message` - Send a prompt and receive a streamed (SSE) or JSON response.
  * `GET /chat/{id}/history` - Fetch the full history of a chat session.
  * `DELETE /chat/{id}` - Delete a chat session.

* **Auth**
  * `GET /auth/config` - Fetch public authentication configuration.
  * `POST /auth/google` - Exchange a Google ID token for a stateless session JWT.
  * `GET /auth/me` - Check current authentication status and user details.
  * `POST /auth/logout` - Client-side logout helper.

* **Evaluations**
  * `GET /eval/summary` - Fetch a summary of recent evaluation logs and metrics.
  * `POST /eval/run` - Trigger an evaluation run asynchronously.
  * `POST /eval/tune` - Sweep hyperparameters and tune relevance thresholds.

---

## Evaluations & Auto-Tuning

OmniCentricBot includes a built-in suite for evaluating RAG performance against held-out datasets (Faithfulness, Context Precision, Refusal Rates).

### Prerequisites for Evaluation
1. **Install Eval Dependencies:** You must install the `[eval]` extra:
   ```bash
   cd backend
   pip install -e ".[eval]"
   ```
2. **Use a Local Document ID:** If you are running the evaluation script locally, you **must** use a Document ID that exists in your local `qdrant_data` database. You cannot use a Document ID from your production FastAPI Cloud deployment! Start your local frontend and backend, upload a test document to `localhost:3000`, grab the local Document ID from the URL, and use that.
3. **Stop the Backend Server:** Qdrant local uses a file lock on the `qdrant_data` folder. You cannot run the background `uvicorn` server and the evaluation script at the same time. Stop the local backend (`Ctrl+C`) before running the script. *(If it crashed, you may need to manually delete the hidden `qdrant_data/.lock` file).*

### Running Evaluations
You can run evaluations via the API or CLI:
```bash
cd backend
# Run a standard evaluation on a document
python -m app.eval.ragas_eval --document-id <LOCAL_UUID>

# Sweep the relevance threshold hyperparameter and get a recommended value
python -m app.eval.ragas_eval --document-id <LOCAL_UUID> --tune
```
