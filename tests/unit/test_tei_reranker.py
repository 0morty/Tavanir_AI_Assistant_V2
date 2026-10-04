import asyncio
import json
import uuid
from typing import Any, cast

import httpx
import pytest
from src.infrastructure.configs.settings import RerankerSettings
from src.infrastructure.services.reranker.tei_reranker import TEIReranker

from src.application.dtos import RerankCandidate
from src.application.exceptions import (
    RerankerAPIError,
    RerankerConfigurationError,
    RerankerConnectionError,
    RerankerInputLimitError,
    RerankerOverloadedError,
    RerankerProtocolError,
    RerankerValidationError,
)


# ---------------------------------------------------------------------------
# Fixtures & Helpers
# ---------------------------------------------------------------------------
def make_settings(**overrides: Any) -> RerankerSettings:
    defaults: dict[str, Any] = {
        "RERANKER_HOST": "localhost",
        "RERANKER_PORT": 8081,
        "RERANKER_API_KEY": "test-key",
        "RERANKER_EXPECTED_MODEL_ID": "BAAI/bge-reranker-v2-m3",
        "RERANKER_CLIENT_BATCH_SIZE": 32,
        "RERANKER_MAX_CONCURRENT_REQUESTS": 4,
        "RERANKER_RAW_SCORES": True,
        "RERANKER_TRUNCATE": True,
        "RERANKER_TRUNCATION_DIRECTION": "Left",
        "RERANKER_CONNECT_TIMEOUT": 1.0,
        "RERANKER_READ_TIMEOUT": 3.0,
        "RERANKER_MAX_RETRIES": 1,
        "RERANKER_RETRY_BASE_DELAY": 0.01,
        "RERANKER_RETRY_MAX_DELAY": 0.05,
        "RERANKER_TRUNCATION_RISK_CHAR_THRESHOLD": 100,
    }
    defaults.update(overrides)
    return RerankerSettings(**defaults)


def make_candidate(
    candidate_id: str | None = None,
    text: str = "نمونه متن آزمایشی",
    rank: int = 1,
    score: float = 0.5,
) -> RerankCandidate:
    return RerankCandidate(
        candidate_id=candidate_id or str(uuid.uuid4()),
        normalized_text=text,
        retrieval_rank=rank,
        retrieval_score=score,
    )


# ---------------------------------------------------------------------------
# 1. Input Validation & Contract Edge Cases
# ---------------------------------------------------------------------------
def test_rerank_candidate_validation_empty_id():
    with pytest.raises(ValueError, match="candidate_id must be non-empty"):
        RerankCandidate(
            candidate_id="   ",
            normalized_text="Valid text",
            retrieval_rank=1,
            retrieval_score=0.5,
        )


def test_rerank_candidate_validation_empty_text():
    with pytest.raises(ValueError, match="normalized_text must be non-empty"):
        RerankCandidate(
            candidate_id=str(uuid.uuid4()),
            normalized_text="  \t \n ",
            retrieval_rank=1,
            retrieval_score=0.5,
        )


def test_rerank_candidate_validation_non_positive_rank():
    with pytest.raises(ValueError, match="retrieval_rank must be positive"):
        RerankCandidate(
            candidate_id=str(uuid.uuid4()),
            normalized_text="Valid text",
            retrieval_rank=0,
            retrieval_score=0.5,
        )


@pytest.mark.asyncio
async def test_reranker_empty_or_whitespace_query():
    settings = make_settings()
    client = httpx.AsyncClient()
    reranker = TEIReranker(
        client=client, settings=settings, semaphore=asyncio.Semaphore(4)
    )

    with pytest.raises(RerankerValidationError) as exc_info:
        await reranker.rerank(normalized_query="   ", candidates=[make_candidate()])
    assert exc_info.value.pointer == "/data/query"
    assert exc_info.value.field_name == "query"

    with pytest.raises(RerankerValidationError) as exc_info_empty:
        await reranker.rerank(normalized_query="", candidates=[make_candidate()])
    assert exc_info_empty.value.pointer == "/data/query"


