"""Run 20 mixed in/out-of-context questions against the local API and score accuracy."""
from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

API = "http://127.0.0.1:8000"
FIXTURES = Path(__file__).resolve().parent / "test_fixtures"
QUESTION_DELAY_SEC = 12.0
PROVIDER_ERROR_MARKERS = (
    "All LLM providers failed",
    "Groq error 429",
    "Gemini error 429",
    "rate_limit",
)

REFUSAL_HINTS = (
    "don't have enough context",
    "do not have enough context",
    "insufficient context",
    "not enough information",
    "not enough context",
)


def is_refusal(text: str) -> bool:
    t = (text or "").strip().lower()
    return any(h in t for h in REFUSAL_HINTS)


def wait_ready(client: httpx.Client, doc_id: str, timeout: float = 300.0) -> dict:
    start = time.time()
    while time.time() - start < timeout:
        doc = client.get(f"{API}/documents/{doc_id}/status").json()
        if doc["status"] == "ready":
            return doc
        if doc["status"] == "failed":
            raise RuntimeError(f"Ingest failed for {doc_id}: {doc.get('error_message')}")
        time.sleep(1.5)
    raise TimeoutError(doc_id)


def upload_file(client: httpx.Client, path: Path) -> dict:
    with path.open("rb") as f:
        files = {"file": (path.name, f)}
        doc = client.post(f"{API}/documents/upload", files=files).json()
    return wait_ready(client, doc["id"])


def ingest_url(client: httpx.Client, url: str, title: str | None = None) -> dict:
    doc = client.post(
        f"{API}/documents/from-url",
        json={"url": url, "title": title},
    ).json()
    return wait_ready(client, doc["id"])


def ask(client: httpx.Client, session_id: str, question: str, document_ids: list[str]) -> dict:
    resp = client.post(
        f"{API}/chat/{session_id}/message",
        json={
            "content": question,
            "document_ids": document_ids,
            "stream": False,
        },
        timeout=180.0,
    )
    resp.raise_for_status()
    return resp.json()


def contains_any(text: str, needles: list[str]) -> bool:
    lower = text.lower()
    return any(n.lower() in lower for n in needles)


def is_provider_error(text: str) -> bool:
    t = text or ""
    return any(m in t for m in PROVIDER_ERROR_MARKERS)


def latest_ready(client: httpx.Client, filename: str) -> dict | None:
    docs = client.get(f"{API}/documents").json()
    ready = [d for d in docs if d.get("filename") == filename and d.get("status") == "ready"]
    return ready[-1] if ready else None


