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
from app.services import embeddings as emb_svc
from app.services import vector_store as vs


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


async def hybrid_search(
    db: AsyncSession,
    kb_id: str,
    query: str,
    top_k: int = 8,
    vector_weight: float = 0.65,
) -> list[dict[str, Any]]:
    kb = await db.get(KnowledgeBase, kb_id)
    if not kb:
        return []
    model = kb.embedding_model_id
    query_vec = (await emb_svc.embed_texts([query], model=model))[0]
    vec_raw = vs.query_vectors(kb_id, query_vec, top_k=max(top_k * 4, 20))
    vec_ids = vec_raw["ids"][0] if vec_raw.get("ids") else []
    vec_dist = vec_raw["distances"][0] if vec_raw.get("distances") else []

    vec_scores: dict[str, float] = {}
    for i, cid in enumerate(vec_ids):
        d = float(vec_dist[i]) if i < len(vec_dist) else 1.0
        sim = 1.0 / (1.0 + d)
        vec_scores[cid] = sim

    id_list, texts, _metas = await load_kb_chunks(db, kb_id)
    if not texts:
        return []

    tokenized = [_tokenize(t) for t in texts]
    bm25 = BM25Okapi(tokenized)
    q_tokens = _tokenize(query)
    bm_scores = bm25.get_scores(q_tokens)
    bm_map: dict[str, float] = {}
    for i, cid in enumerate(id_list):
        if i < len(bm_scores):
            bm_map[cid] = float(bm_scores[i])

    def norm_dict(d: dict[str, float]) -> dict[str, float]:
        if not d:
            return {}
        lo, hi = min(d.values()), max(d.values())
        if hi - lo < 1e-9:
            return {k: 1.0 for k in d}
        return {k: (v - lo) / (hi - lo) for k, v in d.items()}

    n_vec = norm_dict(vec_scores)
    n_bm = norm_dict(bm_map)
    all_ids = set(n_vec) | set(n_bm)
    fused: dict[str, float] = {}
    for cid in all_ids:
        fused[cid] = vector_weight * n_vec.get(cid, 0.0) + (1 - vector_weight) * n_bm.get(cid, 0.0)

    ranked = sorted(fused.items(), key=lambda x: x[1], reverse=True)[:top_k]
    out: list[dict[str, Any]] = []
    for cid, score in ranked:
        chunk = await db.get(ChunkRecord, cid)
        if not chunk:
            continue
        doc = await db.get(Document, chunk.document_id)
        out.append(
            {
                "chunk_id": cid,
                "content": chunk.content,
                "score": round(score, 4),
                "metadata": {
                    "source": doc.filename if doc else "",
                    "document_id": chunk.document_id,
                    "page": chunk.page,
                    "heading_path": chunk.heading_path,
                },
            }
        )
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
