"""Create a grounded test corpus: PDF + image + URL text file for accuracy eval."""
from __future__ import annotations

from pathlib import Path

import fitz

OUT = Path(__file__).resolve().parent / "test_fixtures"
OUT.mkdir(parents=True, exist_ok=True)


def make_pdf() -> Path:
    doc = fitz.open()
    page = doc.new_page()
    text = """OmniCentricBot Knowledge Brief
Version: 2.4.1
Published: 12 March 2025
Author: Dr. Lena Ortiz
Organization: Northwind Applied AI Lab

1. Mission
OmniCentricBot is a context-grounded multimodal RAG assistant. It answers questions
only from uploaded documents and refuses when evidence is missing.

2. Core Numbers
- Embedding model dimension: 384
- Default relevance threshold: 0.35
- Maximum upload size: 50 MB
- Whisper free-tier media limit: 25 MB
- Supported image formats: PNG, JPG, WEBP, GIF, BMP

3. Architecture Overview
Retrieval uses hybrid search: dense vectors in Qdrant plus BM25 keyword matching,
fused with Reciprocal Rank Fusion (RRF), then a cross-encoder reranker
(Xenova/ms-marco-MiniLM-L-6-v2). Generation defaults to Groq model openai/gpt-oss-20b
with Gemini as fallback.

4. Safety Policy
The assistant must not invent phone numbers, home addresses, or medical dosages
that are absent from the source documents. If asked for the capital of France and
that fact is not in the documents, it must refuse.

5. Project Codename
Internal codename: Project Harborlight
Primary contact email: harborlight@northwind-lab.example
Launch city: Portland
"""
    page.insert_text((50, 50), text, fontsize=11)
    path = OUT / "omnicentric_knowledge_brief.pdf"
    doc.save(path)
    doc.close()
    return path


def make_image() -> Path:
    # Render a second page as an image so vision captioning is exercised.
    doc = fitz.open()
    page = doc.new_page(width=600, height=400)
    page.insert_text(
        (40, 40),
        "SENSOR CARD\n"
        "Device: Harborlight Temp Probe HL-7\n"
        "Operating range: -20C to 85C\n"
        "Battery life: 14 days\n"
        "Firmware: 1.9.3\n"
        "Calibration date: 2025-01-08\n",
        fontsize=16,
    )
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
    path = OUT / "sensor_card.png"
    pix.save(path)
    doc.close()
    return path


def make_url_snapshot() -> Path:
    # Local HTML-like text that the web/text loader can ingest after URL fetch simulation.
    # We will also ingest a real public URL via the API.
    path = OUT / "notes.txt"
    path.write_text(
        "Meeting Notes — Harborlight Standup\n"
        "Date: 2025-02-18\n"
        "Attendees: Lena Ortiz, Sam Park, Mei Chen\n"
        "Decision: Ship hybrid retrieval first; graph expansion is optional.\n"
        "Budget approved: $42,000 for Q2 evaluation hardware.\n"
        "Next milestone: citation UX polish by April 5, 2025.\n",
        encoding="utf-8",
    )
    return path


if __name__ == "__main__":
    pdf = make_pdf()
    img = make_image()
    notes = make_url_snapshot()
    print(pdf)
    print(img)
    print(notes)
