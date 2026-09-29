from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

from .query_planner import concept_version
from .util import digest, stable_json


DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


class SemanticIndex:
    """A small local dense-vector index. Heavy dependencies are imported only when used."""

    def __init__(self, data_dir: Path, model_name: str = DEFAULT_MODEL):
        self.directory = data_dir / "semantic"
        self.model_name = model_name
        self._model = None
        self._vectors = None
        self._chunk_ids = None

    @property
    def metadata_path(self) -> Path:
        return self.directory / "meta.json"

    def metadata(self) -> dict | None:
        try:
            return json.loads(self.metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def available(self) -> bool:
        metadata = self.metadata()
        return bool(
            metadata
            and metadata.get("model") == self.model_name
            and (self.directory / "vectors.npy").is_file()
            and (self.directory / "chunk_ids.npy").is_file()
        )

    def _embedding_model(self):
        if self._model is None:
            try:
                from fastembed import TextEmbedding
            except ImportError as exc:
                raise RuntimeError("semantic_dependency_missing") from exc
            self.directory.mkdir(parents=True, exist_ok=True)
            self._model = TextEmbedding(
                model_name=self.model_name,
                cache_dir=str(self.directory / "models"),
            )
        return self._model

    @staticmethod
    def corpus_digest(rows: Iterable[tuple[int, str]]) -> str:
        return digest(stable_json(list(rows)))

    def build(self, database, *, batch_size: int = 64) -> dict:
        import numpy as np

        with database.connection() as connection:
            rows = connection.execute(
                "SELECT c.id,v.title,c.text,c.text_sha FROM chunks c "
                "JOIN documents d ON d.id=c.document_id "
                "JOIN document_versions v ON v.id=c.version_id "
                "WHERE c.version_id=d.current_version_id ORDER BY c.id"
            ).fetchall()
        if not rows:
            raise RuntimeError("semantic_corpus_empty")
        texts = [f"{row['title']}\n{row['text']}" for row in rows]
        vectors = np.asarray(
            list(self._embedding_model().embed(texts, batch_size=batch_size)), dtype=np.float32
        )
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        vectors = vectors / np.maximum(norms, 1e-12)
        chunk_ids = np.asarray([row["id"] for row in rows], dtype=np.int64)
        self.directory.mkdir(parents=True, exist_ok=True)
        vector_tmp = self.directory / "vectors.tmp.npy"
        id_tmp = self.directory / "chunk_ids.tmp.npy"
        np.save(vector_tmp, vectors)
        np.save(id_tmp, chunk_ids)
        os.replace(vector_tmp, self.directory / "vectors.npy")
        os.replace(id_tmp, self.directory / "chunk_ids.npy")
        metadata = {
            "model": self.model_name,
            "dimension": int(vectors.shape[1]),
            "chunk_count": int(vectors.shape[0]),
            "max_chunk_id": int(chunk_ids[-1]),
            "corpus_digest": self.corpus_digest([(row["id"], row["text_sha"]) for row in rows]),
            "concept_version": concept_version(),
            "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        meta_tmp = self.directory / "meta.tmp.json"
        meta_tmp.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(meta_tmp, self.metadata_path)
        self._vectors = vectors
        self._chunk_ids = chunk_ids
        return metadata

    def is_current(self, connection) -> bool:
        metadata = self.metadata()
        if not metadata:
            return False
        row = connection.execute(
            "SELECT count(*),coalesce(max(c.id),0) FROM chunks c "
            "JOIN documents d ON d.id=c.document_id WHERE c.version_id=d.current_version_id"
        ).fetchone()
        return (
            metadata.get("chunk_count") == row[0]
            and metadata.get("max_chunk_id") == row[1]
        )

    def search(self, query: str, limit: int = 300) -> list[tuple[int, float]]:
        if not self.available():
            return []
        import numpy as np

        if self._vectors is None:
            self._vectors = np.load(self.directory / "vectors.npy", mmap_mode="r")
            self._chunk_ids = np.load(self.directory / "chunk_ids.npy", mmap_mode="r")
        vector = np.asarray(
            next(iter(self._embedding_model().query_embed(query))), dtype=np.float32
        )
        vector = vector / max(float(np.linalg.norm(vector)), 1e-12)
        scores = self._vectors @ vector
        count = min(limit, len(scores))
        if count == 0:
            return []
        indices = np.argpartition(scores, -count)[-count:]
        indices = indices[np.argsort(scores[indices])[::-1]]
        return [(int(self._chunk_ids[index]), float(scores[index])) for index in indices]
