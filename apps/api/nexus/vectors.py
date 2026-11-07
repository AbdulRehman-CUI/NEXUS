import hashlib
import json
from typing import Protocol


class VectorIndex(Protocol):
    fingerprint: str

    def upsert(self, chunks: list[dict], embeddings: list[list[float]]): ...
    def search(self, workspace_id: str, vector: list[float], limit: int) -> list[tuple[str, float]]: ...
    def delete_document(self, workspace_id: str, document_id: str): ...


class ChromaIndex:
    def __init__(
        self,
        path,
        embedding_fingerprint,
        chunk_size,
        overlap,
        dimension=384,
        namespace=None,
        fingerprint=None,
    ):
        import chromadb
        from chromadb.config import Settings as ChromaSettings
        from llama_index.vector_stores.chroma import ChromaVectorStore

        self.dimension = dimension
        self.configuration = {
            "embedding": embedding_fingerprint,
            "chunk_size": chunk_size,
            "overlap": overlap,
            "parser": "bounded-sentence-v2",
        }
        self.fingerprint = (
            fingerprint
            or hashlib.sha256(json.dumps(self.configuration, sort_keys=True).encode()).hexdigest()[:24]
        )
        self.client = chromadb.PersistentClient(
            path=str(path), settings=ChromaSettings(anonymized_telemetry=False)
        )
        self.collection = self.client.get_or_create_collection(
            namespace or f"nexus_{self.fingerprint}",
            metadata={
                "hnsw:space": "cosine",
                "configuration": json.dumps(self.configuration, sort_keys=True),
                "dimension": dimension,
                "normalization": "l2",
            },
        )
        self.store = ChromaVectorStore(chroma_collection=self.collection)

    def upsert(self, chunks, embeddings):
        from llama_index.core.schema import NodeRelationship, RelatedNodeInfo, TextNode

        if len(chunks) != len(embeddings) or any(len(vector) != self.dimension for vector in embeddings):
            raise ValueError("Vector dimension mismatch; rebuild with a compatible embedding configuration.")
        # Chroma's upsert makes interrupted/repeated jobs idempotent.
        for offset in range(0, len(chunks), 64):
            batch = chunks[offset : offset + 64]
            nodes = [
                TextNode(
                    id_=c["id"],
                    text=c["text"],
                    metadata=c["metadata"],
                    relationships={
                        NodeRelationship.SOURCE: RelatedNodeInfo(node_id=c["metadata"]["document_id"])
                    },
                )
                for c in batch
            ]
            # Use the same node serialization as LlamaIndex's Chroma adapter.
            from llama_index.core.vector_stores.utils import node_to_metadata_dict

            self.collection.upsert(
                ids=[n.node_id for n in nodes],
                documents=[n.text for n in nodes],
                embeddings=embeddings[offset : offset + 64],
                metadatas=[node_to_metadata_dict(n, remove_text=True, flat_metadata=True) for n in nodes],
            )

    def search(self, workspace_id, vector, limit, document_ids=None):
        from llama_index.core.vector_stores import (
            FilterOperator,
            MetadataFilter,
            MetadataFilters,
            VectorStoreQuery,
        )

        if len(vector) != self.dimension:
            raise ValueError("Query embedding dimension does not match index dimension.")
        if document_ids == []:
            return []
        filters = MetadataFilters(
            filters=[
                MetadataFilter(key="workspace_id", value=workspace_id, operator=FilterOperator.EQ),
                MetadataFilter(key="fingerprint", value=self.fingerprint, operator=FilterOperator.EQ),
            ]
        )
        if document_ids is not None:
            filters.filters.append(
                MetadataFilter(key="document_id", value=document_ids, operator=FilterOperator.IN)
            )
        result = self.store.query(
            VectorStoreQuery(query_embedding=vector, similarity_top_k=limit, filters=filters)
        )
        return [
            (node.node_id, 1 - similarity)
            for node, similarity in zip(result.nodes or [], result.similarities or [])
        ]

    def delete_document(self, workspace_id, document_id):
        # Delete across old fingerprints as well, so embedding migrations don't leak vectors.
        for item in self.client.list_collections():
            name = item.name if hasattr(item, "name") else item
            if name.startswith("nexus_"):
                self.client.get_collection(name).delete(
                    where={
                        "$and": [
                            {"workspace_id": {"$eq": workspace_id}},
                            {"document_id": {"$eq": document_id}},
                        ]
                    }
                )


def vector_index(settings, sessions, *args):
    if settings.hosted:
        from .hosted import PostgresIndex

        return PostgresIndex(sessions.kw["bind"], *args)
    return ChromaIndex(settings.data_dir / "chroma", *args)
