"""Mock HTTP checks reported separately from real database evidence."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class MockScenario:
    case_id: str
    variant_id: str
    profile: str = "mock"
    operation: str = "mock"
    parameters: tuple = ()
    characterization: bool = True


MOCK_SCENARIOS = tuple(MockScenario(f"MOCK-{index:02d}", variant) for index, variants in {
    1: ["metadata-and-reset-route"],
    2: ["missing-auth", "wrong-auth", "valid-reset"],
    3: ["seed-restoration-custom-removal-repeat"],
    4: ["ingest", "put", "patch"],
    5: ["repeat-delete", "mixed-bulk", "all-deleted-bulk"],
    6: ["put-omitted-metadata", "patch-evaluation-without-status"],
    7: ["restart", "two-independent-processes"],
    8: ["auth", "validation", "camel-case-envelope", "request-id"],
}.items() for variant in variants)


def body(identifier):
    return {"suggestionId": identifier, "title": "بهینه سازی مصرف انرژی", "problem": "مصرف بالای انرژی در تجهیزات روشنایی", "solution": "نصب تجهیزات کم مصرف و کنترل هوشمند", "status": "APPROVED"}


def assert_response(response, status):
    assert response.status_code == status, response.text
    result = response.json()
    if status < 300:
        assert result["status"] == status
        if status != 207:
            assert "errors" not in result
    else:
        assert result["errors"]
    return result


def execute_mock(harness, scenario):
    case, variant = scenario.case_id, scenario.variant_id
    assert_response(harness.request("POST", "/api/v1/mock/reset", json={}), 200)
    path = "/api/v1/suggestions/"
    identifier = harness.new_id("mock")
    payload = body(identifier)
    if case == "MOCK-01":
        assert harness.request("GET", "/", auth=False).json()["mockMode"] is True
        assert harness.request("GET", "/health", auth=False).json()["mockMode"] is True
    elif case == "MOCK-02":
        if variant == "missing-auth":
            assert_response(harness.request("POST", "/api/v1/mock/reset", auth=False), 401)
        elif variant == "wrong-auth":
            assert_response(harness.request("POST", "/api/v1/mock/reset", auth=False, headers={harness.config.api_header: "wrong"}), 401)
        else:
            result = assert_response(harness.request("POST", "/api/v1/mock/reset"), 200)
            assert result["data"]["seededItems"] == 6
    elif case == "MOCK-03":
        assert_response(harness.request("POST", path + "ingest", json=payload), 201)
        assert_response(harness.request("PATCH", path + identifier, json={"title": "عنوان تغییر یافته برای پیشنهاد آزمایشی"}), 200)
        assert_response(harness.request("DELETE", path + "sug-101"), 200)
        for _ in range(2):
            assert_response(harness.request("POST", "/api/v1/mock/reset"), 200)
            assert_response(harness.request("PATCH", path + "sug-101", json={"title": "عنوان تازه برای پیشنهاد بازگردانی"}), 200)
            assert_response(harness.request("PATCH", path + identifier, json={"title": "عنوان تازه برای پیشنهاد بازگردانی"}), 404)
    elif case == "MOCK-04":
        result = assert_response(harness.request("POST", path + "ingest", json=payload), 201)
        if variant == "put":
            result = assert_response(harness.request("PUT", path + identifier, json={key: value for key, value in payload.items() if key != "suggestionId"}), 200)
        elif variant == "patch":
            result = assert_response(harness.request("PATCH", path + identifier, json={"title": "عنوان تازه برای پیشنهاد آزمایشی"}), 200)
        assert result["data"]["chunksCount"] == 4
    elif case == "MOCK-05":
        assert_response(harness.request("DELETE", path + "sug-101"), 200)
        if variant == "repeat-delete":
            assert_response(harness.request("DELETE", path + "sug-101"), 404)
        else:
            ids = ["sug-101", "sug-102"] if variant == "mixed-bulk" else ["sug-101"]
            result = assert_response(harness.request("POST", path + "bulk-delete", json={"suggestionIds": ids}), 207 if variant == "mixed-bulk" else 400)
            assert result["errors"][0]["code"] == "SUGGESTION_NOT_FOUND"
    elif case == "MOCK-06":
        payload.update(shamsiDate="1403/02/18", contextTitle="مدیریت توزیع برق", secretariatScrutiny=-2, secretariatComment="بررسی اولیه انجام شد و پرونده کامل است")
        assert_response(harness.request("POST", path + "ingest", json=payload), 201)
        if variant == "put-omitted-metadata":
            assert_response(harness.request("PUT", path + identifier, json={key: payload[key] for key in ("title", "problem", "solution", "status")}), 200)
            state = json.loads((harness.config.artifacts_dir / "mock-state.json").read_text(encoding="utf-8"))[identifier]
            assert state["date"]["value"] == "1403/02/18"
            assert state["context_title"] == payload["contextTitle"]
        else:
            assert_response(harness.request("PATCH", path + identifier, json={"description": "شرح جدید برای ارزیابی پیشنهاد آزمایشی"}), 200)
            state = json.loads((harness.config.artifacts_dir / "mock-state.json").read_text(encoding="utf-8"))[identifier]
            assert state["evaluation"]["description"] is None
    elif case == "MOCK-07":
        assert_response(harness.request("DELETE", path + "sug-101"), 200)
        if variant == "restart":
            harness.restart()
            assert_response(harness.request("PATCH", path + "sug-101", json={"title": "عنوان تازه برای پیشنهاد بازگردانی"}), 200)
        else:
            from .harness import AppProcess
            with AppProcess(harness.config, artifacts_dir=harness.config.artifacts_dir / "second-mock", app="src.presentation.mock_server:app") as other:
                assert_response(other.request("PATCH", path + "sug-101", json={"title": "عنوان تازه برای پیشنهاد مستقل"}), 200)
                assert_response(harness.request("PATCH", path + "sug-101", json={"title": "عنوان تازه برای پیشنهاد مستقل"}), 404)
    elif case == "MOCK-08":
        if variant == "auth":
            assert_response(harness.request("POST", path + "ingest", json=payload, auth=False), 401)
        elif variant == "validation":
            assert_response(harness.request("POST", path + "ingest", json={}), 422)
        else:
            request_id = str(uuid.uuid4())
            response = harness.request("POST", path + "ingest", json=payload, headers={"X-Request-Id": request_id})
            result = assert_response(response, 201)
            assert response.headers["x-request-id"] == request_id
            assert result["data"]["suggestionId"] == identifier
            assert not any("_" in key for key in result["data"])
