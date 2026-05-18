"""Text chunking strategies."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Chunk:
    text: str
    heading_path: str
    page: int | None
    chunk_index: int


def simple_chunks(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    text = text.strip()
    if not text:
        return []
    out: list[str] = []
    i = 0
    step = max(1, chunk_size - chunk_overlap)
    while i < len(text):
        out.append(text[i : i + chunk_size])
        i += step
    return out


def chunk_with_headings(
    segments: list[tuple[int | None, str, str]],
    chunk_size: int,
    chunk_overlap: int,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    idx = 0
    for page, heading, seg_text in segments:
        if not seg_text.strip():
            continue
        for part in simple_chunks(seg_text, chunk_size, chunk_overlap):
            chunks.append(Chunk(text=part, heading_path=heading, page=page, chunk_index=idx))
            idx += 1
    if not chunks:
        full = "\n".join(s[2] for s in segments if s[2].strip())
        for part in simple_chunks(full, chunk_size, chunk_overlap):
            chunks.append(Chunk(text=part, heading_path="", page=None, chunk_index=idx))
            idx += 1
    return chunks
