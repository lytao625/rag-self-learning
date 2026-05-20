import asyncio
import logging
from typing import Any, Optional

from app.core.config import get_settings

log = logging.getLogger(__name__)


class RerankerService:
    """Cross-encoder reranker with lazy loading and async-safe inference."""

    def __init__(self, model_name: Optional[str] = None, device: Optional[str] = None):
        self._model_name = model_name or get_settings().reranker_model
        self._device = device
        self._model = None
        self._lock = asyncio.Lock()
        self._available = True

    async def _load_model(self):
        if self._model is not None:
            return
        async with self._lock:
            if self._model is not None:
                return
            try:
                from sentence_transformers import CrossEncoder

                log.info("Loading reranker model: %s", self._model_name)
                self._model = await asyncio.to_thread(
                    lambda: CrossEncoder(self._model_name, device=self._device)
                )
            except Exception:
                self._available = False
                log.warning(
                    "Failed to load reranker model '%s'. Rerank disabled.",
                    self._model_name,
                    exc_info=True,
                )

    async def rerank(
        self,
        query: str,
        documents: list[dict[str, Any]],
        top_n: int = 5,
    ) -> list[dict[str, Any]]:
        if not documents:
            return []

        valid_docs = [d for d in documents if "content" in d]
        if not valid_docs:
            log.warning("No documents with 'content' field for reranking")
            return documents[:top_n]

        if not self._available:
            return valid_docs[:top_n]

        await self._load_model()
        if self._model is None:
            return valid_docs[:top_n]

        pairs = [[query, d["content"]] for d in valid_docs]

        try:
            scores = await asyncio.to_thread(
                self._model.predict, pairs, show_progress_bar=False
            )
            for doc, score in zip(valid_docs, scores):
                doc["rerank_score"] = float(score)

            ranked = sorted(
                valid_docs, key=lambda x: x.get("rerank_score", 0), reverse=True
            )
            return ranked[:top_n]
        except Exception as e:
            log.error("Rerank failed: %s, falling back to original order", e)
            return valid_docs[:top_n]


_reranker: Optional[RerankerService] = None


def get_reranker() -> RerankerService:
    global _reranker
    if _reranker is None:
        _reranker = RerankerService()
    return _reranker


async def rerank_documents(
    query: str,
    documents: list[dict[str, Any]],
    top_n: int = 5,
) -> list[dict[str, Any]]:
    return await get_reranker().rerank(query, documents, top_n)
