import threading
import uuid
from typing import Optional

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger("vector")

_SCORE_THRESHOLD = 0.30


class VectorStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ready = False
        self._store = None
        self._embeddings = None
        self._collection = None

    @property
    def is_ready(self) -> bool:
        return self._ready

    def warmup(self) -> bool:
        ready = self._initialize()
        if ready and self._embeddings:
            try:
                self._embeddings.embed_query("warmup")
            except Exception:
                pass
        return ready

    def _initialize(self) -> bool:
        if self._ready:
            return True
        with self._lock:
            if self._ready:
                return True
            settings = get_settings()
            try:
                from langchain_huggingface import HuggingFaceEmbeddings
                from langchain_qdrant import QdrantVectorStore
                from qdrant_client import QdrantClient
                from qdrant_client.http.models import Distance, VectorParams

                client = QdrantClient(url=settings.qdrant_url, timeout=1.0)
                collections = [c.name for c in client.get_collections().collections]
                self._collection = settings.qdrant_collection
                if self._collection not in collections:
                    client.create_collection(
                        collection_name=self._collection,
                        vectors_config=VectorParams(size=384, distance=Distance.COSINE),
                    )
                    logger.info("Created Qdrant collection %s", self._collection)

                self._embeddings = HuggingFaceEmbeddings(model_name=settings.embedding_model)
                self._store = QdrantVectorStore(
                    client=client,
                    collection_name=self._collection,
                    embedding=self._embeddings,
                )
                self._ready = True
                logger.info("Vector memory ready (Qdrant at %s).", settings.qdrant_url)
            except Exception as exc:
                logger.warning("Vector memory unavailable: %s", exc)
                self._ready = False
            return self._ready

    def add(self, text: str, metadata: Optional[dict] = None) -> Optional[uuid.UUID]:
        if not self._ready:
            return None
        point_id = uuid.uuid4()
        try:
            from langchain_core.documents import Document

            self._store.add_documents(
                [Document(page_content=text, metadata=metadata or {})],
                ids=[str(point_id)],
            )
            return point_id
        except Exception as exc:
            logger.warning("Vector add failed: %s", exc)
            return None

    def search(self, query: str, k: int = 4):
        if not self._ready:
            return []
        try:
            docs_with_scores = self._store.similarity_search_with_relevance_scores(
                query, k=k, score_threshold=_SCORE_THRESHOLD
            )
            return [(d.page_content, score) for d, score in docs_with_scores]
        except Exception as exc:
            logger.warning("Vector search failed: %s", exc)
            return []

    def delete(self, point_id: str) -> None:
        if not self._ready:
            return
        try:
            from qdrant_client import QdrantClient

            QdrantClient(url=get_settings().qdrant_url).delete(
                collection_name=self._collection,
                points_selector=[point_id],
            )
        except Exception as exc:
            logger.warning("Vector delete failed: %s", exc)


vector_store = VectorStore()