@pytest.mark.asyncio
async def test_reranker_top_n_non_positive_raises_validation_error():
    settings = make_settings()
    client = httpx.AsyncClient()
    reranker = TEIReranker(
        client=client, settings=settings, semaphore=asyncio.Semaphore(4)
    )

    with pytest.raises(RerankerValidationError) as exc_info_zero:
        await reranker.rerank(
            normalized_query="پرسش تست",
            candidates=[make_candidate()],
            top_n=0,
        )
    assert exc_info_zero.value.pointer == "/data/topN"
    assert exc_info_zero.value.field_name == "top_n"

    with pytest.raises(RerankerValidationError) as exc_info_neg:
        await reranker.rerank(
            normalized_query="پرسش تست",
            candidates=[make_candidate()],
            top_n=-3,
        )
    assert exc_info_neg.value.pointer == "/data/topN"


@pytest.mark.asyncio
async def test_reranker_duplicate_candidates_deduplicated_preserving_first_occurrence(
    capsys,
    caplog,
):
    dup_id = str(uuid.uuid4())
    other_id = str(uuid.uuid4())
    candidates = [
        make_candidate(candidate_id=dup_id, text="متن اول", rank=1, score=0.9),
        make_candidate(candidate_id=other_id, text="متن دوم", rank=2, score=0.7),
        make_candidate(candidate_id=dup_id, text="متن تکراری", rank=5, score=0.3),
    ]

    captured_requests: list[dict[str, Any]] = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.content)
        captured_requests.append(data)
        return httpx.Response(
            200,
            json=[{"index": 0, "score": 2.5}, {"index": 1, "score": 1.2}],
        )

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        reranker = TEIReranker(
            client=client,
            settings=make_settings(),
            semaphore=asyncio.Semaphore(4),
        )
        results = await reranker.rerank(
            normalized_query="پرسش تست", candidates=candidates
        )

    # 1. Exactly 2 unique candidates forwarded to TEI
    assert len(captured_requests) == 1
    assert len(captured_requests[0]["texts"]) == 2
    assert captured_requests[0]["texts"][0] == "متن اول"
    assert captured_requests[0]["texts"][1] == "متن دوم"

    # 2. Results preserve the first candidate occurrence (rank=1, score=0.9)
    assert len(results) == 2
    assert results[0].candidate_id == dup_id
    assert results[0].retrieval_rank == 1
    assert results[0].retrieval_score == 0.9
    assert results[1].candidate_id == other_id

    # 3. Warning log emitted for dropped duplicate
    captured = capsys.readouterr()
    combined_log = captured.out + captured.err + caplog.text
    assert "reranker_duplicate_candidate_dropped" in combined_log


@pytest.mark.asyncio
async def test_reranker_empty_candidates_returns_empty_list():
    settings = make_settings()
    client = httpx.AsyncClient()
    reranker = TEIReranker(
        client=client, settings=settings, semaphore=asyncio.Semaphore(4)
    )

    result = await reranker.rerank(normalized_query="پرسش تستی", candidates=[])
    assert result == []


@pytest.mark.asyncio
async def test_reranker_top_n_none_and_clamping():
    cands = [make_candidate(rank=i) for i in range(1, 6)]

    def mock_handler(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.content)
        texts = data["texts"]
        # Return descending scores: 5.0, 4.0, ...
        return httpx.Response(
            200,
            json=[{"index": i, "score": 10.0 - i} for i in range(len(texts))],
        )

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        reranker = TEIReranker(
            client=client,
            settings=make_settings(),
            semaphore=asyncio.Semaphore(4),
        )

        # top_n = None returns all 5
        res_all = await reranker.rerank("پرسش", cands, top_n=None)
        assert len(res_all) == 5

        # top_n = 20 clamped to 5
        res_clamped = await reranker.rerank("پرسش", cands, top_n=20)
        assert len(res_clamped) == 5

        # top_n = 2 returns top 2
        res_2 = await reranker.rerank("پرسش", cands, top_n=2)
        assert len(res_2) == 2


