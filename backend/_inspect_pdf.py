import asyncio

import fitz
from sqlalchemy import select

from app.db.models import Document
from app.db.session import SessionLocal


async def main():
    async with SessionLocal() as s:
        d = (await s.execute(select(Document))).scalars().first()
        path = d.storage_path
        print(path)
    doc = fitz.open(path)
    print("pages", len(doc))
    for i in range(len(doc)):
        p = doc[i]
        text = p.get_text("text")
        imgs = p.get_images()
        blocks = p.get_text("blocks")
        print(
            "page",
            i + 1,
            "chars",
            len(text.strip()),
            "images",
            len(imgs),
            "blocks",
            len(blocks),
        )
        print(repr(text[:400]))
    doc.close()


if __name__ == "__main__":
    asyncio.run(main())
