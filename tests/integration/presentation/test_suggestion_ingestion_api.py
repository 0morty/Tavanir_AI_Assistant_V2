from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from src.containers import Container
from src.infrastructure.configs.settings import security_settings

from src.application.dtos import IngestSuggestionResponseDTO
from src.domain.exceptions import (
    InvalidSuggestionContentError,
    SuggestionAlreadyExistsError,
)
from src.main import app


@pytest.fixture
def api_headers():
    return {
        security_settings.API_KEY_NAME: security_settings.API_KEY,
        "Content-Type": "application/json",
    }


@pytest.fixture
def valid_payload():
    return {
        "suggestionId": "sugg-api-101",
        "title": "بهینه‌سازی مصرف انرژی در تاسیسات",
        "problem": "مصرف بالای انرژی به دلیل فرسودگی تجهیزات روشنایی و سرمایشی",
        "solution": "نصب سیستم‌های هوشمند کنترل مصرف و تعویض لامپ‌ها با انواع ال‌ای‌دی",
        "status": "مصوب",
        "scrutiny": "تایید شده توسط کمیته بهینه‌سازی مصرف",
        "description": "دستور تخصیص بودجه اولیه صادر گردید",
        "shamsiDate": "۱۴۰۲/۰۶/۱۵",
        "contextTitle": "مدیریت توزیع برق",
    }


@pytest.fixture(autouse=True)
def setup_container():
    container = Container()
    container.wire(packages=["src.presentation.routers"])
    yield container
    container.unwire()


@pytest.mark.asyncio
async def test_ingest_suggestion_missing_api_key(valid_payload):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/suggestions/ingest", json=valid_payload)
        assert response.status_code == 401
        data = response.json()
        assert data["errors"][0]["code"] == "API_KEY_MISSING"


@pytest.mark.asyncio
async def test_ingest_suggestion_invalid_api_key(valid_payload):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/suggestions/ingest",
            json=valid_payload,
            headers={security_settings.API_KEY_NAME: "wrong-key"},
        )
        assert response.status_code == 401
        data = response.json()
        assert data["errors"][0]["code"] == "API_KEY_INVALID"


@pytest.mark.asyncio
async def test_ingest_suggestion_success_201(
    setup_container, api_headers, valid_payload
):
    mock_use_case = AsyncMock()
    mock_use_case.execute.return_value = IngestSuggestionResponseDTO(
        suggestion_id="sugg-api-101",
        chunks_count=4,
        status="CREATED",
    )

    with setup_container.ingest_suggestion_use_case.override(mock_use_case):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/suggestions/ingest",
                json=valid_payload,
                headers=api_headers,
            )

            assert response.status_code == 201
            data = response.json()
            assert data["status"] == 201
            assert data["data"] == {
                "suggestionId": "sugg-api-101",
                "chunksCount": 4,
                "status": "CREATED",
            }
            mock_use_case.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_ingest_suggestion_conflict_409(
    setup_container, api_headers, valid_payload
):
    mock_use_case = AsyncMock()
    mock_use_case.execute.side_effect = SuggestionAlreadyExistsError(
        "Suggestion with ID 'sugg-api-101' already exists.",
        pointer="/data/suggestionId",
    )

    with setup_container.ingest_suggestion_use_case.override(mock_use_case):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/suggestions/ingest",
                json=valid_payload,
                headers=api_headers,
            )

            assert response.status_code == 409
            data = response.json()
            assert "errors" in data
            err = data["errors"][0]
            assert err["status"] == 409
            assert err["code"] == "SUGGESTION_ALREADY_EXISTS"
            assert err["source"]["pointer"] == "/data/suggestionId"


@pytest.mark.asyncio
async def test_ingest_suggestion_domain_invalid_content_422(
    setup_container, api_headers, valid_payload
):
    mock_use_case = AsyncMock()
    mock_use_case.execute.side_effect = InvalidSuggestionContentError(
        "Suggestion problem must contain substantive content, got 'ندارد'.",
        pointer="/data/problem",
    )

    with setup_container.ingest_suggestion_use_case.override(mock_use_case):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/suggestions/ingest",
                json=valid_payload,
                headers=api_headers,
            )

            assert response.status_code == 422
            data = response.json()
            assert "errors" in data
            err = data["errors"][0]
            assert err["status"] == 422
            assert err["code"] == "INVALID_SUGGESTION_CONTENT"
            assert err["source"]["pointer"] == "/data/problem"


@pytest.mark.asyncio
async def test_ingest_suggestion_invalid_status_422(api_headers, valid_payload):
    payload = dict(valid_payload)
    payload["status"] = "وضعیت_نامعلوم"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/suggestions/ingest",
            json=payload,
            headers=api_headers,
        )

        assert response.status_code == 422
        data = response.json()
        assert "errors" in data
        err = data["errors"][0]
        assert err["status"] == 422
        assert err["code"] == "INVALID_SUGGESTION_STATUS"
        assert err["source"]["pointer"] == "/data/status"


@pytest.mark.asyncio
async def test_ingest_suggestion_extra_fields_forbidden(api_headers, valid_payload):
    payload = dict(valid_payload)
    payload["unexpectedExtraField"] = "malicious_payload"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/suggestions/ingest",
            json=payload,
            headers=api_headers,
        )

        assert response.status_code == 422
        data = response.json()
        assert "errors" in data
        err = data["errors"][0]
        assert err["code"] == "VALIDATION_ERROR"
