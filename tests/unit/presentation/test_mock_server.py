import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.infrastructure.configs.settings import security_settings
from src.main import create_app

VALID_HEADERS = {
    security_settings.API_KEY_NAME: security_settings.API_KEY,
}


@pytest_asyncio.fixture(loop_scope="function")
async def client():
    """Test client executing with mock lifespan enabled."""
    app = create_app(is_mock=True)
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            yield ac


@pytest.mark.asyncio
async def test_mock_server_health_and_root(client: AsyncClient):
    """Verifies that root metadata and health check endpoints report mockMode correctly."""
    root_resp = await client.get("/")
    assert root_resp.status_code == 200
    root_data = root_resp.json()
    assert root_data["service"] == "Tavanir AI Assistant V2"
    assert root_data["mockMode"] is True

    health_resp = await client.get("/health")
    assert health_resp.status_code == 200
    health_data = health_resp.json()
    assert health_data["status"] == "ok"
    assert health_data["mockMode"] is True


@pytest.mark.asyncio
async def test_mock_auth_missing_header(client: AsyncClient):
    """Verifies Contract 06: Missing X-API-Key returns HTTP 401 with pointer."""
    resp = await client.post(
        "/api/v1/suggestions/analyze",
        json={
            "title": "بهینه‌سازی سیستم خنک‌کاری",
            "currentProblem": "افزایش دمای سیم‌پیچ‌ها در تابستان",
            "solution": "نصب مه‌پاش هوشمند",
        },
    )
    assert resp.status_code == 401
    payload = resp.json()
    assert "errors" in payload
    assert payload["errors"][0]["code"] == "API_KEY_MISSING"
    assert (
        payload["errors"][0]["source"]["pointer"]
        == f"/headers/{security_settings.API_KEY_NAME}"
    )


@pytest.mark.asyncio
async def test_mock_auth_invalid_header(client: AsyncClient):
    """Verifies Contract 06: Invalid X-API-Key returns HTTP 401 with code API_KEY_INVALID."""
    resp = await client.post(
        "/api/v1/suggestions/analyze",
        headers={security_settings.API_KEY_NAME: "wrong_secret_key"},
        json={
            "title": "بهینه‌سازی سیستم خنک‌کاری",
            "currentProblem": "افزایش دمای سیم‌پیچ‌ها در تابستان",
            "solution": "نصب مه‌پاش هوشمند",
        },
    )
    assert resp.status_code == 401
    payload = resp.json()
    assert payload["errors"][0]["code"] == "API_KEY_INVALID"


