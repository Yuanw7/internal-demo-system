from __future__ import annotations

import re
from dataclasses import dataclass

from .util import digest


@dataclass(frozen=True)
class Chunk:
    stable_id: str
    start: int
    end: int
    page: int | None
    text: str


def _units(body: str, start: int, end: int) -> list[tuple[int, int]]:
    """Split on paragraph/sentence boundaries while preserving absolute offsets."""
    spans: list[tuple[int, int]] = []
    cursor = start
    boundary = re.compile(r"(?:\n{2,}|(?<=[。！？!?])|(?<=[.])\s+)")
    for match in boundary.finditer(body, start, end):
        point = match.end()
        if body[cursor:point].strip():
            spans.append((cursor, point))
        cursor = point
    if cursor < end and body[cursor:end].strip():
        spans.append((cursor, end))
    return spans or ([(start, end)] if body[start:end].strip() else [])


def chunk_document(
    document_id: str,
    version_id: str,
    body: str,
    pages: list[tuple[int, int, int]],
    *,
    max_chars: int = 1400,
    overlap_chars: int = 240,
) -> list[Chunk]:
    page_spans = pages or [(None, 0, len(body))]
    chunks: list[Chunk] = []
    for page, page_start, page_end in page_spans:
        units = _units(body, page_start, page_end)
        index = 0
        while index < len(units):
            start = units[index][0]
            end = start
            next_index = index
            while next_index < len(units) and units[next_index][1] - start <= max_chars:
                end = units[next_index][1]
                next_index += 1
            if next_index == index:
                end = min(start + max_chars, units[index][1])
                if end < units[index][1]:
                    units[index] = (end, units[index][1])
                else:
                    next_index += 1
            text = body[start:end]
            stable_id = digest(f"{document_id}:{version_id}:{start}:{end}")[:32]
            chunks.append(Chunk(stable_id, start, end, page, text))
            if next_index >= len(units):
                break
            overlap_index = next_index
            while overlap_index > index + 1:
                candidate = units[overlap_index - 1][0]
                if end - candidate > overlap_chars:
                    break
                overlap_index -= 1
            index = overlap_index if overlap_index < next_index else next_index
    return chunks