# ---------------------------------------------------------------------------
# 2. Scoring, Sorting & Deterministic Tie-Breaking
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_reranker_logit_ordering_descending():
    cands = [
        make_candidate(candidate_id="id-1", rank=1),
        make_candidate(candidate_id="id-2", rank=2),
        make_candidate(candidate_id="id-3", rank=3),
    ]

    def mock_handler(request: httpx.Request) -> httpx.Response:
        # Give id-2 highest score, id-3 middle, id-1 lowest
        return httpx.Response(
            200,
            json=[
                {"index": 0, "score": 2.5},
                {"index": 1, "score": 12.0},
                {"index": 2, "score": 6.8},
            ],
        )

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        reranker = TEIReranker(
            client=client,
            settings=make_settings(),
            semaphore=asyncio.Semaphore(4),
        )
        res = await reranker.rerank("پرسش", cands)

        assert [r.candidate_id for r in res] == ["id-2", "id-3", "id-1"]
        assert [r.rerank_score for r in res] == [12.0, 6.8, 2.5]
        assert [r.reranked_rank for r in res] == [1, 2, 3]


@pytest.mark.asyncio
async def test_reranker_deterministic_tie_breaking():
    # id-1 (rank 1) and id-2 (rank 4) both get score 9.5
    cands = [
        make_candidate(candidate_id="cand-rank-4", rank=4),
        make_candidate(candidate_id="cand-rank-1", rank=1),
    ]

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {"index": 0, "score": 9.5},
                {"index": 1, "score": 9.5},
            ],
        )

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        reranker = TEIReranker(
            client=client,
            settings=make_settings(),
            semaphore=asyncio.Semaphore(4),
        )
        res = await reranker.rerank("پرسش", cands)

        # Cand with retrieval_rank 1 must beat rank 4 on equal score
        assert res[0].candidate_id == "cand-rank-1"
        assert res[0].retrieval_rank == 1
        assert res[1].candidate_id == "cand-rank-4"
        assert res[1].retrieval_rank == 4


# ---------------------------------------------------------------------------
# 3. Multi-Batch Mapping & Atomicity
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_reranker_multi_batch_mapping():
    # 65 candidates with batch size 32 = 3 batches (32, 32, 1)
    settings = make_settings(RERANKER_CLIENT_BATCH_SIZE=32)
    cands = [make_candidate(candidate_id=f"c-{i}", rank=i) for i in range(1, 66)]

    def mock_handler(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.content)
        texts = data["texts"]
        # Score is simply descending within the batch
        return httpx.Response(
            200,
            json=[{"index": i, "score": float(100 - i)} for i in range(len(texts))],
        )

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        reranker = TEIReranker(
            client=client, settings=settings, semaphore=asyncio.Semaphore(4)
        )
        res = await reranker.rerank("پرسش", cands)

        assert len(res) == 65
        # Verify all candidates are accounted for uniquely
        returned_ids = {r.candidate_id for r in res}
        assert returned_ids == {f"c-{i}" for i in range(1, 66)}


@pytest.mark.asyncio
async def test_reranker_batch_failure_atomicity():
    # If any batch in a multi-batch request fails, no partial results are returned
    settings = make_settings(RERANKER_CLIENT_BATCH_SIZE=2, RERANKER_MAX_RETRIES=0)
    cands = [
        make_candidate(candidate_id=f"c-{i}", text=f"text-for-c-{i}", rank=i)
        for i in range(1, 5)
    ]

    def mock_handler(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.content)
        # Fail the batch containing text-for-c-3
        if any("text-for-c-3" in t for t in data["texts"]):
            return httpx.Response(500, text="Internal GPU Error")
        return httpx.Response(
            200,
            json=[{"index": 0, "score": 5.0}, {"index": 1, "score": 4.0}],
        )

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        reranker = TEIReranker(
            client=client, settings=settings, semaphore=asyncio.Semaphore(4)
        )

        with pytest.raises(RerankerAPIError):
            await reranker.rerank("پرسش", cands)


# ---------------------------------------------------------------------------
# 4. TEI Protocol & Wire Anomalies
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_reranker_protocol_index_missing():
    cands = [make_candidate(rank=1), make_candidate(rank=2)]

    def mock_handler(request: httpx.Request) -> httpx.Response:
        # Sent 2 items, only returned 1
        return httpx.Response(200, json=[{"index": 0, "score": 5.0}])

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        reranker = TEIReranker(
            client=client,
            settings=make_settings(),
            semaphore=asyncio.Semaphore(4),
        )
        with pytest.raises(RerankerProtocolError, match="Response item count mismatch"):
            await reranker.rerank("پرسش", cands)


