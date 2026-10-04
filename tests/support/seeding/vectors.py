"""Deterministic and live vector generators for test database seeding.

Provides:
- DeterministicVectorGenerator: Generates 768-dimensional dense vectors with mathematically
  guaranteed cosine similarity profiles (cos_sim > 0.82 within cluster, cos_sim < 0.20 across
  different clusters) and real Persian sparse BM25 vectors via PersianBm25Embedder without
  network calls.
- LiveVectorGenerator: Wraps OpenAIDenseEmbedder and PersianBm25Embedder for live TEI embedding
  when --live-embeddings is passed.
"""

from __future__ import annotations

import hashlib
from typing import Protocol

import numpy as np

from src.application.interfaces.i_dense_embedder import IDenseEmbedder
from src.application.interfaces.i_sparse_embedder import ISparseEmbedder
from src.domain.entities import SparseVector
from src.infrastructure.services.embeddings.persian_bm25_embedder import (
    PersianBm25Embedder,
)
from tests.support.seeding.corpus import CLUSTERS


class IVectorGenerator(Protocol):
    """Protocol for vector generation during test database seeding and benchmarking."""

    async def generate_chunk_vectors(
        self, content: str, cluster: str, chunk_id: str
    ) -> tuple[list[float], SparseVector]:
        """Generates (dense_vector, sparse_vector) for a document/suggestion chunk."""
        ...

    async def generate_query_vectors(
        self, query_text: str, target_cluster: str
    ) -> tuple[list[float], SparseVector]:
        """Generates (dense_vector, sparse_vector) for a search/benchmark query."""
        ...

    def get_cluster_centroid(self, cluster: str) -> list[float]:
        """Returns the base 768-dimensional unit centroid vector for a given cluster."""
        ...


