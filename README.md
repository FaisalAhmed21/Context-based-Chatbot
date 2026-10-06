# OmniCentricBot: Ultra-Fast Grounded RAG Platform

Welcome to **OmniCentricBot**, a high-performance, Context-Grounded Multimodal Retrieval-Augmented Generation (RAG) platform. 

This project allows you to build a searchable knowledge base by uploading PDFs, images, text files, and web page URLs. The bot answers questions **only** using the context provided in your uploaded documents, and is explicitly designed to refuse to answer rather than guess when the context is insufficient.

---

## Architecture & Data Lifecycle (How It Works)

OmniCentricBot is designed around a modern, extremely fast, and cost-efficient pipeline. Here is exactly what happens from the moment you upload a file to the moment the chatbot answers a question.

### 1. Document Ingestion & Parsing
When a file is uploaded, it is routed to a specialized parser based on its MIME type:
* **PDFs (`PyMuPDF4LLM`)**: Traditional PDF parsers destroy formatting, which confuses LLMs. We use `PyMuPDF4LLM` because it preserves tables, headers, and reading order, outputting perfectly structured Markdown.
* **Images (`OCR.space API`)**: Because many cloud providers (like FastAPI Cloud, Render, or Vercel) restrict installing C++ applications like Tesseract directly onto their servers, we securely send images to the **OCR.space API**. This outsources the heavy C++ OCR extraction to their servers for free, instantly returning the extracted text.
* **Web Pages (`BeautifulSoup`)**: Scrapes the raw HTML and cleans it into readable text.

### 2. Chunking & Local Embedding
Once the document is converted into raw text, it enters the **Unified Ingestion Flow**:
* **Chunking**: The text is split into logical segments (approx. 500-1000 tokens) so the search engine can find precise paragraphs rather than entire books.
* **Local Embedding (`FastEmbed`)**: Instead of paying for OpenAI or Cohere embeddings, the backend uses `FastEmbed` to locally run the `BAAI/bge-small-en-v1.5` model. This converts the text chunks into mathematical vectors entirely on your server's CPU, keeping data private and free.

### 3. Vector Storage & Hybrid Search
* **Qdrant Vector DB**: The vectors are saved into Qdrant. Qdrant was chosen because it supports **Hybrid Search**. When you ask a question, Qdrant searches using *Dense Vectors* (understanding the semantic meaning of your question) AND *Sparse BM25* (finding exact keyword matches). 
* **Reciprocal Rank Fusion (RRF)**: The results from the semantic search and the keyword search are mathematically merged to find the absolute best chunks.
* **Cross-Encoder Reranking**: The top results are passed through a local Cross-Encoder model that acts as a final judge, re-scoring them to guarantee the most relevant context is sent to the LLM.

### 4. Generation & Streaming
* **The LLM Engine (`Groq` + `Qwen`)**: The retrieved text is injected into a prompt and sent to Groq. Groq was chosen because its LPU (Language Processing Unit) architecture streams answers back at hundreds of tokens per second—making the chatbot feel instant. We use the `qwen/qwen3.8-27b` model for its high reasoning capabilities.
* **The Fallback (`Google Gemini`)**: If Groq hits a free-tier rate limit, the backend automatically intercepts the error and seamlessly falls back to `gemini-3.8-flash`. This ensures your chatbot never crashes due to traffic.
* **Groundedness / Anti-Hallucination**: The prompt explicitly forbids the LLM from using outside knowledge. If the answer isn't in the provided chunks, the LLM will output a strict refusal.

---

## Tech Stack (What Is Used & Why)

| Layer | Technology | Why We Chose It |
|---|---|---|
| **Frontend** | Next.js 16 (React), TailwindCSS, React-PDF | Server-Side Rendering (SSR) for speed, beautiful modern UI, and integrated PDF viewing for citations. |
| **Backend** | FastAPI (Python 3.10+), Uvicorn | Asynchronous, extremely fast, and Python-native (perfect for AI integrations). |
| **Authentication**| Google Identity Services (OAuth2) | Stateless JWTs mean no managing passwords or user tables. |
| **Vector DB** | Qdrant (Cloud in Prod, Local in Dev) | State-of-the-art hybrid search (Dense + BM25) with a very generous free cloud tier. |
| **Relational DB** | SQLite (Dev) / PostgreSQL (Prod) | Stores chat history, document metadata, and user sessions. |
| **Embeddings** | `FastEmbed` (`bge-small-en-v1.5`) | Runs locally on CPU without needing a GPU. Extremely fast and cost-free. |
| **LLM Engine** | Groq (`qwen/qwen3.8-27b`) | Unbeatable inference speed for instant response streaming. |
| **Fallback LLM** | Google Gemini (`gemini-3.8-flash`) | Acts as a reliable safety net if Groq gets rate-limited. |
| **Image OCR** | OCR.space API | Bypasses restrictive cloud environments that block C++ OS installations. |
| **Document Parsing**| PyMuPDF4LLM | Preserves Markdown structure and tables better than traditional PDF extractors. |

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
GEMINI_API_KEY=your_gemini_key

# Models
LLM_PROVIDER=groq
LLM_MODEL=qwen/qwen3.8-27b
LLM_FALLBACK_MODEL=gemini-3.8-flash

# Qdrant Cloud
QDRANT_URL=your_qdrant_url
QDRANT_API_KEY=your_qdrant_api_key

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
