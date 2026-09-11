import asyncio
from collections import defaultdict
from collections.abc import Sequence
from typing import cast

import mmh3
import structlog
from shekar import Stemmer, WordTokenizer
from shekar.preprocessing import StopWordRemover

from src.application.exceptions import SparseEmbedderError
from src.application.interfaces.i_sparse_embedder import ISparseEmbedder
from src.domain.entities import SparseVector
from src.infrastructure.configs.settings import BM25Settings
from src.infrastructure.utils import clean_text_for_bm25

_logger = structlog.stdlib.get_logger(__name__)


class PersianBm25Embedder(ISparseEmbedder):
    """
    Persian BM25 Sparse Vector Embedder.

    Produces lexical sparse representations (SparseVector) with unsigned 32-bit
    integer indices (MurmurHash3) compatible with Qdrant's sparse vectors.

    Features & Pipeline:
    1. Pre-sanitizes Markdown and strips URLs to whitespace (preserving Persian ZWNJ \u200c),
       preventing word-fusion and vocabulary pollution.
    2. Applies Shekar's native Persian StopWordRemover.
    3. Tokenizes Persian text into words via Shekar WordTokenizer.
    4. Stems tokens and filters by max token length.
    5. Calculates Term Frequency (TF) saturation weights for documents, matching
       the FastEmbed BM25 specification for Qdrant collections with models.Modifier.IDF.
    6. Produces flat unit weights (1.0) for search queries to enable correct BM25 dot-product scoring.
    7. Executes CPU-bound NLP processing asynchronously on worker threads via asyncio.to_thread.
    """

    def __init__(
        self,
        config: BM25Settings | None = None,
        k: float | None = None,
        b: float | None = None,
        avg_len: float | None = None,
        token_max_length: int | None = None,
    ):
        self.k = k if k is not None else (config.BM25_K if config else 1.2)
        self.b = b if b is not None else (config.BM25_B if config else 0.2)
        self.avg_len = (
            avg_len
            if avg_len is not None
            else (config.BM25_AVG_LEN if config else 256.0)
        )
        self.token_max_length = (
            token_max_length
            if token_max_length is not None
            else (config.BM25_TOKEN_MAX_LENGTH if config else 40)
        )

        self._stop_word_remover = StopWordRemover()
        self._tokenizer = WordTokenizer()
        self._stemmer = Stemmer()

    def _process_text(self, text: str) -> list[str]:
        """
        Cleans, filters stopwords, tokenizes, and stems Persian text.
        """
        if not text or not text.strip():
            return []

        # 1. Clean Markdown and URLs to whitespace (prevents token welding while preserving ZWNJ)
        sanitized_text = clean_text_for_bm25(text)

        # 2. Remove Persian stopwords natively
        cleaned_text = cast(str, self._stop_word_remover.fit_transform(sanitized_text))

        # 3. Tokenize words
        tokens = self._tokenizer.tokenize(cleaned_text)

        # 4. Filter token length and stem
        return [
            stemmed
            for t in tokens
            if len(t) <= self.token_max_length
            if (stemmed := self._stemmer(t))
        ]

    @staticmethod
    def _compute_token_id(token: str) -> int:
        """Computes unsigned 32-bit integer ID for Qdrant sparse vector index."""
        return mmh3.hash(token, signed=False)

    def _calculate_tf(self, tokens: list[str]) -> SparseVector:
        """
        Calculates document Term Frequency (TF) saturation weights.

        Matches the standard BM25 formula without document frequency (IDF),
        designed for vector stores (like Qdrant) that compute IDF on the fly.
        """
        if not tokens:
            return SparseVector(indices=[], values=[])

        counter: dict[str, int] = defaultdict(int)
        for token in tokens:
            counter[token] += 1

        doc_len = len(tokens)
        tf_map: dict[int, float] = {}

        for token, num_occurrences in counter.items():
            token_id = self._compute_token_id(token)
            weight = num_occurrences * (self.k + 1)
            weight /= num_occurrences + self.k * (
                1 - self.b + self.b * doc_len / self.avg_len
            )
            tf_map[token_id] = float(weight)

        return SparseVector.from_dict(tf_map)

    def _embed_document_sync(self, text: str) -> SparseVector:
        tokens = self._process_text(text)
        return self._calculate_tf(tokens)

    def _embed_documents_sync(self, texts: Sequence[str]) -> list[SparseVector]:
        return [self._embed_document_sync(t) for t in texts]

    def _embed_query_sync(self, query: str) -> SparseVector:
        tokens = self._process_text(query)
        if not tokens:
            return SparseVector(indices=[], values=[])

        unique_tokens = set(tokens)
        weight_map = {self._compute_token_id(t): 1.0 for t in unique_tokens}
        return SparseVector.from_dict(weight_map)

    # --- Async Public Interface ---

    async def embed_document(self, text: str) -> SparseVector:
        """
        Generates sparse embedding for a single document chunk asynchronously.
        """
        if not text or not text.strip():
            return SparseVector(indices=[], values=[])

        try:
            return await asyncio.to_thread(self._embed_document_sync, text)
        except Exception as e:
            _logger.error("Failed to generate document sparse embedding", error=str(e))
            raise SparseEmbedderError(
                f"Failed to generate document sparse embedding: {e}"
            ) from e

    async def embed_documents(self, texts: Sequence[str]) -> list[SparseVector]:
        """
        Generates sparse embeddings for a batch of document texts asynchronously.
        """
        if not texts:
            return []

        try:
            return await asyncio.to_thread(self._embed_documents_sync, texts)
        except Exception as e:
            _logger.error("Failed to generate batch sparse embeddings", error=str(e))
            raise SparseEmbedderError(
                f"Failed to generate batch sparse embeddings: {e}"
            ) from e

    async def embed_query(self, query: str) -> SparseVector:
        """
        Generates sparse embedding for a search query string asynchronously.
        """
        if not query or not query.strip():
            return SparseVector(indices=[], values=[])

        try:
            return await asyncio.to_thread(self._embed_query_sync, query)
        except Exception as e:
            _logger.error("Failed to generate query sparse embedding", error=str(e))
            raise SparseEmbedderError(
                f"Failed to generate query sparse embedding: {e}"
            ) from e