def main() -> None:
    client = httpx.Client(timeout=180.0)
    health = client.get(f"{API}/health").json()
    assert health.get("status") == "ok", health

    reuse = __import__("os").environ.get("EVAL_REUSE_DOCS", "1") != "0"
    print("Preparing fixtures (reuse=%s)…" % reuse)
    if reuse:
        pdf = latest_ready(client, "omnicentric_knowledge_brief.pdf")
        img = latest_ready(client, "sensor_card.png")
        notes = latest_ready(client, "notes.txt")
        wiki = latest_ready(client, "Wikipedia RAG")
        if not pdf:
            pdf = upload_file(client, FIXTURES / "omnicentric_knowledge_brief.pdf")
        if not img:
            img = upload_file(client, FIXTURES / "sensor_card.png")
        else:
            img = client.post(f"{API}/documents/{img['id']}/reingest").json()
            img = wait_ready(client, img["id"], timeout=300.0)
        if not notes:
            notes = upload_file(client, FIXTURES / "notes.txt")
        if not wiki:
            wiki = ingest_url(
                client,
                "https://en.wikipedia.org/wiki/Retrieval-augmented_generation",
                title="Wikipedia RAG",
            )
    else:
        pdf = upload_file(client, FIXTURES / "omnicentric_knowledge_brief.pdf")
        img = upload_file(client, FIXTURES / "sensor_card.png")
        notes = upload_file(client, FIXTURES / "notes.txt")
        wiki = ingest_url(
            client,
            "https://en.wikipedia.org/wiki/Retrieval-augmented_generation",
            title="Wikipedia RAG",
        )

    doc_ids = [pdf["id"], img["id"], notes["id"], wiki["id"]]

    print("Docs:", [(d, client.get(f"{API}/documents/{d}/status").json()["filename"]) for d in doc_ids])

    cases = [
        # --- In-context (PDF brief) ---
        {
            "q": "What is the version number of the OmniCentricBot Knowledge Brief?",
            "expect_refuse": False,
            "must_include": ["2.4.1"],
            "source": "pdf",
        },
        {
            "q": "Who authored the Knowledge Brief?",
            "expect_refuse": False,
            "must_include": ["Lena Ortiz"],
            "source": "pdf",
        },
        {
            "q": "What is the default relevance threshold?",
            "expect_refuse": False,
            "must_include": ["0.35"],
            "source": "pdf",
        },
        {
            "q": "What embedding dimension is used?",
            "expect_refuse": False,
            "must_include": ["384"],
            "source": "pdf",
        },
        {
            "q": "What is the internal project codename?",
            "expect_refuse": False,
            "must_include": ["Harborlight"],
            "source": "pdf",
        },
        {
            "q": "Which city is listed as the launch city?",
            "expect_refuse": False,
            "must_include": ["Portland"],
            "source": "pdf",
        },
        {
            "q": "What contact email is listed for Harborlight?",
            "expect_refuse": False,
            "must_include": ["harborlight@northwind-lab.example"],
            "source": "pdf",
        },
        {
            "q": "What is the maximum upload size mentioned?",
            "expect_refuse": False,
            "must_include": ["50"],
            "source": "pdf",
        },
        # --- In-context (image sensor card) ---
        {
            "q": "What is the firmware version on the Harborlight Temp Probe?",
            "expect_refuse": False,
            "must_include": ["1.9.3"],
            "source": "image",
        },
        {
            "q": "What is the operating temperature range of the HL-7 probe?",
            "expect_refuse": False,
            "must_include": ["-20", "85"],
            "source": "image",
        },
        {
            "q": "When was the sensor calibrated?",
            "expect_refuse": False,
            "must_include": ["2025-01-08", "January 8", "Jan 8", "1/8/2025", "08"],
            "source": "image",
            "any_of": True,
        },
        # --- In-context (notes txt) ---
        {
            "q": "What budget was approved in the Harborlight standup notes?",
            "expect_refuse": False,
            "must_include": ["42,000", "42000", "$42"],
            "source": "notes",
            "any_of": True,
        },
        {
            "q": "Who attended the Harborlight standup on 2025-02-18?",
            "expect_refuse": False,
            "must_include": ["Lena", "Sam", "Mei"],
            "source": "notes",
        },
        # --- In-context (Wikipedia RAG URL) ---
        {
            "q": "According to the Wikipedia page, what does RAG stand for?",
            "expect_refuse": False,
            "must_include": ["retrieval", "augmented", "generation"],
            "source": "url",
        },
        {
            "q": "What problem does retrieval-augmented generation aim to reduce according to the Wikipedia article?",
            "expect_refuse": False,
            "must_include": ["hallucin", "outdated", "external", "knowledge", "factual"],
            "source": "url",
            "any_of": True,
        },
        # --- Out-of-context (must refuse) ---
        {
            "q": "What is the capital of France?",
            "expect_refuse": True,
            "source": "ooc",
        },
        {
            "q": "Who won the 2018 FIFA World Cup?",
            "expect_refuse": True,
            "source": "ooc",
        },
        {
            "q": "What is Dr. Lena Ortiz's personal home address and phone number?",
            "expect_refuse": True,
            "source": "ooc",
        },
        {
            "q": "Write a Python function that sorts a list using quicksort.",
            "expect_refuse": True,
            "source": "ooc",
        },
        {
            "q": "What is the stock price of NVIDIA right now?",
            "expect_refuse": True,
            "source": "ooc",
        },
    ]

    results = []
    correct = 0
    for i, case in enumerate(cases, start=1):
        print(f"\n[{i}/20] {case['q']}")
        # Fresh session per question so prior turns cannot leak facts or bias refusals.
        try:
            session = client.post(
                f"{API}/chat/sessions",
                json={"document_ids": doc_ids, "title": f"Accuracy Q{i}"},
            ).json()
            sid = session["id"]
            ans = ask(client, sid, case["q"], doc_ids)
            content = ans.get("content") or ""
            if is_provider_error(content):
                time.sleep(20.0)
                ans = ask(client, sid, case["q"], doc_ids)
        except Exception as exc:
            print("  ERROR", exc)
            results.append({**case, "ok": False, "error": str(exc)})
            continue
        content = ans.get("content") or ""
        provider_err = is_provider_error(content)
        refused = (bool(ans.get("refused")) or is_refusal(content)) and not provider_err
        ok = False
        if provider_err:
            ok = False
        elif case["expect_refuse"]:
            ok = refused
        else:
            if refused:
                ok = False
            else:
                needles = case.get("must_include") or []
                if case.get("any_of"):
                    ok = contains_any(content, needles)
                else:
                    ok = all(n.lower() in content.lower() for n in needles)
        if ok:
            correct += 1
        preview = (content[:220] or "").replace("\n", " ").encode("ascii", "replace").decode("ascii")
        print(f"  refused={refused} ok={ok}\n  answer={preview}")
        results.append(
            {
                "question": case["q"],
                "source": case["source"],
                "expect_refuse": case["expect_refuse"],
                "refused": refused,
                "provider_error": provider_err,
                "ok": ok,
                "answer": content,
                "citations": ans.get("citations") or [],
            }
        )
        if i < len(cases):
            time.sleep(QUESTION_DELAY_SEC)

    summary = {
        "total": len(cases),
        "correct": correct,
        "accuracy": round(100.0 * correct / len(cases), 1),
        "in_context_correct": sum(
            1 for r in results if not r.get("expect_refuse") and r.get("ok")
        ),
        "in_context_total": sum(1 for c in cases if not c["expect_refuse"]),
        "ooc_correct": sum(1 for r in results if r.get("expect_refuse") and r.get("ok")),
        "ooc_total": sum(1 for c in cases if c["expect_refuse"]),
        "provider_errors": sum(1 for r in results if r.get("provider_error")),
        "document_ids": doc_ids,
        "results": results,
    }
    out = Path(__file__).resolve().parent / "accuracy_results.json"
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("\n==== SUMMARY ====")
    print(json.dumps({k: summary[k] for k in summary if k != "results"}, indent=2))
    print("Wrote", out)


if __name__ == "__main__":
    main()
