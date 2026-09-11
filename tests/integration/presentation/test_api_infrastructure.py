import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel
from src.infrastructure.configs.settings import security_settings

from src.application.exceptions import (
    AggregateApplicationError,
    EmbedderConnectionError,
)
from src.domain.exceptions import InvalidSuggestionStatusError
from src.main import app
from src.presentation.routers.router import master_router_v1


class DummyInputModel(BaseModel):
    title: str
    target_score: int


# Attach dummy endpoints (prefix with dummy_ so pytest doesn't collect them as test cases)
@master_router_v1.get("/dummy-protected")
async def dummy_protected_endpoint():
    return {"status": "authorized"}


@master_router_v1.post("/dummy-validation")
async def dummy_validation_endpoint(payload: DummyInputModel):
    return {"received": payload.title}


@master_router_v1.get("/dummy-domain-error")
async def dummy_domain_error_endpoint():
    raise InvalidSuggestionStatusError(
        "Unknown status provided", pointer="/data/status"
    )


@master_router_v1.get("/dummy-internal-error")
async def dummy_internal_error_endpoint():
    raise EmbedderConnectionError("TEI server unreachable on port 8080")


@master_router_v1.get("/dummy-aggregate-error")
async def dummy_aggregate_error_endpoint():
    raise AggregateApplicationError(
        errors=[
            InvalidSuggestionStatusError("Invalid status for record 0"),
            EmbedderConnectionError("Timeout processing record 1"),
        ]
    )


@pytest.mark.asyncio
async def test_root_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "Tavanir AI Assistant V2"
        assert "documentation" in data


@pytest.mark.asyncio
async def test_health_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "tavanir-ai-assistant-v2"


@pytest.mark.asyncio
async def test_correlation_id_middleware_generates_request_id():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
        assert "x-request-id" in response.headers
        assert len(response.headers["x-request-id"]) > 0


@pytest.mark.asyncio
async def test_correlation_id_middleware_preserves_caller_id():
    transport = ASGITransport(app=app)
    valid_uuid = str(uuid.uuid4())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health", headers={"X-Request-Id": valid_uuid})
        assert response.headers["x-request-id"] == valid_uuid


@pytest.mark.asyncio
async def test_scalar_docs_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/scalar")
        assert response.status_code == 200
        assert "/static/scalar.js" in response.text


@pytest.mark.asyncio
async def test_scalar_static_js_asset_serving():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/static/scalar.js")
        assert response.status_code == 200
        assert len(response.content) > 100_000  # Full scalar.js bundle


@pytest.mark.asyncio
async def test_security_missing_api_key():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/dummy-protected")
        assert response.status_code == 401
        assert response.headers.get("www-authenticate") == "ApiKey"
        data = response.json()
        assert "errors" in data
        err = data["errors"][0]
        assert err["code"] == "API_KEY_MISSING"
        assert err["source"]["pointer"] == f"/headers/{security_settings.API_KEY_NAME}"


@pytest.mark.asyncio
async def test_security_invalid_api_key():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/dummy-protected",
            headers={security_settings.API_KEY_NAME: "wrong-secret-token"},
        )
        assert response.status_code == 401
        assert response.headers.get("www-authenticate") == "ApiKey"
        data = response.json()
        err = data["errors"][0]
        assert err["code"] == "API_KEY_INVALID"
        assert err["source"]["pointer"] == f"/headers/{security_settings.API_KEY_NAME}"


@pytest.mark.asyncio
async def test_security_valid_api_key():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/dummy-protected",
            headers={security_settings.API_KEY_NAME: security_settings.API_KEY},
        )
        assert response.status_code == 200
        assert response.json() == {"status": "authorized"}


@pytest.mark.asyncio
async def test_validation_error_missing_field():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/dummy-validation",
            headers={security_settings.API_KEY_NAME: security_settings.API_KEY},
            json={},  # Missing title and target_score
        )
        assert response.status_code == 422
        data = response.json()
        assert "errors" in data
        codes = [e["code"] for e in data["errors"]]
        assert "MISSING_REQUIRED_FIELD" in codes
        pointers = [e["source"]["pointer"] for e in data["errors"]]
        assert any("title" in p for p in pointers)


@pytest.mark.asyncio
async def test_domain_error_mapping():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/dummy-domain-error",
            headers={security_settings.API_KEY_NAME: security_settings.API_KEY},
        )
        assert response.status_code == 422
        data = response.json()
        err = data["errors"][0]
        assert err["code"] == "INVALID_SUGGESTION_STATUS"
        assert err["source"]["pointer"] == "/data/status"


@pytest.mark.asyncio
async def test_internal_single_error_omits_source():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/dummy-internal-error",
            headers={security_settings.API_KEY_NAME: security_settings.API_KEY},
        )
        assert response.status_code == 503
        data = response.json()
        err = data["errors"][0]
        assert err["code"] == "EMBEDDER_CONNECTION_FAILED"
        # Source must be omitted completely on single internal errors
        assert "source" not in err


@pytest.mark.asyncio
async def test_aggregate_batch_error_mapping():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/dummy-aggregate-error",
            headers={security_settings.API_KEY_NAME: security_settings.API_KEY},
        )
        assert response.status_code == 400
        data = response.json()
        assert len(data["errors"]) == 2
        assert data["errors"][0]["code"] == "INVALID_SUGGESTION_STATUS"
        assert data["errors"][0]["source"]["pointer"] == "/data/0"
        assert data["errors"][1]["code"] == "EMBEDDER_CONNECTION_FAILED"
        assert data["errors"][1]["source"]["pointer"] == "/data/1"
