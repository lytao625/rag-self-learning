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


def delete_collection(kb_id: str) -> None:
    client = _client()
    try:
        client.delete_collection(collection_name(kb_id))
    except Exception:
        pass
