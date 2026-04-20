"""
Face Re-Identification — InsightFace ArcFace → Qdrant vector search.

Provider chain: CUDAExecutionProvider → CPUExecutionProvider
No CoreML / MPS — cross-platform compatible (Linux/Railway/Docker).
"""

from __future__ import annotations

import asyncio
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
from loguru import logger

from sentinel.core.config import get_settings
from sentinel.core.logging_setup import log_face_id

if TYPE_CHECKING:
    from qdrant_client import AsyncQdrantClient

cfg = get_settings()

# ONNX providers in priority order — CUDA first, CPU as universal fallback
_ONNX_PROVIDERS = ["CUDAExecutionProvider", "CPUExecutionProvider"]


@dataclass
class Identity:
    person_id: str
    name: str
    category: str       # "staff" | "vip" | "regular" | "new"
    similarity: float
    visit_count: int = 0


class FaceReIDService:
    def __init__(self) -> None:
        self._app: Any = None
        self._qdrant: AsyncQdrantClient | None = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="reid")
        self._ready = False

    @property
    def ready(self) -> bool:
        return self._ready

    async def load(self) -> None:
        import time
        loop = asyncio.get_event_loop()
        logger.info("🧠 Loading InsightFace ReID — model={}", cfg.FACE_REID_MODEL)
        t0 = time.monotonic()
        self._app = await loop.run_in_executor(self._executor, self._load_insightface)
        try:
            from qdrant_client import AsyncQdrantClient  # lazy
            self._qdrant = AsyncQdrantClient(url=cfg.QDRANT_URL)
            await self._ensure_collection()
        except Exception as exc:
            logger.warning("⚠️ Qdrant unavailable ({}). ReID will work without vector search.", exc)
            self._qdrant = None
        self._ready = True
        logger.success("✅ InsightFace ready in {:.1f}s", time.monotonic() - t0)

    def _load_insightface(self):  # type: ignore[no-untyped-def]
        from insightface.app import FaceAnalysis  # lazy import
        app = FaceAnalysis(name=cfg.FACE_REID_MODEL, providers=_ONNX_PROVIDERS)
        app.prepare(ctx_id=0, det_size=(640, 640))
        return app

    async def _ensure_collection(self) -> None:
        from qdrant_client.models import Distance, VectorParams  # lazy
        assert self._qdrant is not None
        cols = await self._qdrant.get_collections()
        existing = [c.name for c in cols.collections]
        if cfg.QDRANT_COLLECTION_FACES not in existing:
            await self._qdrant.create_collection(
                cfg.QDRANT_COLLECTION_FACES,
                vectors_config=VectorParams(size=cfg.QDRANT_VECTOR_SIZE, distance=Distance.COSINE),
            )
            logger.info("📦 Qdrant collection '{}' created", cfg.QDRANT_COLLECTION_FACES)

    # ── Public API ──────────────────────────────────────────────────────────────

    async def identify(self, face_crop: np.ndarray) -> Identity | None:
        if not self._ready or self._app is None:
            return None
        loop = asyncio.get_event_loop()
        embedding = await loop.run_in_executor(self._executor, self._get_embedding, face_crop)
        if embedding is None:
            return None
        identity = await self._search(embedding)
        if identity:
            log_face_id(identity.name, identity.category, identity.similarity, "reid")
        return identity

    async def get_embedding_for_face(self, image: np.ndarray) -> np.ndarray | None:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, self._get_embedding, image)

    async def register(
        self,
        person_id: str,
        name: str,
        category: str,
        embedding: np.ndarray,
        visit_count: int = 0,
    ) -> None:
        from qdrant_client.models import PointStruct  # lazy
        if self._qdrant is None:
            logger.warning("Qdrant unavailable — cannot register face for {}", name)
            return
        await self._qdrant.upsert(
            collection_name=cfg.QDRANT_COLLECTION_FACES,
            points=[PointStruct(
                id=str(uuid.uuid4()),
                vector=embedding.tolist(),
                payload={
                    "person_id": person_id,
                    "name": name,
                    "category": category,
                    "visit_count": visit_count,
                },
            )],
        )
        logger.success("✅ Enrolled: {} ({}) id={}", name, category, person_id)

    # ── Internal ────────────────────────────────────────────────────────────────

    def _get_embedding(self, image: np.ndarray) -> np.ndarray | None:
        if self._app is None:
            return None
        try:
            faces = self._app.get(image)
        except Exception as exc:
            logger.debug("reid._get_embedding error: {}", exc)
            return None
        if not faces:
            return None
        face = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
        emb = face.normed_embedding
        return emb.astype(np.float32) if emb is not None else None

    async def _search(self, embedding: np.ndarray) -> Identity | None:
        if self._qdrant is None:
            return None
        hits = await self._qdrant.search(
            collection_name=cfg.QDRANT_COLLECTION_FACES,
            query_vector=embedding.tolist(),
            limit=1,
            score_threshold=cfg.FACE_SIMILARITY_THRESHOLD,
        )
        if not hits:
            return None
        hit = hits[0]
        p = hit.payload or {}
        return Identity(
            person_id=str(p.get("person_id", hit.id)),
            name=str(p.get("name", "Незнакомец")),
            category=str(p.get("category", "new")),
            similarity=float(hit.score),
            visit_count=int(p.get("visit_count", 0)),
        )
