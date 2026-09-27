from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from src.containers import Container
from src.infrastructure.configs.settings import security_settings

from src.application.dtos import (
    BulkDeleteErrorItemDTO,
    BulkDeleteResultDTO,
    DeleteSuggestionResponseDTO,
    UpdateSuggestionResponseDTO,
)
from src.domain.exceptions import (
    SuggestionNotFoundError,
    SuggestionProcessingConflictError,
)
from src.main import app


@pytest.fixture
def api_headers():
    return {
        security_settings.API_KEY_NAME: security_settings.API_KEY,
        "Content-Type": "application/json",
    }


@pytest.fixture
def valid_put_payload():
    return {
        "suggestionId": "sugg-api-101",
        "title": "بهینه‌سازی مصرف انرژی در تاسیسات",
        "problem": "مصرف بالای انرژی به دلیل فرسودگی تجهیزات روشنایی و سرمایشی",
        "solution": "نصب سیستم‌های هوشمند کنترل مصرف و تعویض لامپ‌ها با انواع ال‌ای‌دی",
        "status": "مصوب",
        "committeeScrutiny": "تایید",
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


# --- PUT Endpoint Tests ---


@pytest.mark.asyncio
async def test_put_suggestion_missing_api_key(valid_put_payload):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put(
            "/api/v1/suggestions/sugg-api-101", json=valid_put_payload
        )
        assert response.status_code == 401
        data = response.json()
        assert data["errors"][0]["code"] == "API_KEY_MISSING"


@pytest.mark.asyncio
async def test_put_suggestion_body_id_mismatch_422(setup_container, api_headers):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "suggestionId": "sugg-body-1",
            "title": "عنوان پیشنهاد",
            "problem": "شرح مشکل سازمان با جزییات کامل",
            "solution": "ارائه راهکار اجرایی مناسب",
            "status": "مصوب",
        }
        # Path id differs from body id
        response = await client.put(
            "/api/v1/suggestions/sugg-path-different",
            json=payload,
            headers=api_headers,
        )
        assert response.status_code == 422
        data = response.json()
        assert "errors" in data


