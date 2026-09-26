import os
import uuid

import httpx
import pytest
from src.infrastructure.configs.settings import RerankerSettings
from src.infrastructure.services.reranker.tei_reranker import TEIReranker

from src.application.dtos import RerankCandidate

# This test requires a running TEI container serving BAAI/bge-reranker-v2-m3
pytestmark = pytest.mark.skipif(
    os.getenv("TEST_TEI_LIVE") != "true",
    reason="Skipped: live TEI reranker container not available or TEST_TEI_LIVE != true",
)


@pytest.mark.asyncio
async def test_tei_reranker_live_probe_and_scoring():
    settings = RerankerSettings(
        RERANKER_HOST="localhost",
        RERANKER_PORT=8081,
        RERANKER_EXPECTED_MODEL_ID="BAAI/bge-reranker-v2-m3",
    )

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=2.0, read=5.0)
    ) as client:
        import asyncio

        reranker = TEIReranker(
            client=client,
            settings=settings,
            semaphore=asyncio.Semaphore(4),
        )

        # 1. Health Probe Check
        health = await reranker.probe_health()
        assert health["status"] == "healthy"
        assert health["model_id"] == "BAAI/bge-reranker-v2-m3"

        # 2. Real Persian Reranking Scoring
        query = "تعویض مقره‌های سیلیکونی خط ۴۰۰ کیلوولت"
        candidates = [
            RerankCandidate(
                candidate_id=str(uuid.uuid4()),
                normalized_text="تعویض و شستشوی مقره‌های خطوط انتقال فشار قوی و فوق توزیع",
                retrieval_rank=1,
                retrieval_score=0.03,
            ),
            RerankCandidate(
                candidate_id=str(uuid.uuid4()),
                normalized_text="دستورالعمل اداری مرخصی کارکنان شرکت توزیع نیروی برق",
                retrieval_rank=2,
                retrieval_score=0.02,
            ),
        ]

        results = await reranker.rerank(query, candidates, top_n=2)
        assert len(results) == 2
        # The electrical insulator candidate should score much higher than staff leave rules
        assert results[0].candidate_id == candidates[0].candidate_id
        assert results[0].rerank_score > results[1].rerank_score