class DeterministicVectorGenerator:
    """
    Offline deterministic vector generator.

    Dense vectors:
    - 768-dimensional unit hypersphere.
    - Each semantic cluster occupies an orthogonal coordinate subspace.
    - Base centroids are orthogonal unit vectors across clusters (cos_sim = 0.0 < 0.20).
    - Chunk perturbations are strictly confined to their cluster subspace with alpha=0.96,
      guaranteeing cos_sim >= 0.8432 > 0.82 for any two items in the same cluster,
      and cos_sim = 0.96 for queries against member chunks.
    - Vectors are fully deterministic and reproducible using SHA-256 seeding.

    Sparse vectors:
    - Real local Persian BM25 lexical vectors via PersianBm25Embedder without network requests.
    """

    DEFAULT_ALPHA: float = 0.96  # Guarantees min intra-cluster cos_sim = 2*alpha^2 - 1 = 0.8432 > 0.82

    def __init__(
        self,
        dimension: int = 768,
        sparse_embedder: ISparseEmbedder | None = None,
        alpha: float = DEFAULT_ALPHA,
    ) -> None:
        self.dimension = dimension
        self.alpha = alpha
        self._beta = float(np.sqrt(1.0 - alpha**2))
        self._sparse_embedder = sparse_embedder or PersianBm25Embedder()
        self._cluster_map = {cluster: idx for idx, cluster in enumerate(CLUSTERS)}
        self._centroids = self._initialize_centroids()

    def _get_slice(self, cluster_idx: int) -> tuple[int, int]:
        num_clusters = len(CLUSTERS)
        slice_len = self.dimension // num_clusters
        start = cluster_idx * slice_len
        end = self.dimension if cluster_idx == num_clusters - 1 else (cluster_idx + 1) * slice_len
        return start, end

    def _initialize_centroids(self) -> dict[str, np.ndarray]:
        centroids: dict[str, np.ndarray] = {}
        for cluster, idx in self._cluster_map.items():
            start, end = self._get_slice(idx)
            c = np.zeros(self.dimension, dtype=np.float32)
            c[start:end] = 1.0 / np.sqrt(end - start)
            centroids[cluster] = c
        return centroids

    def get_cluster_centroid(self, cluster: str) -> list[float]:
        if cluster not in self._centroids:
            raise KeyError(f"Unknown semantic cluster: '{cluster}'. Valid clusters: {CLUSTERS}")
        return self._centroids[cluster].tolist()

    def _generate_dense_vector(self, cluster: str, seed_text: str) -> list[float]:
        if cluster not in self._centroids:
            raise KeyError(f"Unknown semantic cluster: '{cluster}'. Valid clusters: {CLUSTERS}")

        cluster_idx = self._cluster_map[cluster]
        start, end = self._get_slice(cluster_idx)
        slice_dim = end - start
        centroid = self._centroids[cluster]

        # Deterministic 64-bit integer seed from SHA-256
        seed_hash = hashlib.sha256(f"{cluster}:{seed_text}".encode("utf-8")).hexdigest()
        seed_int = int(seed_hash[:16], 16)
        rng = np.random.default_rng(seed_int)

        # Generate subspace perturbation
        raw_perturb = rng.standard_normal(slice_dim).astype(np.float32)
        perturb_full = np.zeros(self.dimension, dtype=np.float32)
        perturb_full[start:end] = raw_perturb

        # Gram-Schmidt orthogonalization against centroid
        proj = float(np.dot(perturb_full, centroid))
        ortho_perturb = perturb_full - proj * centroid
        norm = float(np.linalg.norm(ortho_perturb))
        if norm > 1e-8:
            ortho_perturb /= norm
        else:
            ortho_perturb = np.zeros(self.dimension, dtype=np.float32)

        # Combine centroid + perturbation
        vector = self.alpha * centroid + self._beta * ortho_perturb
        vector_norm = float(np.linalg.norm(vector))
        if vector_norm > 1e-8:
            vector /= vector_norm

        return vector.tolist()

    async def generate_chunk_vectors(
        self, content: str, cluster: str, chunk_id: str
    ) -> tuple[list[float], SparseVector]:
        dense = self._generate_dense_vector(cluster, seed_text=chunk_id)
        sparse = await self._sparse_embedder.embed_document(content)
        return dense, sparse

    async def generate_query_vectors(
        self, query_text: str, target_cluster: str
    ) -> tuple[list[float], SparseVector]:
        # For query dense vectors, use cluster centroid with a very slight perturbation (or direct centroid)
        dense = self.get_cluster_centroid(target_cluster)
        sparse = await self._sparse_embedder.embed_query(query_text)
        return dense, sparse


class LiveVectorGenerator:
    """
    Live vector generator wrapping OpenAIDenseEmbedder and PersianBm25Embedder.

    Used when --live-embeddings is passed to run inference through live TEI endpoints.
    """

    def __init__(
        self,
        dense_embedder: IDenseEmbedder,
        sparse_embedder: ISparseEmbedder | None = None,
    ) -> None:
        self._dense_embedder = dense_embedder
        self._sparse_embedder = sparse_embedder or PersianBm25Embedder()

    def get_cluster_centroid(self, cluster: str) -> list[float]:
        # Centroids are not pre-computed in live TEI mode; returns unit zero vector
        dim = self._dense_embedder.embedding_dimension
        return [0.0] * dim

    async def generate_chunk_vectors(
        self, content: str, cluster: str, chunk_id: str
    ) -> tuple[list[float], SparseVector]:
        dense_results = await self._dense_embedder.embed_documents([content])
        dense = dense_results[0] if dense_results else [0.0] * self._dense_embedder.embedding_dimension
        sparse = await self._sparse_embedder.embed_document(content)
        return dense, sparse

    async def generate_query_vectors(
        self, query_text: str, target_cluster: str
    ) -> tuple[list[float], SparseVector]:
        dense = await self._dense_embedder.embed_query(query_text)
        sparse = await self._sparse_embedder.embed_query(query_text)
        return dense, sparse