@pytest.mark.asyncio
async def test_put_suggestion_success_200(
    setup_container, api_headers, valid_put_payload
):
    mock_use_case = AsyncMock()
    mock_use_case.execute_put.return_value = UpdateSuggestionResponseDTO(
        suggestion_id="sugg-api-101",
        chunks_count=3,
        version=2,
        status="UPDATED",
    )

    with setup_container.update_suggestion_use_case.override(mock_use_case):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.put(
                "/api/v1/suggestions/sugg-api-101",
                json=valid_put_payload,
                headers=api_headers,
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == 200
            assert data["data"] == {
                "suggestionId": "sugg-api-101",
                "chunksCount": 3,
                "version": 2,
                "status": "UPDATED",
            }
            mock_use_case.execute_put.assert_awaited_once()


@pytest.mark.asyncio
async def test_put_suggestion_not_found_404(
    setup_container, api_headers, valid_put_payload
):
    mock_use_case = AsyncMock()
    mock_use_case.execute_put.side_effect = SuggestionNotFoundError(
        "Suggestion with ID 'sugg-api-101' not found.",
        pointer="/data/suggestionId",
    )

    with setup_container.update_suggestion_use_case.override(mock_use_case):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.put(
                "/api/v1/suggestions/sugg-api-101",
                json=valid_put_payload,
                headers=api_headers,
            )

            assert response.status_code == 404
            data = response.json()
            assert data["errors"][0]["code"] == "SUGGESTION_NOT_FOUND"


@pytest.mark.asyncio
async def test_put_suggestion_conflict_in_processing_409(
    setup_container, api_headers, valid_put_payload
):
    mock_use_case = AsyncMock()
    mock_use_case.execute_put.side_effect = SuggestionProcessingConflictError(
        "Suggestion 'sugg-api-101' is currently being modified by another operation.",
        pointer="/data/suggestionId",
    )

    with setup_container.update_suggestion_use_case.override(mock_use_case):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.put(
                "/api/v1/suggestions/sugg-api-101",
                json=valid_put_payload,
                headers=api_headers,
            )

            assert response.status_code == 409
            data = response.json()
            assert data["errors"][0]["code"] == "SUGGESTION_IN_PROCESSING"


# --- PATCH Endpoint Tests ---


@pytest.mark.asyncio
async def test_patch_suggestion_rejects_id_in_body_422(setup_container, api_headers):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.patch(
            "/api/v1/suggestions/sugg-1",
            json={"suggestionId": "sugg-1", "title": "عنوان جدید"},
            headers=api_headers,
        )
        assert response.status_code == 422
        data = response.json()
        assert "errors" in data


@pytest.mark.asyncio
async def test_patch_suggestion_rejects_empty_payload_422(setup_container, api_headers):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.patch(
            "/api/v1/suggestions/sugg-1",
            json={},
            headers=api_headers,
        )
        assert response.status_code == 422
        data = response.json()
        assert "errors" in data


@pytest.mark.asyncio
async def test_patch_suggestion_success_200(setup_container, api_headers):
    mock_use_case = AsyncMock()
    mock_use_case.execute_patch.return_value = UpdateSuggestionResponseDTO(
        suggestion_id="sugg-1",
        chunks_count=3,
        version=3,
        status="UPDATED",
    )

    with setup_container.update_suggestion_use_case.override(mock_use_case):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.patch(
                "/api/v1/suggestions/sugg-1",
                json={"title": "فقط عنوان تغییر یافته"},
                headers=api_headers,
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == 200
            assert data["data"] == {
                "suggestionId": "sugg-1",
                "chunksCount": 3,
                "version": 3,
                "status": "UPDATED",
            }
            mock_use_case.execute_patch.assert_awaited_once()


# --- DELETE Endpoint Tests ---


@pytest.mark.asyncio
async def test_delete_suggestion_success_200(setup_container, api_headers):
    mock_use_case = AsyncMock()
    mock_use_case.execute.return_value = DeleteSuggestionResponseDTO(
        suggestion_id="sugg-to-del",
        status="DELETED",
    )

    with setup_container.delete_suggestion_use_case.override(mock_use_case):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.delete(
                "/api/v1/suggestions/sugg-to-del",
                headers=api_headers,
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == 200
            assert data["data"] == {
                "suggestionId": "sugg-to-del",
                "status": "DELETED",
            }
            mock_use_case.execute.assert_awaited_once_with(suggestion_id="sugg-to-del")


@pytest.mark.asyncio
async def test_delete_suggestion_not_found_404(setup_container, api_headers):
    mock_use_case = AsyncMock()
    mock_use_case.execute.side_effect = SuggestionNotFoundError(
        "Suggestion with ID 'sugg-not-found' not found.",
        pointer="/data/suggestionId",
    )

    with setup_container.delete_suggestion_use_case.override(mock_use_case):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.delete(
                "/api/v1/suggestions/sugg-not-found",
                headers=api_headers,
            )

            assert response.status_code == 404
            data = response.json()
            assert data["errors"][0]["code"] == "SUGGESTION_NOT_FOUND"


# --- Bulk DELETE Endpoint Tests ---


@pytest.mark.asyncio
async def test_bulk_delete_validation_bounds_422(setup_container, api_headers):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Empty list
        resp1 = await client.post(
            "/api/v1/suggestions/bulk-delete",
            json={"suggestionIds": []},
            headers=api_headers,
        )
        assert resp1.status_code == 422

        # Duplicates
        resp2 = await client.post(
            "/api/v1/suggestions/bulk-delete",
            json={"suggestionIds": ["id-1", "id-1"]},
            headers=api_headers,
        )
        assert resp2.status_code == 422


@pytest.mark.asyncio
async def test_bulk_delete_all_succeed_200(setup_container, api_headers):
    mock_use_case = AsyncMock()
    mock_use_case.execute.return_value = BulkDeleteResultDTO(
        deleted_ids=["sugg-1", "sugg-2"],
        errors=[],
        total_requested=2,
        total_deleted=2,
        total_failed=0,
    )

    with setup_container.bulk_delete_suggestions_use_case.override(mock_use_case):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/suggestions/bulk-delete",
                json={"suggestionIds": ["sugg-1", "sugg-2"]},
                headers=api_headers,
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == 200
            assert len(data["data"]) == 2
            assert data["data"][0]["suggestionId"] == "sugg-1"
            assert data["data"][0]["status"] == "DELETED"
            assert "errors" not in data


@pytest.mark.asyncio
async def test_bulk_delete_partial_success_207_multi_status(
    setup_container, api_headers
):
    mock_use_case = AsyncMock()
    mock_use_case.execute.return_value = BulkDeleteResultDTO(
        deleted_ids=["sugg-1"],
        errors=[
            BulkDeleteErrorItemDTO(
                suggestion_id="sugg-2",
                index=1,
                code="SUGGESTION_NOT_FOUND",
                detail="Suggestion with ID 'sugg-2' not found.",
                source_pointer="/data/suggestionIds/1",
            )
        ],
        total_requested=2,
        total_deleted=1,
        total_failed=1,
    )

    with setup_container.bulk_delete_suggestions_use_case.override(mock_use_case):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/suggestions/bulk-delete",
                json={"suggestionIds": ["sugg-1", "sugg-2"]},
                headers=api_headers,
            )

            assert response.status_code == 207
            data = response.json()
            assert data["status"] == 207
            # Both data and errors present
            assert len(data["data"]) == 1
            assert data["data"][0]["suggestionId"] == "sugg-1"
            assert len(data["errors"]) == 1
            err = data["errors"][0]
            assert err["code"] == "SUGGESTION_NOT_FOUND"
            assert err["source"]["pointer"] == "/data/suggestionIds/1"


@pytest.mark.asyncio
async def test_bulk_delete_all_fail_400(setup_container, api_headers):
    mock_use_case = AsyncMock()
    mock_use_case.execute.return_value = BulkDeleteResultDTO(
        deleted_ids=[],
        errors=[
            BulkDeleteErrorItemDTO(
                suggestion_id="sugg-missing",
                index=0,
                code="SUGGESTION_NOT_FOUND",
                detail="Suggestion with ID 'sugg-missing' not found.",
                source_pointer="/data/suggestionIds/0",
            )
        ],
        total_requested=1,
        total_deleted=0,
        total_failed=1,
    )

    with setup_container.bulk_delete_suggestions_use_case.override(mock_use_case):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/suggestions/bulk-delete",
                json={"suggestionIds": ["sugg-missing"]},
                headers=api_headers,
            )

            assert response.status_code == 400
            data = response.json()
            assert "data" not in data
            assert len(data["errors"]) == 1
            assert data["errors"][0]["code"] == "SUGGESTION_NOT_FOUND"
            assert data["errors"][0]["source"]["pointer"] == "/data/suggestionIds/0"
