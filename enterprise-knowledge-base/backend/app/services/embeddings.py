from __future__ import annotations

import httpx

from app.core.config import get_settings


async def embed_texts(texts: list[str], model: str | None = None) -> list[list[float]]:
    settings = get_settings()
    m = model or settings.embedding_model
    if not settings.openai_api_key:
        raise RuntimeError("未配置 OPENAI_API_KEY，无法计算向量")
    url = settings.openai_api_base.rstrip("/") + "/embeddings"
    headers = {"Authorization": f"Bearer {settings.openai_api_key}"}
    out: list[list[float]] = []
    batch = 32
    print(f"url:{url}, model:{m}, headers:{headers}")
    async with httpx.AsyncClient(timeout=120.0) as client:
        for i in range(0, len(texts), batch):
            chunk = texts[i : i + batch]
            resp = await client.post(
                url,
                headers=headers,
                json={"model": m, "input": chunk},
            )
            resp.raise_for_status()
            data = resp.json()["data"]
            data.sort(key=lambda x: x["index"])
            out.extend([d["embedding"] for d in data])
    return out
