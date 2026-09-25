from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from src.containers import Container
from src.infrastructure.configs.settings import security_settings

from src.application.dtos import AnalyzeSuggestionResponse
from src.main import app


@pytest.fixture
def api_headers() -> dict[str, str]:
    return {
        security_settings.API_KEY_NAME: security_settings.API_KEY,
        "Content-Type": "application/json",
    }


@pytest.fixture
def valid_analyze_payload() -> dict[str, str]:
    return {
        "title": "بهینه‌سازی مصرف انرژی در شبکه‌های توزیع برق",
        "currentProblem": "فرسودگی ترانس‌ها و افزایش تلفات حرارتی در مناطق گرمسیری",
        "solution": "استفاده از ترانسفورماتورهای فوق‌کم‌تلفات و سیستم خنک‌سازی پیشرفته",
        "contextTitle": "معاونت مهندسی و توزیع",
    }


@pytest.fixture(autouse=True)
def setup_container():
    container = Container()
    container.wire(packages=["src.presentation.routers"])
    yield container
    container.unwire()


@pytest.mark.asyncio
async def test_analyze_suggestion_missing_api_key(valid_analyze_payload):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/suggestions/analyze", json=valid_analyze_payload
        )
        assert response.status_code == 401
        data = response.json()
        assert data["errors"][0]["code"] == "API_KEY_MISSING"


@pytest.mark.asyncio
async def test_analyze_suggestion_invalid_api_key(valid_analyze_payload):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/suggestions/analyze",
            json=valid_analyze_payload,
            headers={security_settings.API_KEY_NAME: "wrong-api-key"},
        )
        assert response.status_code == 401
        data = response.json()
        assert data["errors"][0]["code"] == "API_KEY_INVALID"


@pytest.mark.asyncio
async def test_analyze_suggestion_success_200(
    setup_container, api_headers, valid_analyze_payload
):
    mock_use_case = AsyncMock()
    mock_use_case.execute.return_value = AnalyzeSuggestionResponse(
        analysis="## گزارش تحلیلی\n\nپیشنهادات مشابه استخراج شدند.",
        similar_executed_ids=["SUG-100", "SUG-101"],
        similar_approved_ids=["SUG-200"],
        similar_pending_ids=["SUG-300"],
        similar_rejected_ids=["SUG-400"],
        similar_not_accepted_ids=["SUG-500"],
        applied_statute_ids=[],
    )

    with setup_container.analyze_suggestion_use_case.override(mock_use_case):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/suggestions/analyze",
                json=valid_analyze_payload,
                headers=api_headers,
            )

            assert response.status_code == 200
            body = response.json()
            assert body["status"] == 200
            assert body["data"] == {
                "analysis": "## گزارش تحلیلی\n\nپیشنهادات مشابه استخراج شدند.",
                "similarExecutedIds": ["SUG-100", "SUG-101"],
                "similarApprovedIds": ["SUG-200"],
                "similarPendingIds": ["SUG-300"],
                "similarRejectedIds": ["SUG-400"],
                "similarNotAcceptedIds": ["SUG-500"],
                "appliedStatuteIds": [],
            }
            mock_use_case.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_analyze_suggestion_validation_error_noise_placeholder(
    setup_container, api_headers
):
    payload = {
        "title": "عنوان پیشنهاد معتبر و دقیق",
        "currentProblem": "ندارد",  # Noise placeholder
        "solution": "ارائه راهکار مهندسی دقیق برای حل مشکل",
    }
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/suggestions/analyze",
            json=payload,
            headers=api_headers,
        )
        assert response.status_code == 422
        body = response.json()
        assert "errors" in body
        error = body["errors"][0]
        assert error["code"] == "INVALID_SUGGESTION_CONTENT"
        assert error["source"]["pointer"] == "/data/currentProblem"


@pytest.mark.asyncio
async def test_analyze_suggestion_extra_fields_forbidden(setup_container, api_headers):
    payload = {
        "title": "عنوان معتبر برای پیشنهاد",
        "currentProblem": "شرح دقیق مسئله و مشکل",
        "solution": "راهکار اجرایی و مهندسی",
        "extraForbiddenField": "not_allowed",
    }
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/suggestions/analyze",
            json=payload,
            headers=api_headers,
        )
        assert response.status_code == 422
        body = response.json()
        assert "errors" in body
        assert any(
            "extraForbiddenField" in str(e) or e["code"] == "UNPROCESSABLE_ENTITY"
            for e in body["errors"]
        )
