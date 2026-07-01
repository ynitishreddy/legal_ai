import logging
import threading
import time
from typing import List, Dict, Any, Optional
from uuid import UUID

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class QdrantService:
    """
    Singleton service wrapper for the Qdrant Vector Database.
    Handles connection state, auto-creating collections, HNSW index generation,
    and fallback to local in-memory Qdrant instance if connection fails.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super(QdrantService, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self.settings = get_settings()
        self.host = self.settings.qdrant_host
        self.port = self.settings.qdrant_port
        self.api_key = self.settings.qdrant_api_key
        self.https = self.settings.qdrant_https
        self.collection_name = self.settings.qdrant_collection_name
        self.dimension = self.settings.embedding_dimension

        self._client = None
        self._client_lock = threading.Lock()
        self._initialized = True

    def _get_url(self) -> str:
        protocol = "https" if self.https else "http"
        return f"{protocol}://{self.host}:{self.port}"

    def _load_client(self):
        """Lazy-loads the Qdrant client, with in-memory fallback on connection failure."""
        if self._client is not None:
            return self._client

        with self._client_lock:
            if self._client is not None:
                return self._client

            from qdrant_client import QdrantClient
            
            # If host is configured as memory/mock, use native in-memory Qdrant
            if self.host in (":memory:", "mock", "memory"):
                logger.info("QdrantService: Initializing native in-memory Qdrant instance.")
                self._client = QdrantClient(":memory:")
                self._verify_collection(self._client)
                return self._client

            url = self._get_url()
            logger.info("QdrantService: Connecting to Qdrant cluster at %s...", url)
            try:
                # Direct server connection check with brief timeout
                client = QdrantClient(
                    url=url,
                    api_key=self.api_key,
                    timeout=5.0,
                )
                # Query collections to verify active connection
                client.get_collections()
                self._client = client
                logger.info("QdrantService: Successfully connected to Qdrant server at %s", url)
                self._verify_collection(self._client)
            except Exception as e:
                logger.warning(
                    "QdrantService: Failed to connect to Qdrant server at %s (%s). Falling back to in-memory instance.",
                    url, str(e)
                )
                self._client = QdrantClient(":memory:")
                self._verify_collection(self._client)

        return self._client

    def _verify_collection(self, client) -> None:
        """Verifies collection integrity. Creates it if missing with proper configuration."""
        from qdrant_client.http import models as qmodels
        try:
            logger.info("QdrantService: Verifying vector collection '%s' integrity...", self.collection_name)
            collections = client.get_collections().collections
            collection_names = [col.name for col in collections]
            
            if self.collection_name not in collection_names:
                logger.info(
                    "QdrantService: Collection '%s' does not exist. Creating with dimension %d and COSINE distance.",
                    self.collection_name, self.dimension
                )
                client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=qmodels.VectorParams(
                        size=self.dimension,
                        distance=qmodels.Distance.COSINE,
                    ),
                    hnsw_config=qmodels.HnswConfigDiff(
                        m=16,
                        ef_construct=100,
                    ),
                    optimizers_config=qmodels.OptimizersConfigDiff(
                        default_segment_number=2,
                    ),
                )
                
                # Create standard payload indexes for future filtering performance
                client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name="document_id",
                    field_schema=qmodels.PayloadSchemaType.KEYWORD,
                )
                client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name="case_id",
                    field_schema=qmodels.PayloadSchemaType.KEYWORD,
                )
                client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name="owner_id",
                    field_schema=qmodels.PayloadSchemaType.KEYWORD,
                )
                logger.info("QdrantService: Collection '%s' created and indexed successfully.", self.collection_name)
            else:
                logger.debug("QdrantService: Collection '%s' exists and is verified.", self.collection_name)
        except Exception as e:
            logger.error("QdrantService: Error verifying/creating collection '%s': %s", self.collection_name, str(e), exc_info=True)

    def health_check(self) -> Dict[str, Any]:
        """Perform health check verification queries."""
        try:
            client = self._load_client()
            collections = client.get_collections().collections
            # In Qdrant client, remote server uses QdrantRemote. Any local storage uses memory storage or local file.
            is_remote = client._client.__class__.__name__ == "QdrantRemote"
            mode = "server" if is_remote else "memory"
            
            # Simple metadata query
            info = client.get_collection(self.collection_name)
            
            return {
                "status": "healthy",
                "mode": mode,
                "collections_count": len(collections),
                "target_collection": self.collection_name,
                "vector_count": info.points_count,
                "status_detail": "Qdrant connection active and target collection responsive"
            }
        except Exception as e:
            logger.error("QdrantService: Health check failed: %s", str(e))
            return {
                "status": "unhealthy",
                "mode": "disconnected",
                "collections_count": 0,
                "target_collection": self.collection_name,
                "vector_count": 0,
                "status_detail": f"Connection/Query failure: {str(e)}"
            }

    def upsert_vectors(self, points: List[Dict[str, Any]]) -> bool:
        """
        Upserts a batch of vectors into Qdrant.
        Each point dict must contain:
          - 'id': UUID
          - 'vector': List[float]
          - 'payload': Dict[str, Any]
        """
        if not points:
            return True

        client = self._load_client()
        from qdrant_client.http import models as qmodels
        
        q_points = []
        for p in points:
            # Generate deterministic UUID-string from standard UUID
            point_id = str(p["id"])
            q_points.append(
                qmodels.PointStruct(
                    id=point_id,
                    vector=p["vector"],
                    payload=p["payload"],
                )
            )

        retries = self.settings.qdrant_max_retries
        for attempt in range(retries):
            try:
                client.upsert(
                    collection_name=self.collection_name,
                    points=q_points,
                    wait=True,
                )
                logger.debug("QdrantService: Successfully upserted %d vectors.", len(points))
                return True
            except Exception as e:
                logger.warning(
                    "QdrantService: Upsert failed (attempt %d/%d): %s", 
                    attempt + 1, retries, str(e)
                )
                if attempt == retries - 1:
                    logger.error("QdrantService: Max retries exceeded during vector upsert.")
                    raise e
                time.sleep(1.0 * (attempt + 1))
        return False

    def delete_vectors(self, ids: List[UUID]) -> bool:
        """Deletes vectors with the given standard UUIDs from Qdrant."""
        if not ids:
            return True

        client = self._load_client()
        from qdrant_client.http import models as qmodels
        
        point_ids = [str(uuid_id) for uuid_id in ids]
        
        try:
            client.delete(
                collection_name=self.collection_name,
                points_selector=qmodels.PointIdsList(
                    points=point_ids
                ),
                wait=True,
            )
            logger.debug("QdrantService: Successfully deleted %d vectors from Qdrant.", len(ids))
            return True
        except Exception as e:
            logger.error("QdrantService: Failed to delete vectors from Qdrant: %s", str(e), exc_info=True)
            raise e

    def delete_by_document(self, document_id: UUID) -> bool:
        """Deletes all vectors belonging to a specific document ID filter."""
        client = self._load_client()
        from qdrant_client.http import models as qmodels
        
        try:
            client.delete(
                collection_name=self.collection_name,
                points_selector=qmodels.FilterSelector(
                    filter=qmodels.Filter(
                        must=[
                            qmodels.FieldCondition(
                                key="document_id",
                                match=qmodels.MatchValue(value=str(document_id))
                            )
                        ]
                    )
                ),
                wait=True,
            )
            logger.debug("QdrantService: Deleted Qdrant vectors filtered by document_id=%s", document_id)
            return True
        except Exception as e:
            logger.error("QdrantService: Failed to delete vectors by document filter: %s", str(e))
            raise e

    def get_collection_info(self) -> Dict[str, Any]:
        """Expose detailed stats of the target collection."""
        try:
            client = self._load_client()
            info = client.get_collection(self.collection_name)
            return {
                "name": self.collection_name,
                "status": str(info.status),
                "vectors_count": info.points_count,
                "dimension": self.dimension,
                "indexed_vectors_count": info.indexed_points_count,
                "segments_count": info.segments_count,
            }
        except Exception as e:
            logger.warning("QdrantService: Failed to fetch collection info: %s", str(e))
            return {
                "name": self.collection_name,
                "status": "unavailable",
                "vectors_count": 0,
                "dimension": self.dimension,
                "indexed_vectors_count": 0,
                "segments_count": 0,
            }

    def search_vectors(
        self,
        query_vector: List[float],
        limit: int = 5,
        score_threshold: Optional[float] = None,
        filter_dict: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Executes similarity search on the configured Qdrant collection.
        Resolves filtering dictionary parameters to build a strict Qdrant search filter.
        """
        client = self._load_client()
        from qdrant_client.http import models as qmodels
        from uuid import UUID

        must_conditions = []
        if filter_dict:
            for key, val in filter_dict.items():
                if val is not None and val != "":
                    # Map standard filters to FieldCondition matching
                    if isinstance(val, list):
                        if len(val) > 0:
                            must_conditions.append(
                                qmodels.FieldCondition(
                                    key=key,
                                    match=qmodels.MatchAny(any=[str(v) for v in val])
                                )
                            )
                    else:
                        must_conditions.append(
                            qmodels.FieldCondition(
                                key=key,
                                match=qmodels.MatchValue(value=str(val))
                            )
                        )

        q_filter = qmodels.Filter(must=must_conditions) if must_conditions else None

        try:
            results = client.search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                query_filter=q_filter,
                limit=limit,
                score_threshold=score_threshold,
                with_payload=True,
                with_vectors=False,
            )
            
            output = []
            for r in results:
                point_id = r.id
                if isinstance(point_id, str):
                    try:
                        point_id = UUID(point_id)
                    except ValueError:
                        pass
                
                output.append({
                    "id": point_id,
                    "score": r.score,
                    "payload": r.payload or {},
                })
            return output
        except Exception as e:
            logger.error("QdrantService: Search vectors query failed: %s", str(e), exc_info=True)
            raise e

