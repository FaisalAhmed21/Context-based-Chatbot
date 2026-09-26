# OmniCentricBot: Grounded RAG Platform

Welcome to **OmniCentricBot**, a state-of-the-art Context-Grounded Multimodal Retrieval-Augmented Generation (RAG) platform. 

This project allows you to build a highly intelligent, multimodal knowledge base by uploading PDFs, images, text files, and web page URLs. The bot strictly answers questions **only** using the context provided in your uploaded documents, and is explicitly designed to refuse to answer rather than hallucinate if the context is insufficient.

## What Makes This Exceptional?

1. **Strict Context Grounding (Zero Hallucination)**
   Unlike standard LLM chatbots, OmniCentricBot employs strict relevance gating and self-RAG groundedness checks. If the answer isn't in your documents, the bot honestly refuses to guess.
2. **Multimodal Capabilities**
   The platform processes far more than just text. It parses complex PDF layouts, analyzes images, and scrapes web pages, unifying them into a single queryable vector space.
3. **Advanced Hybrid Retrieval Pipeline**
   We combine Dense Vector Search (using `fastembed` Qdrant) with sparse BM25 keyword matching. Results are merged using Reciprocal Rank Fusion (RRF) and then passed through a Cross-Encoder Reranker to guarantee high-precision context retrieval.
4. **Interactive Citation UX**
   The frontend doesn't just give you an answer; it proves it. Clicking a citation jumps the integrated PDF viewer directly to the exact page and highlights the relevant snippet that informed the answer.
5. **Dynamic Evaluations & Auto-Tuning**
   Built-in evaluation endpoints allow you to run automated RAGAS-style metrics on held-out QA sets, and even automatically sweep and recommend optimal relevance thresholds for your specific dataset.

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Frontend** | Next.js 16 (React 19), TailwindCSS, React-PDF |
| **Backend** | FastAPI (Python 3.10+), Uvicorn, SQLAlchemy |
| **Authentication**| Google Identity Services (OAuth2) with stateless JWTs |
| **Vector DB** | Qdrant (Local on-disk or Cloud) |
| **Relational DB** | SQLite (Local dev) / PostgreSQL (Production) |
| **Embeddings** | `BAAI/bge-small-en-v1.5` (via FastEmbed) |
| **LLM Engine** | Groq (GPT-OSS-20B) / Gemini fallback |
| **Document Parsing**| PyMuPDF4LLM |

---

## Production Deployment (Vercel & FastAPI Cloud)

This project is fully optimized for serverless and cloud deployments.

### 1. Backend (FastAPI Cloud)
The backend runs on FastAPI Cloud. 
- API Base URL: `https://context-based-chatbot.fastapicloud.dev`
- API Documentation: `https://context-based-chatbot.fastapicloud.dev/docs`

Ensure the backend environment variables are set in your FastAPI Cloud dashboard:
* `GROQ_API_KEY`: Your Groq API key for the LLM.
* `AUTH_ENABLED`: `true`
* `GOOGLE_CLIENT_ID`: Your Google OAuth client ID.

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
   .\.venv\Scripts\Activate.ps1
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

OmniCentricBot supports secure authentication exclusively via Google Sign-In. No passwords or custom registration flows are required.

When enabled, documents and chat sessions are strictly scoped to the user who created them.

---

## API Reference

The backend exposes a clean, documented REST API. For full schema details, visit the `/docs` endpoint on your backend URL. 

### Core Endpoints

* **Documents**
  * `POST /documents/upload` - Upload and asynchronously ingest a media file (PDF, Image, Text).
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

# Sweep the relevance threshold hyperparameter and get an optimal recommendation
python -m app.eval.ragas_eval --document-id <LOCAL_UUID> --tune
```
