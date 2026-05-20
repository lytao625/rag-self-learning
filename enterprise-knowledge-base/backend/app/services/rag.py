from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
from rank_bm25 import BM25Okapi
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import ChunkRecord, Document, KnowledgeBase
from app.services import vector_store as vs
from app.services.reranker import rerank_documents

def _tokenize(text: str) -> list[str]:
    return [t for t in "".join(ch if ch.isalnum() else " " for ch in text.lower()).split() if t]


async def load_kb_chunks(
    db: AsyncSession, kb_id: str
) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    """Returns parallel lists: chunk_ids, texts, lightweight meta (for citations)."""
    q = (
        select(ChunkRecord)
        .join(Document, ChunkRecord.document_id == Document.id)
        .where(Document.knowledge_base_id == kb_id)
        .order_by(ChunkRecord.document_id, ChunkRecord.chunk_index)
    )
    res = await db.execute(q)
    rows = list(res.scalars().all())
    ids = [r.id for r in rows]
    texts = [r.content for r in rows]
    meta = [
        {
            "document_id": r.document_id,
            "heading_path": r.heading_path,
            "page": r.page,
            "embedding_model_id": r.embedding_model_id,
        }
        for r in rows
    ]
    return ids, texts, meta


def _norm_scores(d: dict[str, float]) -> dict[str, float]:
    """Min-max normalize a score dict. Returns empty dict for empty input."""
    if not d:
        return {}
    lo, hi = min(d.values()), max(d.values())
    if hi - lo < 1e-9:
        return {k: 1.0 for k in d}
    return {k: (v - lo) / (hi - lo) for k, v in d.items()}


async def hybrid_search(
    db: AsyncSession,
    kb_id: str,
    query: str,
    top_k: int = 15,
    vector_weight: float = 0.65,
) -> list[dict[str, Any]]:
    """Two-stage hybrid retrieval: vector search + BM25 keyword search, with score fusion.

    Stage 1 – Vector recall: retrieves a larger pool via embedding similarity.
    Stage 2 – BM25: scores the full corpus for keyword match, then fuses normalized
              scores from both sources via weighted sum.
    Stage 3 – Optional rerank: applies cross-encoder reranker when enabled.
    """
    kb = await db.get(KnowledgeBase, kb_id)
    if not kb:
        return []

    effective_top_k = kb.search_top_k or top_k
    pool_size = max(effective_top_k * 4, 20)

    # ── Stage 1: Vector recall ──────────────────────────────────────────
    vector_hits = await vs.search(kb_id, query, top_k=pool_size)
    if not vector_hits:
        return []

    # ── Stage 2: BM25 + score fusion ────────────────────────────────────
    all_ids, all_texts, all_metas = await load_kb_chunks(db, kb_id)
    if not all_texts:
        return vector_hits[:effective_top_k]

    tokenized_corpus = [_tokenize(t) for t in all_texts]
    bm25 = BM25Okapi(tokenized_corpus)
    bm_scores = bm25.get_scores(_tokenize(query))

    bm25_map: dict[str, float] = {
        all_ids[i]: float(bm_scores[i]) for i in range(len(all_ids))
    }
    vec_map: dict[str, float] = {h["chunk_id"]: h["score"] for h in vector_hits}

    n_vec = _norm_scores(vec_map)
    n_bm = _norm_scores(bm25_map)

    candidate_ids = set(n_vec.keys()) | set(n_bm.keys())
    fused: dict[str, float] = {}
    for cid in candidate_ids:
        fused[cid] = vector_weight * n_vec.get(cid, 0.0) + (1 - vector_weight) * n_bm.get(cid, 0.0)

    ranked = sorted(fused.items(), key=lambda x: x[1], reverse=True)[:effective_top_k]

    # ── Build output ────────────────────────────────────────────────────
    doc_ids = {m.get("document_id", "") for m in all_metas if m.get("document_id")}
    doc_map: dict[str, str] = {}
    if doc_ids:
        doc_rows = (await db.execute(select(Document).where(Document.id.in_(list(doc_ids))))).scalars().all()
        doc_map = {d.id: d.filename for d in doc_rows}

    text_lookup = {all_ids[i]: all_texts[i] for i in range(len(all_ids))}
    meta_lookup = {all_ids[i]: all_metas[i] for i in range(len(all_ids))}

    out: list[dict[str, Any]] = []
    for cid, score in ranked:
        meta = meta_lookup.get(cid, {})
        out.append(
            {
                "chunk_id": cid,
                "content": text_lookup.get(cid, ""),
                "score": round(score, 4),
                "metadata": {
                    "source": doc_map.get(meta.get("document_id", ""), ""),
                    "document_id": meta.get("document_id", ""),
                    "page": meta.get("page"),
                    "heading_path": meta.get("heading_path", ""),
                },
            }
        )

    # ── Stage 3: Rerank ─────────────────────────────────────────────────
    if kb.use_rerank and out:
        out = await rerank_documents(query, out, top_n=kb.rerank_top_k or effective_top_k)

    return out

SYSTEM_PROMPT = """你是企业知识库助手。请仅根据「参考资料」回答问题。
若参考资料不足以回答，请明确说明「根据现有资料无法回答」，不要编造条款或出处。
回答末尾不需要重复参考资料全文。"""


async def stream_llm_answer(
    messages: list[dict[str, str]],
) -> AsyncIterator[str]:
    settings = get_settings()
    if not settings.openai_api_key:
        yield "[错误] 服务端未配置 OPENAI_API_KEY，无法调用大模型。"
        return
    url = settings.openai_api_base.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": settings.llm_model,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}, *messages],
        "temperature": 0.3,
        "stream": True,
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream("POST", url, headers=headers, json=body) as resp:
            if resp.status_code >= 400:
                err = await resp.aread()
                yield f"[错误] LLM 调用失败: {resp.status_code} {err.decode(errors='replace')[:500]}"
                return
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data = line[6:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                    delta = obj["choices"][0].get("delta") or {}
                    piece = delta.get("content") or ""
                    if piece:
                        yield piece
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
