from __future__ import annotations

import hashlib
import logging
import uuid
from pathlib import Path

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import ChunkRecord, Document, IngestionJob, JobStatus, KnowledgeBase
from app.services import chunking, embeddings, parser, vector_store as vs

log = logging.getLogger(__name__)


async def run_ingestion(job_id: str, document_id: str) -> None:
    async with SessionLocal() as db:
        job = await db.get(IngestionJob, job_id)
        doc = await db.get(Document, document_id)
        if not job or not doc:
            return
        kb = await db.get(KnowledgeBase, doc.knowledge_base_id)
        if not kb:
            job.status = JobStatus.failed.value
            job.error_message = "知识库不存在"
            await db.commit()
            return

        path = Path(doc.storage_path)
        try:
            job.status = JobStatus.parsing.value
            job.progress = 10
            await db.commit()

            _full, segments = parser.parse_document(path)
            chunks = chunking.chunk_with_headings(segments, kb.chunk_size, kb.chunk_overlap)
            if not chunks:
                job.status = JobStatus.failed.value
                job.error_message = "文档无有效文本（可能是扫描版 PDF）"
                await db.commit()
                return

            job.status = JobStatus.embedding.value
            job.progress = 40
            await db.commit()

            res_old = await db.execute(select(ChunkRecord).where(ChunkRecord.document_id == document_id))
            old_rows = list(res_old.scalars().all())
            if old_rows:
                vs.delete_ids(doc.knowledge_base_id, [r.id for r in old_rows])
                for r in old_rows:
                    await db.delete(r)
                await db.commit()

            # 批量嵌入（分批处理以监控进度）
            batch_size = 10
            total_chunks = len(chunks)
            for i in range(0, total_chunks, batch_size):
                batch_chunks = chunks[i:i+batch_size]
                texts = [c.text for c in batch_chunks]
                vectors = await embeddings.embed_texts(texts, model=kb.embedding_model_id)

                ids: list[str] = []
                metadatas: list[dict] = []
                for j, ch in enumerate(batch_chunks):
                    cid = str(uuid.uuid4())
                    ids.append(cid)
                    cr = ChunkRecord(
                        id=cid,
                        document_id=document_id,
                        chunk_index=i+j,
                        content=ch.text,
                        heading_path=ch.heading_path or "",
                        page=ch.page,
                        content_hash=hashlib.sha256(ch.text.encode()).hexdigest(),
                        chroma_id=cid,
                        embedding_model_id=kb.embedding_model_id,
                    )
                    db.add(cr)
                    meta = {
                        "kb_id": doc.knowledge_base_id,
                        "document_id": document_id,
                        "chunk_id": cid,
                        "filename": doc.filename,
                        "heading_path": ch.heading_path or "",
                        "embedding_model_id": kb.embedding_model_id,
                    }
                    if ch.page is not None:
                        meta["page"] = int(ch.page)
                    metadatas.append(meta)

                await db.commit()

                vs.add_chunks(
                    doc.knowledge_base_id,
                    ids=ids,
                    embeddings=vectors,
                    documents=texts,
                    metadatas=metadatas,
                )

                job.progress = 50 + int((i + batch_size) / total_chunks * 50)
                await db.commit()

            job.status = JobStatus.done.value
            job.progress = 100
            job.error_message = None
            await db.commit()
        except Exception as e:
            log.exception("ingestion failed")
            job.status = JobStatus.failed.value
            job.error_message = str(e)[:2000]
            await db.commit()