@pytest.mark.asyncio
async def test_reranker_protocol_index_duplicate():
    cands = [make_candidate(rank=1), make_candidate(rank=2)]

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[{"index": 0, "score": 5.0}, {"index": 0, "score": 6.0}],
        )

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        reranker = TEIReranker(
            client=client,
            settings=make_settings(),
            semaphore=asyncio.Semaphore(4),
        )
        with pytest.raises(RerankerProtocolError, match="Duplicate index"):
            await reranker.rerank("پرسش", cands)


@pytest.mark.asyncio
async def test_reranker_protocol_index_out_of_bounds():
    cands = [make_candidate(rank=1), make_candidate(rank=2)]

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[{"index": 0, "score": 5.0}, {"index": 5, "score": 6.0}],
        )

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        reranker = TEIReranker(
            client=client,
            settings=make_settings(),
            semaphore=asyncio.Semaphore(4),
        )
        with pytest.raises(RerankerProtocolError, match="out of range"):
            await reranker.rerank("پرسش", cands)


@pytest.mark.asyncio
async def test_reranker_protocol_non_finite_logits():
    cands = [make_candidate(rank=1)]

    def mock_handler_nan(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text='[{"index": 0, "score": NaN}]')

    def mock_handler_inf(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text='[{"index": 0, "score": Infinity}]')

    transport = httpx.MockTransport(mock_handler_nan)
    async with httpx.AsyncClient(transport=transport) as client:
        reranker = TEIReranker(
            client=client,
            settings=make_settings(),
            semaphore=asyncio.Semaphore(4),
        )
        # NaN is either rejected by JSON parser or by float finite validation
        with pytest.raises(RerankerProtocolError):
            await reranker.rerank("پرسش", cands)


@pytest.mark.asyncio
async def test_reranker_error_mapping():
    cands = [make_candidate()]

    async def check_status(status: int, exc_type: type[Exception]):
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(status, text=f"Error {status}")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as cl:
            r = TEIReranker(
                client=cl,
                settings=make_settings(RERANKER_MAX_RETRIES=0),
                semaphore=asyncio.Semaphore(4),
            )
            with pytest.raises(exc_type):
                await r.rerank("پرسش", cands)

    await check_status(401, RerankerConfigurationError)
    await check_status(403, RerankerConfigurationError)
    await check_status(413, RerankerInputLimitError)
    await check_status(422, RerankerInputLimitError)
    await check_status(429, RerankerOverloadedError)
    await check_status(500, RerankerAPIError)
    await check_status(503, RerankerAPIError)


# ---------------------------------------------------------------------------
# 5. Resilience, SLA & Concurrency
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_reranker_timeout_and_retry():
    cands = [make_candidate()]
    attempts = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("Read timed out after 3.0s")

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        reranker = TEIReranker(
            client=client,
            settings=make_settings(RERANKER_MAX_RETRIES=1),
            semaphore=asyncio.Semaphore(4),
        )
        with pytest.raises(
            RerankerConnectionError, match="connection failed after 2 attempts"
        ):
            await reranker.rerank("پرسش", cands)

        assert attempts == 2


@pytest.mark.asyncio
async def test_reranker_transient_retry_success():
    cands = [make_candidate()]
    attempts = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(502, text="Bad Gateway")
        return httpx.Response(200, json=[{"index": 0, "score": 8.0}])

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        reranker = TEIReranker(
            client=client,
            settings=make_settings(RERANKER_MAX_RETRIES=1),
            semaphore=asyncio.Semaphore(4),
        )
        res = await reranker.rerank("پرسش", cands)
        assert len(res) == 1
        assert res[0].rerank_score == 8.0
        assert attempts == 2