@pytest.mark.asyncio
async def test_mock_analyze_suggestion_success(client: AsyncClient):
    """Verifies POST /api/v1/suggestions/analyze returns structured analysis and similar IDs."""
    payload = {
        "title": "بهینه‌سازی سیستم خنک‌کاری ترانسفورماتور",
        "currentProblem": "افزایش دمای سیم‌پیچ‌ها در تابستان گرمسیری",
        "solution": "نصب مه‌پاش هوشمند با کنترل دیجیتال برخط",
        "contextTitle": "معاونت انتقال",
    }
    resp = await client.post(
        "/api/v1/suggestions/analyze",
        headers=VALID_HEADERS,
        json=payload,
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "analysis" in data
    assert isinstance(data["analysis"], str)
    assert len(data["analysis"]) > 20
    assert "similarExecutedIds" in data
    assert isinstance(data["similarExecutedIds"], list)
    assert "appliedStatuteIds" in data
    assert len(data["appliedStatuteIds"]) > 0


@pytest.mark.asyncio
async def test_mock_analyze_suggestion_noise_placeholder_422(
    client: AsyncClient,
):
    """Verifies that domain noise placeholders trigger HTTP 422 with pointer."""
    payload = {
        "title": "بهینه‌سازی سیستم خنک‌کاری",
        "currentProblem": "ندارد",  # Noise placeholder
        "solution": "نصب مه‌پاش هوشمند با کنترل دیجیتال",
    }
    resp = await client.post(
        "/api/v1/suggestions/analyze",
        headers=VALID_HEADERS,
        json=payload,
    )
    assert resp.status_code == 422
    err = resp.json()["errors"][0]
    assert err["code"] == "INVALID_SUGGESTION_CONTENT"
    assert "/data/currentProblem" in err["source"]["pointer"]


@pytest.mark.asyncio
async def test_mock_ingest_suggestion_success(client: AsyncClient):
    """Verifies POST /api/v1/suggestions/ingest creates a new suggestion in-memory."""
    payload = {
        "suggestionId": "sug-test-999",
        "title": "نصب سلول‌های خورشیدی روی کانال‌های آب نیروگاه",
        "problem": "تبخیر آب و اتلاف سطح در محوطه نیروگاه‌های حرارتی",
        "solution": "پوشش کانال‌ها با پنل‌های فتوولتائیک منعطف",
        "status": 3,
        "shamsiDate": "1403/03/15",
        "contextTitle": "نیروگاه طرشت",
    }
    resp = await client.post(
        "/api/v1/suggestions/ingest",
        headers=VALID_HEADERS,
        json=payload,
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["suggestionId"] == "sug-test-999"
    assert data["status"] == "CREATED"
    assert data["chunksCount"] == 4


@pytest.mark.asyncio
async def test_mock_ingest_suggestion_duplicate_conflict_409(
    client: AsyncClient,
):
    """Verifies ingesting an existing ID raises HTTP 409 SUGGESTION_ALREADY_EXISTS."""
    payload = {
        "suggestionId": "sug-101",  # Pre-seeded item
        "title": "بهینه‌سازی سیستم خنک‌کاری ترانسفورماتورهای قدرت",
        "problem": "افزایش دمای سیم‌پیچ‌ها در اوج بار تابستان",
        "solution": "نصب سیستم مه‌پاش هوشمند اتوماتیک",
        "status": 4,
    }
    resp = await client.post(
        "/api/v1/suggestions/ingest",
        headers=VALID_HEADERS,
        json=payload,
    )
    assert resp.status_code == 409
    err = resp.json()["errors"][0]
    assert err["code"] == "SUGGESTION_ALREADY_EXISTS"
    assert err["source"]["pointer"] == "/data/suggestionId"


@pytest.mark.asyncio
async def test_mock_update_suggestion_put_and_patch(client: AsyncClient):
    """Verifies full replacement (PUT) and partial update (PATCH) on in-memory entity."""
    # 1. Full replacement (PUT)
    put_payload = {
        "title": "عنوان جدید به‌روزشده برای ترانسفورماتورها",
        "problem": "چالش جدید در بهره‌برداری ایستگاه‌های توزیع",
        "solution": "راهکار نوین با الگوریتم‌های هوش مصنوعی",
        "status": 3,
        "shamsiDate": "1403/04/01",
        "contextTitle": "معاونت انتقال",
    }
    put_resp = await client.put(
        "/api/v1/suggestions/sug-101",
        headers=VALID_HEADERS,
        json=put_payload,
    )
    assert put_resp.status_code == 200
    put_data = put_resp.json()["data"]
    assert put_data["suggestionId"] == "sug-101"
    assert put_data["version"] == 2
    assert put_data["status"] == "UPDATED"

    # 2. Partial update (PATCH)
    patch_payload = {
        "title": "عنوان ویرایش‌شده با پچ جزئی",
    }
    patch_resp = await client.patch(
        "/api/v1/suggestions/sug-101",
        headers=VALID_HEADERS,
        json=patch_payload,
    )
    assert patch_resp.status_code == 200
    patch_data = patch_resp.json()["data"]
    assert patch_data["version"] == 3


@pytest.mark.asyncio
async def test_mock_update_suggestion_not_found_404(client: AsyncClient):
    """Verifies updating a non-existent ID raises HTTP 404 SUGGESTION_NOT_FOUND."""
    put_payload = {
        "title": "عنوان تستی برای مورد ناموجود",
        "problem": "مسئله تستی برای بررسی خطای ۴۰۴",
        "solution": "راهکار تستی برای بررسی خطای ۴۰۴",
        "status": 3,
    }
    resp = await client.put(
        "/api/v1/suggestions/sug-nonexistent-id",
        headers=VALID_HEADERS,
        json=put_payload,
    )
    assert resp.status_code == 404
    err = resp.json()["errors"][0]
    assert err["code"] == "SUGGESTION_NOT_FOUND"


@pytest.mark.asyncio
async def test_mock_delete_suggestion_success_and_not_found(
    client: AsyncClient,
):
    """Verifies soft-delete marks entity deleted, and subsequent delete returns 404."""
    # First delete -> 200 OK
    resp1 = await client.delete(
        "/api/v1/suggestions/sug-201",
        headers=VALID_HEADERS,
    )
    assert resp1.status_code == 200
    assert resp1.json()["data"]["status"] == "DELETED"

    # Second delete on same ID -> 404 NOT FOUND
    resp2 = await client.delete(
        "/api/v1/suggestions/sug-201",
        headers=VALID_HEADERS,
    )
    assert resp2.status_code == 404
    assert resp2.json()["errors"][0]["code"] == "SUGGESTION_NOT_FOUND"


@pytest.mark.asyncio
async def test_mock_bulk_delete_all_success_200(client: AsyncClient):
    """Verifies bulk-delete returns 200 OK when all target IDs exist."""
    payload = {"suggestionIds": ["sug-102", "sug-202"]}
    resp = await client.post(
        "/api/v1/suggestions/bulk-delete",
        headers=VALID_HEADERS,
        json=payload,
    )
    assert resp.status_code == 200
    items = resp.json()["data"]
    assert len(items) == 2
    assert {it["suggestionId"] for it in items} == {"sug-102", "sug-202"}


@pytest.mark.asyncio
async def test_mock_bulk_delete_partial_failure_207(client: AsyncClient):
    """Verifies Contract 04: Partial failures return HTTP 207 Multi-Status with RFC 6901 pointers."""
    payload = {"suggestionIds": ["sug-301", "sug-absent-id-1"]}
    resp = await client.post(
        "/api/v1/suggestions/bulk-delete",
        headers=VALID_HEADERS,
        json=payload,
    )
    assert resp.status_code == 207
    body = resp.json()
    assert "data" in body
    assert "errors" in body
    assert len(body["data"]) == 1
    assert body["data"][0]["suggestionId"] == "sug-301"

    assert len(body["errors"]) == 1
    err = body["errors"][0]
    assert err["code"] == "SUGGESTION_NOT_FOUND"
    assert err["source"]["pointer"] == "/data/suggestionIds/1"


@pytest.mark.asyncio
async def test_mock_bulk_delete_all_failure_400(client: AsyncClient):
    """Verifies bulk-delete returns 400 Bad Request when all items fail."""
    payload = {"suggestionIds": ["sug-missing-1", "sug-missing-2"]}
    resp = await client.post(
        "/api/v1/suggestions/bulk-delete",
        headers=VALID_HEADERS,
        json=payload,
    )
    assert resp.status_code == 400
    body = resp.json()
    assert "errors" in body
    assert len(body["errors"]) == 2


@pytest.mark.asyncio
async def test_mock_reset_endpoint(client: AsyncClient):
    """Verifies POST /api/v1/mock/reset repopulates deleted entities back to 6 seed items."""
    # Delete an item
    del_resp = await client.delete(
        "/api/v1/suggestions/sug-302",
        headers=VALID_HEADERS,
    )
    assert del_resp.status_code == 200

    # Verify it is deleted
    del_again = await client.delete(
        "/api/v1/suggestions/sug-302",
        headers=VALID_HEADERS,
    )
    assert del_again.status_code == 404

    # Reset mock state
    reset_resp = await client.post(
        "/api/v1/mock/reset",
        headers=VALID_HEADERS,
    )
    assert reset_resp.status_code == 200
    assert reset_resp.json()["data"]["seededItems"] == 6

    # Verify sug-302 is present and active again
    del_restored = await client.delete(
        "/api/v1/suggestions/sug-302",
        headers=VALID_HEADERS,
    )
    assert del_restored.status_code == 200


def test_mock_openapi_dynamic_visibility():
    """Verifies that /api/v1/mock/reset is visible in OpenAPI only when is_mock is True."""
    mock_app = create_app(is_mock=True)
    mock_paths = mock_app.openapi()["paths"]
    assert "/api/v1/mock/reset" in mock_paths

    prod_app = create_app(is_mock=False)
    prod_paths = prod_app.openapi()["paths"]
    assert "/api/v1/mock/reset" not in prod_paths
