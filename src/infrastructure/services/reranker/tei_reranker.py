import asyncio
import math
import random
from collections.abc import Sequence
from typing import Any

import httpx
import structlog

from src.application.dtos import RerankCandidate, RerankedCandidate
from src.application.exceptions import (
    RerankerAPIError,
    RerankerBaseError,
    RerankerConfigurationError,
    RerankerConnectionError,
    RerankerInputLimitError,
    RerankerOverloadedError,
    RerankerProtocolError,
    RerankerValidationError,
)
from src.application.interfaces.i_reranker import IReranker
from src.infrastructure.configs.settings import RerankerSettings

_logger = structlog.stdlib.get_logger(__name__)


class TEIReranker(IReranker):
    """
    Production-grade infrastructure adapter for Hugging Face Text Embeddings Inference (TEI)
    serving cross-encoder rerankers (e.g. BAAI/bge-reranker-v2-m3).

    Responsibilities:
    - Pure application port implementation (IReranker).
    - Client-side candidate validation and in-flight deduplication (preserving first occurrence).
    - Truncation risk heuristic diagnostics without logging sensitive text.
    - Chunking into sub-batches bounded by TEI's MAX_CLIENT_BATCH_SIZE (32).
    - Concurrent batch execution via asyncio.gather() under a shared Semaphore.
    - Strict SLA timeouts (1s connect, 3s read) and bounded retries with jitter.
    - Wire protocol validation: missing/duplicate indices, count mismatch, non-finite logits.
    - Global stable sorting by raw cross-encoder logits descending, breaking ties by retrieval_rank.
    - Non-startup-blocking /info health and configuration-drift probe.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        settings: RerankerSettings,
        semaphore: asyncio.Semaphore,
    ) -> None:
        self._client = client
        self._settings = settings
        self._semaphore = semaphore

    async def rerank(
        self,
        normalized_query: str,
        candidates: Sequence[RerankCandidate],
        *,
        top_n: int | None = None,
    ) -> list[RerankedCandidate]:
        """
        Reranks retrieved candidates against a pre-normalized query.
        """
        # 1. Validate query
        if not normalized_query or not normalized_query.strip():
            raise RerankerValidationError(
                "normalized_query must be non-empty.",
                pointer="/data/query",
                field_name="query",
            )

        # 2. Empty candidates return immediately without network overhead
        if not candidates:
            return []

        # 3. Deduplicate candidates in-flight (preserving first occurrence)
        unique_candidates: list[RerankCandidate] = []
        seen_ids: set[str] = set()
        for cand in candidates:
            if cand.candidate_id in seen_ids:
                _logger.warning(
                    "reranker_duplicate_candidate_dropped",
                    candidate_id=cand.candidate_id,
                    duplicate_retrieval_rank=cand.retrieval_rank,
                    duplicate_retrieval_score=cand.retrieval_score,
                )
                continue
            seen_ids.add(cand.candidate_id)
            unique_candidates.append(cand)

        if top_n is not None:
            if top_n <= 0:
                raise RerankerValidationError(
                    "top_n must be positive.",
                    pointer="/data/topN",
                    field_name="top_n",
                )
            effective_top_n = min(top_n, len(unique_candidates))
        else:
            effective_top_n = len(unique_candidates)

        # 4. Truncation risk heuristic diagnostics (zero text content logging)
        query_len = len(normalized_query)
        threshold = self._settings.RERANKER_TRUNCATION_RISK_CHAR_THRESHOLD
        for cand in unique_candidates:
            total_chars = query_len + len(cand.normalized_text)
            if total_chars > threshold:
                _logger.warning(
                    "reranker_truncation_risk_detected",
                    candidate_id=cand.candidate_id,
                    total_chars=total_chars,
                    threshold=threshold,
                )

        # 5. Partition into client sub-batches (default 32)
        batch_size = max(1, self._settings.RERANKER_CLIENT_BATCH_SIZE)
        sub_batches = [
            unique_candidates[i : i + batch_size]
            for i in range(0, len(unique_candidates), batch_size)
        ]

        # 6. Execute sub-batches concurrently via asyncio.gather under semaphore
        tasks = [
            self._execute_batch_with_semaphore(normalized_query, batch)
            for batch in sub_batches
        ]
        batch_results = await asyncio.gather(*tasks)

        # 7. Flatten all scored candidate pairs
        all_scored: list[tuple[RerankCandidate, float]] = []
        for batch_result in batch_results:
            all_scored.extend(batch_result)

        if len(all_scored) != len(unique_candidates):
            raise RerankerProtocolError(
                f"Aggregated response count mismatch: expected {len(unique_candidates)}, got {len(all_scored)}"
            )

        # 8. Global stable sort: raw logits descending, tie-break by retrieval_rank ascending
        all_scored.sort(key=lambda item: (-item[1], item[0].retrieval_rank))

        # 9. Slice top_n and construct final DTOs
        sliced = all_scored[:effective_top_n]
        return [
            RerankedCandidate(
                candidate_id=cand.candidate_id,
                retrieval_rank=cand.retrieval_rank,
                retrieval_score=cand.retrieval_score,
                rerank_score=score,
                reranked_rank=rank,
            )
            for rank, (cand, score) in enumerate(sliced, start=1)
        ]

    async def _execute_batch_with_semaphore(
        self, normalized_query: str, batch: Sequence[RerankCandidate]
    ) -> list[tuple[RerankCandidate, float]]:
        """Acquires a concurrency slot from the shared semaphore and executes the batch."""
        async with self._semaphore:
            return await self._execute_batch(normalized_query, batch)

    async def _execute_batch(
        self, normalized_query: str, batch: Sequence[RerankCandidate]
    ) -> list[tuple[RerankCandidate, float]]:
        """Sends a single sub-batch to TEI with SLA-bounded retry policy."""
        url = f"{self._settings.RERANKER_BASE_URL.rstrip('/')}/rerank"
        headers = {"Content-Type": "application/json"}
        if (
            self._settings.RERANKER_API_KEY
            and self._settings.RERANKER_API_KEY != "EMPTY"
        ):
            headers["Authorization"] = f"Bearer {self._settings.RERANKER_API_KEY}"

        payload: dict[str, Any] = {
            "query": normalized_query,
            "texts": [c.normalized_text for c in batch],
            "raw_scores": self._settings.RERANKER_RAW_SCORES,
            "return_text": False,
            "truncate": self._settings.RERANKER_TRUNCATE,
            "truncation_direction": self._settings.RERANKER_TRUNCATION_DIRECTION,
        }

        max_attempts = max(1, self._settings.RERANKER_MAX_RETRIES + 1)
        last_error: Exception | None = None

        for attempt in range(max_attempts):
            try:
                response = await self._client.post(
                    url,
                    json=payload,
                    headers=headers,
                )

                if response.is_success:
                    return self._parse_batch_response(response, batch)

                status = response.status_code
                response_text = response.text

                # Unrecoverable configuration / auth failures
                if status in (401, 403):
                    raise RerankerConfigurationError(
                        f"Reranker authentication failed ({status}): {response_text}"
                    )

                # Payload / length limit errors
                if status in (413, 422):
                    raise RerankerInputLimitError(
                        f"Reranker input limit exceeded ({status}): {response_text}",
                        status_code=status,
                    )

                # Rate limiting (429)
                if status == 429:
                    retry_after_hdr = response.headers.get("Retry-After")
                    delay = (
                        float(retry_after_hdr)
                        if retry_after_hdr and retry_after_hdr.isdigit()
                        else self._calculate_backoff(attempt)
                    )
                    if attempt < max_attempts - 1:
                        await asyncio.sleep(delay)
                        continue
                    raise RerankerOverloadedError(
                        f"Reranker rate limit exhausted ({status}): {response_text}",
                        status_code=429,
                        retry_after=delay,
                    )

                # Upstream server errors (5xx)
                if status >= 500:
                    if attempt < max_attempts - 1:
                        await asyncio.sleep(self._calculate_backoff(attempt))
                        continue
                    raise RerankerAPIError(
                        f"Reranker upstream server error ({status}): {response_text}",
                        status_code=status,
                    )

                # Any other non-success status
                raise RerankerAPIError(
                    f"Reranker unexpected HTTP status ({status}): {response_text}",
                    status_code=status,
                )

            except asyncio.CancelledError:
                # Do not catch or retry task cancellations
                raise

            except (RerankerBaseError, ValueError):
                # Application errors propagate without retrying
                raise

            except (httpx.TimeoutException, httpx.NetworkError) as e:
                last_error = e
                if attempt < max_attempts - 1:
                    await asyncio.sleep(self._calculate_backoff(attempt))
                    continue

                raise RerankerConnectionError(
                    f"Reranker connection failed after {attempt + 1} attempts: {e}"
                ) from e

            except Exception as e:
                raise RerankerAPIError(f"Unexpected reranker error: {e}") from e

        if last_error:
            raise RerankerConnectionError(
                f"Reranker exhausted retries: {last_error}"
            ) from last_error

        raise RerankerAPIError("Reranker batch execution terminated unexpectedly.")

    def _parse_batch_response(
        self, response: httpx.Response, batch: Sequence[RerankCandidate]
    ) -> list[tuple[RerankCandidate, float]]:
        """Parses and strictly validates TEI /rerank response format."""
        try:
            data = response.json()
        except Exception as e:
            raise RerankerProtocolError(
                f"Malformed JSON in TEI /rerank response: {e}"
            ) from e

        if not isinstance(data, list):
            raise RerankerProtocolError(
                f"Expected JSON list from TEI /rerank, got {type(data).__name__}"
            )

        if len(data) != len(batch):
            raise RerankerProtocolError(
                f"Response item count mismatch: sent {len(batch)}, received {len(data)}"
            )

        seen_indices: set[int] = set()
        indexed_scores: list[tuple[RerankCandidate, float]] = []

        for item in data:
            if not isinstance(item, dict):
                raise RerankerProtocolError(
                    f"Expected dictionary per score item, got {type(item).__name__}"
                )

            if "index" not in item or "score" not in item:
                raise RerankerProtocolError(
                    "Missing 'index' or 'score' in TEI rerank response item"
                )

            idx = item["index"]
            score = item["score"]

            if not isinstance(idx, int) or isinstance(idx, bool):
                raise RerankerProtocolError(
                    f"Invalid index type in response: {type(idx).__name__}"
                )

            if idx < 0 or idx >= len(batch):
                raise RerankerProtocolError(
                    f"Index {idx} out of range for batch size {len(batch)}"
                )

            if idx in seen_indices:
                raise RerankerProtocolError(
                    f"Duplicate index {idx} detected in TEI response"
                )

            seen_indices.add(idx)

            if not isinstance(score, (int, float)) or isinstance(score, bool):
                raise RerankerProtocolError(
                    f"Invalid score type at index {idx}: {type(score).__name__}"
                )

            score_float = float(score)
            if math.isnan(score_float) or math.isinf(score_float):
                raise RerankerProtocolError(
                    f"Non-finite score value at index {idx}: {score}"
                )

            indexed_scores.append((batch[idx], score_float))

        if len(seen_indices) != len(batch):
            raise RerankerProtocolError(
                f"Index coverage mismatch: received {len(seen_indices)} unique indices for {len(batch)} items"
            )

        return indexed_scores

    def _calculate_backoff(self, attempt: int) -> float:
        """Calculates exponential backoff with random jitter bounded by settings."""
        base = self._settings.RERANKER_RETRY_BASE_DELAY * (2**attempt)
        jitter = random.uniform(0.0, 0.05)
        return min(base + jitter, self._settings.RERANKER_RETRY_MAX_DELAY)

    async def probe_health(self) -> dict[str, Any]:
        """
        Non-blocking health probe inspecting TEI's GET /info endpoint.
        Validates model identity and deployment limit compatibility.
        """
        url = f"{self._settings.RERANKER_BASE_URL.rstrip('/')}/info"
        headers: dict[str, str] = {}
        if (
            self._settings.RERANKER_API_KEY
            and self._settings.RERANKER_API_KEY != "EMPTY"
        ):
            headers["Authorization"] = f"Bearer {self._settings.RERANKER_API_KEY}"

        try:
            response = await self._client.get(
                url,
                headers=headers,
                timeout=httpx.Timeout(connect=1.0, read=2.0, write=1.0, pool=1.0),
            )

            if not response.is_success:
                raise RerankerAPIError(
                    f"TEI /info returned status {response.status_code}: {response.text}",
                    status_code=response.status_code,
                )

            data = response.json()
            served_model = data.get("model_id")

            # Check model mismatch
            if served_model != self._settings.RERANKER_EXPECTED_MODEL_ID:
                raise RerankerConfigurationError(
                    f"TEI served model mismatch: expected '{self._settings.RERANKER_EXPECTED_MODEL_ID}', "
                    f"got '{served_model}'"
                )

            # Check batch size limit compatibility
            server_max_batch = data.get("max_client_batch_size")
            if (
                server_max_batch is not None
                and server_max_batch < self._settings.RERANKER_CLIENT_BATCH_SIZE
            ):
                raise RerankerConfigurationError(
                    f"TEI max_client_batch_size ({server_max_batch}) is less than configured "
                    f"RERANKER_CLIENT_BATCH_SIZE ({self._settings.RERANKER_CLIENT_BATCH_SIZE})"
                )

            return {
                "status": "healthy",
                "model_id": served_model,
                "max_client_batch_size": server_max_batch,
                "dtype": data.get("dtype"),
            }

        except (RerankerBaseError, ValueError):
            raise

        except (httpx.TimeoutException, httpx.NetworkError) as e:
            raise RerankerConnectionError(f"Failed to connect to TEI /info: {e}") from e

        except Exception as e:
            raise RerankerAPIError(f"Unexpected error querying TEI /info: {e}") from e