@pytest.mark.asyncio
async def test_reranker_cancelled_error_propagation():
    cands = [make_candidate()]

    def mock_handler(request: httpx.Request) -> httpx.Response:
        raise asyncio.CancelledError()

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        reranker = TEIReranker(
            client=client,
            settings=make_settings(),
            semaphore=asyncio.Semaphore(4),
        )
        with pytest.raises(asyncio.CancelledError):
            await reranker.rerank("پرسش", cands)


# ---------------------------------------------------------------------------
# 6. Observability & Security (Zero Leakage)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_reranker_truncation_heuristic_warning(capsys, caplog):
    # Threshold is 50 chars; query + text = 60 chars
    settings = make_settings(RERANKER_TRUNCATION_RISK_CHAR_THRESHOLD=50)
    cands = [
        make_candidate(
            candidate_id="cand-warn",
            text="این متن طولانی آزمایشی برای هشدار کوتاه سازی است",
        )
    ]

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"index": 0, "score": 5.0}])

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        reranker = TEIReranker(
            client=client, settings=settings, semaphore=asyncio.Semaphore(4)
        )
        await reranker.rerank("عنوان پرسش تستی با طول نسبتا بلند", cands)

    captured = capsys.readouterr()
    combined_log = captured.out + captured.err + caplog.text
    assert "reranker_truncation_risk_detected" in combined_log


@pytest.mark.asyncio
async def test_reranker_zero_log_leakage(capsys, caplog):
    # Verify that neither query nor document content leaks into log output even on error
    secret_query = "TOP_SECRET_USER_SUGGESTION_QUERY"
    secret_chunk = "HIGHLY_CONFIDENTIAL_CHUNK_PAYLOAD"
    cands = [make_candidate(text=secret_chunk)]

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        reranker = TEIReranker(
            client=client,
            settings=make_settings(RERANKER_MAX_RETRIES=0),
            semaphore=asyncio.Semaphore(4),
        )
        with pytest.raises(RerankerAPIError):
            await reranker.rerank(secret_query, cands)

    captured = capsys.readouterr()
    combined_log = captured.out + captured.err + caplog.text
    assert secret_query not in combined_log
    assert secret_chunk not in combined_log


# ---------------------------------------------------------------------------
# 7. Probe Health Check
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_probe_health_success():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/info":
            return httpx.Response(
                200,
                json={
                    "model_id": "BAAI/bge-reranker-v2-m3",
                    "max_client_batch_size": 32,
                    "dtype": "float16",
                },
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        reranker = TEIReranker(
            client=client,
            settings=make_settings(),
            semaphore=asyncio.Semaphore(4),
        )
        health = await reranker.probe_health()
        assert health["status"] == "healthy"
        assert health["model_id"] == "BAAI/bge-reranker-v2-m3"


@pytest.mark.asyncio
async def test_probe_health_model_mismatch():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model_id": "google/embedding-gemma-2b",  # Wrong model
                "max_client_batch_size": 32,
            },
        )

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        reranker = TEIReranker(
            client=client,
            settings=make_settings(),
            semaphore=asyncio.Semaphore(4),
        )
        with pytest.raises(RerankerConfigurationError, match="model mismatch"):
            await reranker.probe_health()


@pytest.mark.asyncio
async def test_probe_health_batch_size_mismatch():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model_id": "BAAI/bge-reranker-v2-m3",
                "max_client_batch_size": 16,  # Smaller than app's 32
            },
        )

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        reranker = TEIReranker(
            client=client,
            settings=make_settings(RERANKER_CLIENT_BATCH_SIZE=32),
            semaphore=asyncio.Semaphore(4),
        )
        with pytest.raises(RerankerConfigurationError, match="max_client_batch_size"):
            await reranker.probe_health()


# ---------------------------------------------------------------------------
# 8. Container DI Wiring Test
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_container_reranker_wiring():
    from unittest.mock import MagicMock

    from src.containers import Container

    container = Container()
    container.tokenizer.override(MagicMock())
    container.arq_redis_pool.override(MagicMock())
    await cast(Any, container.init_resources())
    try:
        reranker = await cast(Any, container.reranker())
        assert isinstance(reranker, TEIReranker)
        assert reranker._client is not None
        assert reranker._semaphore is not None
        assert reranker._settings is not None
    finally:
        await cast(Any, container.shutdown_resources())
