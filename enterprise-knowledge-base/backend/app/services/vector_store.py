from __future__ import annotations

from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.core.config import get_settings


def _client() -> chromadb.PersistentClient:
    s = get_settings()
    return chromadb.PersistentClient(
        path=s.chroma_path,
        settings=ChromaSettings(anonymized_telemetry=False),
    )


def collection_name(kb_id: str) -> str:
    return f"kb_{kb_id.replace('-', '_')}"


def get_collection(kb_id: str):
    client = _client()
    name = collection_name(kb_id)
    return client.get_or_create_collection(name=name, metadata={"kb_id": kb_id})


def add_chunks(
    kb_id: str,
    ids: list[str],
    embeddings: list[list[float]],
    documents: list[str],
    metadatas: list[dict[str, Any]],
) -> None:
    col = get_collection(kb_id)
    col.add(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)


def delete_ids(kb_id: str, ids: list[str]) -> None:
    if not ids:
        return
    col = get_collection(kb_id)
    col.delete(ids=ids)


def query_vectors(kb_id: str, query_embedding: list[float], top_k: int) -> dict[str, Any]:
    col = get_collection(kb_id)
    return col.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )


async def search(kb_id: str, query: str, top_k: int) -> list[dict[str, Any]]:
    """Embed query and return top-k results from the vector store."""
    from app.services import embeddings as emb_svc

    settings = get_settings()
    model = settings.embedding_model
    query_vec = (await emb_svc.embed_texts([query], model=model))[0]
    col = get_collection(kb_id)
    raw = col.query(
        query_embeddings=[query_vec],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )
    out: list[dict[str, Any]] = []
    ids = raw.get("ids", [[]])[0]
    docs = raw.get("documents", [[]])[0]
    metas = raw.get("metadatas", [[]])[0]
    dists = raw.get("distances", [[]])[0]
    for i, cid in enumerate(ids):
        d = float(dists[i]) if i < len(dists) else 1.0
        score = round(1.0 / (1.0 + d), 4)
        meta = dict(metas[i]) if i < len(metas) else {}
        if "source" not in meta:
            meta["source"] = meta.get("filename", "")
        out.append(
            {
                "chunk_id": cid,
                "content": docs[i] if i < len(docs) else "",
                "score": score,
                "metadata": meta,
            }
        )
    return out


def delete_collection(kb_id: str) -> None:
    client = _client()
    try:
        client.delete_collection(collection_name(kb_id))
    except Exception:
        pass
