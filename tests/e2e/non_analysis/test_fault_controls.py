"""Harness self-tests. These never connect to SQL, Qdrant, or a real provider."""

from __future__ import annotations

import asyncio
import base64
import json
import math
import struct
import threading
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from http.client import RemoteDisconnected
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pytest

from tests.e2e.non_analysis.bootstrap import wrap_collaborator
from tests.e2e.non_analysis.proxy import (
    REQUEST_CONTEXT,
    BarrierExpired,
    FaultController,
    FaultRule,
    ForwardingProxy,
    classify_request,
    input_fingerprint,
    provider_vector_values,
    transform_provider_response,
)


class OperationPort(ABC):
    @abstractmethod
    async def chunk(self, value):
        raise NotImplementedError


class RecordingOperation(OperationPort):
    def __init__(self):
        self.calls = []

    async def chunk(self, value):
        self.calls.append(value)
        return []


def test_wrapper_requires_delegate_and_uses_injected_real_delegate(tmp_path):
    controller = FaultController(tmp_path)
    delegate = RecordingOperation()
    wrapper = wrap_collaborator(OperationPort, delegate, controller)
    assert isinstance(wrapper, OperationPort)
    asyncio.run(wrapper.chunk("fixture"))
    assert delegate.calls == ["fixture"]
    assert controller.events(kind="phase", timing="after")[0]["delegate_called"]
    with pytest.raises(TypeError):
        type(wrapper)(controller=controller)


def test_exact_parent_request_attempt_matching_and_schedule_reset(tmp_path):
    controller = FaultController(tmp_path)
    controller.install(
        [
            FaultRule(
                "target",
                "vector.promote",
                parent_id="fixture",
                request_id="A",
                attempt=2,
            )
        ]
    )
    a1 = controller.invocation("vector.promote", "fixture", request_id="A")
    controller.hit(a1, "before")
    different_parent = controller.invocation("vector.promote", "other", request_id="A")
    controller.hit(different_parent, "before")
    a2 = controller.invocation("vector.promote", "fixture", request_id="A")
    with pytest.raises(RuntimeError, match="target"):
        controller.hit(a2, "before")
    controller.assert_triggered()
    controller.install([])
    assert (
        controller.invocation("vector.promote", "fixture", request_id="A")["attempt"]
        == 1
    )
    controller.install(
        [FaultRule("exhaustion", "op", action="reject", attempt=[1, 2, 3])]
    )
    controller.hit(controller.invocation("op"), "before")
    with pytest.raises(AssertionError, match="required attempts"):
        controller.assert_triggered()
    controller.hit(controller.invocation("op"), "before")
    controller.hit(controller.invocation("op"), "before")
    controller.assert_triggered()


def test_barrier_acknowledges_exact_phase_then_releases(tmp_path):
    controller = FaultController(tmp_path)
    epoch = controller.install(
        [FaultRule("hold", "chunker.chunk", action="barrier", request_id="A")]
    )
    delegate = RecordingOperation()
    wrapper = wrap_collaborator(OperationPort, delegate, controller)

    def execute():
        token = REQUEST_CONTEXT.set({"request_id": "A", "parent_id": "fixture"})
        try:
            return asyncio.run(wrapper.chunk("value"))
        finally:
            REQUEST_CONTEXT.reset(token)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(execute)
        entered = controller.wait(kind="barrier_entered", epoch=epoch, rule_id="hold")
        assert entered["timing"] == "before"
        assert delegate.calls == []
        assert not future.done()
        controller.release("hold")
        assert future.result(timeout=3) == []
    assert delegate.calls == ["value"]
    controller.assert_triggered()


def test_barrier_expiration_and_missing_fault_are_harness_failures(tmp_path):
    controller = FaultController(tmp_path)
    controller.install(
        [FaultRule("expired", "op", action="barrier", barrier_timeout=0.03)]
    )
    with pytest.raises(BarrierExpired):
        controller.hit(controller.invocation("op"), "before")
    with pytest.raises(AssertionError, match="expired"):
        controller.assert_triggered()
    controller.install([FaultRule("missing", "never")])
    with pytest.raises(AssertionError, match="missing"):
        controller.assert_triggered()


def test_zero_chunk_fault_bypasses_only_matched_collaborator(tmp_path):
    controller = FaultController(tmp_path)
    controller.install([FaultRule("zero", "chunker.chunk", action="zero")])
    delegate = RecordingOperation()
    wrapper = wrap_collaborator(OperationPort, delegate, controller)
    assert asyncio.run(wrapper.chunk("fixture")) == []
    assert delegate.calls == []
    assert controller.events(kind="zero_result")


class TinyUpstream:
    def __init__(self, response=None):
        self.applied = []
        upstream = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                upstream.applied.append(json.loads(raw))
                result = json.dumps(
                    response
                    if response is not None
                    else {"result": {"status": "completed"}}
                ).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(result)))
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(result)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.server_port}"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()


def send_delete(proxy):
    body = json.dumps(
        {"filter": {"must": [{"key": "parent_id", "match": {"value": "fixture"}}]}}
    ).encode()
    request = Request(
        proxy.url + "/collections/test/points/delete?wait=true",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=3) as response:
        return response.status, json.loads(response.read())


def test_rejection_does_not_forward_and_lost_response_records_actual_application(
    tmp_path,
):
    controller = FaultController(tmp_path)
    with (
        TinyUpstream() as upstream,
        ForwardingProxy(upstream.url, controller, provider="qdrant") as proxy,
    ):
        controller.install(
            [
                FaultRule(
                    "reject", "http.qdrant.delete", action="reject", parent_id="fixture"
                )
            ]
        )
        with pytest.raises(HTTPError) as error:
            send_delete(proxy)
        assert error.value.code == 503
        assert not upstream.applied
        assert not controller.events(kind="upstream_outcome")
        controller.assert_triggered()
        epoch = controller.install(
            [
                FaultRule(
                    "lost",
                    "http.qdrant.delete",
                    action="lose_response",
                    timing="after",
                    parent_id="fixture",
                )
            ]
        )
        with pytest.raises((RemoteDisconnected, URLError, ConnectionError)):
            send_delete(proxy)
        assert len(upstream.applied) == 1
        applied = controller.events(kind="upstream_outcome", epoch=epoch)
        assert applied[0]["applied"] is True
        assert applied[0]["application_result"] == "completed"
        controller.assert_triggered()


def test_controlled_provider_response_retains_forwarding_evidence(tmp_path):
    controller = FaultController(tmp_path)
    with (
        TinyUpstream() as upstream,
        ForwardingProxy(upstream.url, controller, provider="embedding") as proxy,
    ):
        controller.install(
            [
                FaultRule(
                    "malformed",
                    "http.embedding",
                    action="response",
                    timing="after",
                    status=200,
                    response={"data": [{"index": 0, "embedding": [0.1]}]},
                )
            ]
        )
        request = Request(
            proxy.url + "/v1/embeddings",
            data=b'{"input":["fixture"],"model":"test"}',
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request, timeout=3) as response:
            assert json.loads(response.read())["data"][0]["embedding"] == [0.1]
        assert len(upstream.applied) == 1
        assert controller.events(kind="upstream_outcome")[0]["forwarded"]
        controller.assert_triggered()


def test_lost_application_response_retains_full_upstream_wire_evidence(tmp_path):
    controller = FaultController(tmp_path)
    with (
        TinyUpstream() as upstream,
        ForwardingProxy(upstream.url, controller, provider="application") as proxy,
    ):
        controller.install(
            [
                FaultRule(
                    "lost",
                    "http.application",
                    action="lose_response",
                    timing="after",
                    request_id="wire",
                )
            ]
        )
        request = Request(
            proxy.url + "/api/v1/suggestions/ingest",
            data=b'{"suggestionId":"fixture"}',
            headers={"Content-Type": "application/json", "X-E2E-Operation-Id": "wire"},
        )
        with pytest.raises((RemoteDisconnected, URLError, ConnectionError)):
            urlopen(request, timeout=3)
        evidence = proxy.upstream_responses(request_id="wire")
        assert len(evidence) == 1 and evidence[0]["status"] == 200
        assert json.loads(evidence[0]["body"]) == {"result": {"status": "completed"}}
        assert (
            evidence[0]["body_sha256"]
            == controller.events(kind="upstream_outcome")[0]["response_sha256"]
        )
        evidence[0]["headers"]["private"] = "caller mutation"
        assert "private" not in proxy.upstream_responses()[0]["headers"]
        assert not proxy.upstream_responses(request_id="other")
        controller.assert_triggered()


def test_direct_http_evidence_sanitizes_secrets_and_keeps_generated_correlation(
    tmp_path,
):
    import httpx

    from tests.e2e.non_analysis.harness import LiveHarness
    from tests.e2e.non_analysis.resilience import (
        ResilienceScenario,
        _observe_direct_http,
    )

    secret = "private-control-test-key"
    harness = LiveHarness.__new__(LiveHarness)
    harness.config = SimpleNamespace(
        artifacts_dir=tmp_path, api_header="X-Custom-Key", secrets=lambda: [secret]
    )
    scenario = ResilienceScenario("API-11", "generated", "correlation")
    correlation = "53fef3d7-f673-4a1c-82ca-f1e61920d6d0"
    response = httpx.Response(
        500,
        json={"errors": [{"detail": "test " + secret}]},
        headers={"X-Request-Id": correlation},
    )
    wire = {
        "method": "POST",
        "path": "/api/v1/suggestions/ingest",
        "url": "http://127.0.0.1/ingest",
        "headers": {"X-Custom-Key": secret, "Authorization": "Bearer " + secret},
        "body": {"suggestionId": "fixture"},
    }
    _observe_direct_http(harness, scenario, **wire, response=response)
    _observe_direct_http(
        harness,
        scenario,
        **wire,
        transport_error={
            "error_type": "RemoteProtocolError",
            "response_delivered": False,
        },
        upstream={
            "responses": [
                {
                    "status": 201,
                    "headers": {"X-Request-Id": correlation},
                    "body": "accepted " + secret,
                    "body_sha256": "digest",
                }
            ]
        },
    )
    journal = (tmp_path / "observations.ndjson").read_text(encoding="utf-8")
    assert secret not in journal
    records = [json.loads(line)["data"] for line in journal.splitlines()]
    assert records[0]["request"]["headers"]["X-Custom-Key"] == "[REDACTED]"
    assert records[0]["response"]["request_id"] == correlation
    assert records[0]["response"]["headers"]["x-request-id"] == correlation
    assert records[1]["response"] is None
    assert records[1]["transport_failure"]["response_delivered"] is False
    assert (
        records[1]["upstream"]["responses"][0]["headers"]["X-Request-Id"] == correlation
    )


def test_qdrant_override_proof_requires_live_exact_run_owned_listener_and_test_upstream(
    tmp_path,
):
    controller = FaultController(tmp_path)
    proxy = ForwardingProxy("http://localhost:19033/", controller, provider="qdrant")
    proof = proxy.ownership_proof("run-control")
    port = int(proxy.url.rsplit(":", 1)[1])
    target = {
        "run_id": "run-control",
        "host": "127.0.0.1",
        "port": port,
        "expected_upstream": "http://127.0.0.1:19033",
    }
    with pytest.raises(ValueError, match="live owned listener"):
        proof.validate_owned_endpoint(**target)
    with proxy:
        proof.validate_owned_endpoint(**target)
        proof.validate_owned_endpoint(**{**target, "host": "localhost"})
        for altered in (
            {"run_id": "other"},
            {"port": port + 1},
            {"host": "127.0.0.2"},
            {"expected_upstream": "http://127.0.0.1:6333"},
        ):
            with pytest.raises(ValueError):
                proof.validate_owned_endpoint(**{**target, **altered})
    with pytest.raises(ValueError, match="live owned listener"):
        proof.validate_owned_endpoint(**target)
    with (
        ForwardingProxy(
            "http://127.0.0.1:19033", controller, provider="embedding"
        ) as embedding,
        pytest.raises(ValueError, match="this run"),
    ):
        embedding.ownership_proof("run-control").validate_owned_endpoint(
            **{**target, "port": int(embedding.url.rsplit(":", 1)[1])}
        )


def test_qdrant_operation_and_embedding_fingerprint_classification():
    operation, parent, _ = classify_request(
        "/collections/test/points/payload",
        {
            "payload": {"chunk_status": "active"},
            "filter": {"must": [{"key": "parent_id", "match": {"value": "fixture"}}]},
        },
        "qdrant",
    )
    assert (operation, parent) == ("http.qdrant.promote", "fixture")
    operation, _, fingerprint = classify_request(
        "/v1/embeddings", {"input": ["a", "b"]}, "embedding"
    )
    assert operation == "http.embedding"
    assert fingerprint == input_fingerprint(["a", "b"])
    operation, parent, _ = classify_request(
        "/collections/test/points?wait=true",
        {
            "points": [{"id": "point", "payload": {"parent_id": "fixture"}}],
        },
        "qdrant",
    )
    assert (operation, parent) == ("http.qdrant.upsert", "fixture")
    operation, parent, _ = classify_request(
        "/collections/test/points?wait=true&ordering=strong",
        {
            "points": [{"id": "point", "payload": {"parent_id": "fixture"}}],
        },
        "qdrant",
    )
    assert (operation, parent) == ("http.qdrant.upsert", "fixture")


def test_batch_ordinals_do_not_reset_for_different_input_fingerprints(tmp_path):
    controller = FaultController(tmp_path)
    controller.install(
        [FaultRule("later", "http.embedding", action="reject", attempt=2)]
    )
    first = controller.invocation("http.embedding", fingerprint="first")
    second = controller.invocation("http.embedding", fingerprint="later")
    assert (first["attempt"], second["attempt"]) == (1, 2)
    assert controller.hit(first, "before") is None
    assert controller.hit(second, "before")["rule_id"] == "later"


def test_rule_rejects_unsafe_control_paths_and_invalid_lost_response():
    with pytest.raises(ValueError):
        FaultRule("../outside", "op")
    with pytest.raises(ValueError):
        FaultRule("lost", "op", action="lose_response", timing="before")


def test_controlled_transform_preserves_vectors_and_mutates_only_protocol_dimension():
    raw = json.dumps(
        {
            "data": [
                {"index": 0, "embedding": [0.1, 0.2]},
                {"index": 1, "embedding": [0.3, 0.4]},
            ]
        }
    ).encode()
    reordered = json.loads(transform_provider_response(raw, "reordered"))
    assert reordered["data"] == [
        {"index": 1, "embedding": [0.3, 0.4]},
        {"index": 0, "embedding": [0.1, 0.2]},
    ]
    duplicate = json.loads(transform_provider_response(raw, "duplicate_indices"))
    assert [item["index"] for item in duplicate["data"]] == [0, 0]
    assert [item["embedding"] for item in duplicate["data"]] == [[0.1, 0.2], [0.3, 0.4]]
    assert len(json.loads(transform_provider_response(raw, "missing"))["data"]) == 1
    assert len(json.loads(transform_provider_response(raw, "extra"))["data"]) == 3
    assert json.loads(transform_provider_response(raw, "wrong_dimension"))["data"][0][
        "embedding"
    ] == [0.1]


@pytest.mark.parametrize("encoding", ["array", "base64"])
def test_provider_wire_values_agree_with_real_sdk_decode_and_keep_exact_index_associations(
    encoding,
):
    import httpx
    from openai import OpenAI

    vectors = [[3.0, 4.0], [5.0, 12.0]]
    encoded = (
        [
            base64.b64encode(struct.pack("<2f", *values)).decode("ascii")
            for values in vectors
        ]
        if encoding == "base64"
        else vectors
    )
    body = {
        "object": "list",
        "model": "control",
        "usage": {"prompt_tokens": 2, "total_tokens": 2},
        "data": [
            {"object": "embedding", "index": index, "embedding": values}
            for index, values in enumerate(encoded)
        ],
    }
    reordered = json.loads(
        transform_provider_response(json.dumps(body).encode(), "reordered")
    )
    with OpenAI(
        api_key="control",
        base_url="http://offline.invalid/v1",
        http_client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=reordered)
            )
        ),
    ) as sdk:
        actual = sdk.embeddings.create(input=["first", "second"], model="control")
    assert [(item.index, item.embedding) for item in actual.data] == [
        (1, vectors[1]),
        (0, vectors[0]),
    ]
    by_index = {
        item["index"]: provider_vector_values(item["embedding"])
        for item in reordered["data"]
    }
    assert by_index == {0: vectors[0], 1: vectors[1]}
    assert [
        value / math.sqrt(sum(number * number for number in by_index[0]))
        for value in by_index[0]
    ] == [0.6, 0.8]
    duplicate = json.loads(
        transform_provider_response(json.dumps(body).encode(), "duplicate_indices")
    )
    missing = json.loads(
        transform_provider_response(json.dumps(body).encode(), "missing_indices")
    )
    assert [item["index"] for item in duplicate["data"]] == [0, 0]
    assert [item["index"] for item in missing["data"]] == [2, 3]
    assert (
        [item["embedding"] for item in duplicate["data"]]
        == encoded
        == [item["embedding"] for item in missing["data"]]
    )


@pytest.mark.parametrize("encoding", ["array", "base64"])
def test_wrong_dimension_and_nonfinite_are_actual_vector_faults_in_both_wire_encodings(
    encoding,
):
    values = [1.0 + index / 1024 for index in range(768)]
    encoded = (
        base64.b64encode(struct.pack("<768f", *values)).decode("ascii")
        if encoding == "base64"
        else values
    )
    original = {
        "data": [{"index": 0, "embedding": encoded}, {"index": 1, "embedding": encoded}]
    }
    raw = json.dumps(original).encode()
    wrong = json.loads(transform_provider_response(raw, "wrong_dimension"))
    assert isinstance(wrong["data"][0]["embedding"], type(encoded))
    assert [provider_vector_values(item["embedding"]) for item in wrong["data"]] == [
        values[:-1],
        values[:-1],
    ]
    malformed = json.loads(transform_provider_response(raw, "nonfinite"))
    assert isinstance(malformed["data"][0]["embedding"], type(encoded))
    faulty_values = provider_vector_values(malformed["data"][0]["embedding"])
    assert len(faulty_values) == 768 and math.isnan(faulty_values[0])
    assert faulty_values[1:] == values[1:]
    assert malformed["data"][1] == original["data"][1]
    assert json.loads(raw) == original, (
        "Controlled transforms must leave the captured original response unchanged"
    )


def test_provider_vector_decoder_rejects_truncated_float32_encoding():
    with pytest.raises(ValueError, match="complete float32"):
        provider_vector_values(base64.b64encode(b"abc").decode("ascii"))


@pytest.mark.parametrize("encoding", ["array", "base64"])
def test_provider_forwarding_retains_exact_transformed_response_and_delivery_ack(
    tmp_path, encoding
):
    values = [3.0, 4.0]
    encoded = (
        base64.b64encode(struct.pack("<2f", *values)).decode("ascii")
        if encoding == "base64"
        else values
    )
    body = {
        "data": [{"index": 0, "embedding": encoded}, {"index": 1, "embedding": encoded}]
    }
    controller = FaultController(tmp_path)
    controller.install(
        [
            FaultRule(
                "indices",
                "http.embedding",
                timing="after",
                action="response",
                status=200,
                response={"__transform__": "duplicate_indices"},
            )
        ]
    )
    with (
        TinyUpstream(body) as upstream,
        ForwardingProxy(upstream.url, controller, provider="embedding") as proxy,
    ):
        request = Request(
            proxy.url + "/v1/embeddings",
            data=b'{"input":["first","second"]}',
            headers={"Content-Type": "application/json", "X-E2E-Operation-Id": "wire"},
        )
        with urlopen(request, timeout=3) as response:
            raw = response.read()
        transformed = controller.events(kind="provider_response_transformed")[0]
        delivered = controller.events(kind="provider_response_delivered")[0]
        assert transformed["body"] == json.loads(raw)
        assert [item["index"] for item in transformed["body"]["data"]] == [0, 0]
        assert [item["embedding"] for item in transformed["body"]["data"]] == [
            encoded,
            encoded,
        ]
        assert transformed["transformed_sha256"] == delivered["transformed_sha256"]
        assert (
            transformed["upstream_sha256"]
            == controller.events(kind="upstream_outcome")[0]["response_sha256"]
        )
        assert (
            delivered["status"] == 200 and delivered["transform"] == "duplicate_indices"
        )
        controller.assert_triggered()


def test_every_resilience_manifest_variant_has_a_concrete_handler():
    from tests.e2e.non_analysis import resilience

    scenarios = resilience.RESILIENCE_SCENARIOS
    keys = {(scenario.case_id, scenario.variant_id) for scenario in scenarios}
    assert len(keys) == len(scenarios)
    for scenario in scenarios:
        assert callable(getattr(resilience, "_execute_" + scenario.action, None)), (
            scenario
        )


def test_fault_correlation_covers_all_mutation_endpoints_and_both_id_origins():
    from tests.e2e.non_analysis.resilience import RESILIENCE_SCENARIOS

    expected = {"provider_generated_request_id", "provider_supplied_request_id"}
    expected.update(
        f"{method}_provider_{kind}_request_id"
        for method in ("put", "patch")
        for kind in ("generated", "supplied")
    )
    expected.update(
        f"{endpoint}_qdrant_{kind}_request_id"
        for endpoint in ("delete", "bulk")
        for kind in ("generated", "supplied")
    )
    cases = [
        scenario for scenario in RESILIENCE_SCENARIOS if scenario.case_id == "API-11"
    ]
    assert {scenario.variant_id for scenario in cases} == expected
    assert len(cases) == 10
    assert {scenario.method for scenario in cases} == {"POST", "PUT", "PATCH", "DELETE"}
    for endpoint in ("put", "patch", "delete", "bulk"):
        pair = [
            scenario
            for scenario in cases
            if scenario.variant_id.startswith(endpoint + "_")
        ]
        assert {scenario.parameters["supplied"] for scenario in pair} == {False, True}


@pytest.mark.parametrize("mode", ["missing", "incompatible"])
def test_alias_fault_restores_guarded_target_before_raw_store_capture(
    tmp_path, monkeypatch, mode
):
    import httpx

    from tests.e2e.non_analysis import resilience

    state = {"target": "physical", "attempts": 0, "captures": []}

    class AdminClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, path):
            return httpx.Response(
                200,
                request=httpx.Request("GET", "http://owned" + path),
                json={
                    "result": {
                        "aliases": [
                            {"alias_name": "active", "collection_name": "physical"}
                        ]
                    }
                },
            )

        def post(self, path, *, json):
            for action in json["actions"]:
                if "delete_alias" in action:
                    state["target"] = None
                if "create_alias" in action:
                    state["target"] = action["create_alias"]["collection_name"]
            return httpx.Response(
                200,
                request=httpx.Request("POST", "http://owned" + path),
                json={"result": True},
            )

        def put(self, path, *, json):
            return httpx.Response(
                200,
                request=httpx.Request("PUT", "http://owned" + path),
                json={"result": True},
            )

        def delete(self, path):
            return httpx.Response(
                200,
                request=httpx.Request("DELETE", "http://owned" + path),
                json={"result": True},
            )

    def snapshot(parent):
        assert state["target"] == "physical", (
            "Raw oracle consulted during an intentionally unsafe alias state"
        )
        state["captures"].append(parent)
        return {"sql": None, "points": []}

    def request(method, path, **kwargs):
        state["attempts"] += 1
        return httpx.Response(
            201, headers={"X-Request-Id": "observed"}, json={"status": 201}
        )

    harness = SimpleNamespace(
        config=SimpleNamespace(
            run_id="offline",
            alias="active",
            collection="physical",
            dense_name="dense",
            sparse_name="sparse",
            dense_dimension=768,
            database=SimpleNamespace(qdrant_url="http://owned", q_api_key="private"),
        ),
        infrastructure=SimpleNamespace(verify=lambda: None),
        new_id=lambda label: "fixture",
        request=request,
        snapshot=snapshot,
        assert_consistent=lambda parent, **kwargs: snapshot(parent),
        snapshot_outbox=lambda parent: [{"retry_count": 1}],
        drain_outbox=lambda: None,
    )
    monkeypatch.setattr(httpx, "Client", AdminClient)
    monkeypatch.setattr(
        resilience,
        "_record",
        lambda h, s, c, parents: [h.snapshot(parent) for parent in parents],
    )
    controller = FaultController(tmp_path)
    scenario = resilience.ResilienceScenario(
        "ING-F12", mode, "alias", parameters={"alias_mode": mode}
    )
    resilience._execute_alias(harness, scenario, controller)
    assert (
        state["attempts"] == 1 and state["target"] == "physical" and state["captures"]
    )
    assert controller.events(kind="alias_fault_installed")[0]["acknowledged"] is True
    assert controller.events(kind="alias_fault_response")[0]["status"] == 201
    assert controller.events(kind="alias_restored")[0]["acknowledged"] is True
    if mode == "incompatible":
        created = controller.events(kind="alias_collection_created")[0]
        removed = controller.events(kind="alias_collection_deleted")[0]
        assert (
            created["collection"]
            == removed["collection"]
            == "test_e2e_offline_wrong_schema"
        )
        assert created["owner_run_id"] == removed["owner_run_id"] == "offline"
        assert created["acknowledged"] is removed["acknowledged"] is True


@pytest.mark.parametrize("capture_fails", [False, True])
def test_assertion_failure_keeps_active_epoch_final_state_without_masking_primary_error(
    tmp_path, monkeypatch, capture_fails
):
    from tests.e2e.non_analysis import resilience

    controller = FaultController(tmp_path / "faults")
    state = {"settled": False, "captured": False}
    harness = SimpleNamespace(
        app=SimpleNamespace(
            overrides={"E2E_FAULT_DIR": str(tmp_path / "faults")},
            factory=True,
            running=True,
        ),
        fault_controller=controller,
        registered_ids={"fixture"},
        settle_requests=lambda: state.update(settled=True),
        config=SimpleNamespace(artifacts_dir=tmp_path, secrets=lambda: ()),
        snapshot=lambda parent: {"sql": None, "points": []},
    )
    real_capture = resilience._record

    def handler(h, s, c):
        c.install([FaultRule("fault", "operation", action="reject")])
        c.hit(c.invocation("operation", "fixture"), "before")
        raise AssertionError("original product failure")

    def capture(h, s, c, ids, *, label):
        assert state["settled"] and ids == ["fixture"] and label == "final"
        assert c._schedule()["rules"][0]["rule_id"] == "fault"
        assert c.events(kind="fault_matched", epoch=c._schedule()["epoch"])
        state["captured"] = True
        if capture_fails:
            raise RuntimeError("strict alias guard still rejects")
        real_capture(h, s, c, ids, label=label)

    monkeypatch.setattr(resilience, "_execute_offline_final", handler, raising=False)
    monkeypatch.setattr(resilience, "_record", capture)
    with pytest.raises(AssertionError, match="original product failure") as error:
        resilience.execute_resilience(
            harness,
            resilience.ResilienceScenario("FLOW-05", "offline", "offline_final"),
        )
    assert state["captured"] and not controller._schedule()["rules"]
    assert bool(controller.events(kind="final_capture_failed")) == capture_fails
    if capture_fails:
        assert error.value.__notes__ == [
            "Final fault/state capture failed: RuntimeError"
        ]
    else:
        evidence = json.loads(
            (tmp_path / "fault_evidence/FLOW-05-offline/final.json").read_text(
                encoding="utf-8"
            )
        )
        assert evidence["fault_schedule"]["rules"][0]["rule_id"] == "fault"
        assert evidence["stores"] == {"fixture": {"sql": None, "points": []}}


@pytest.mark.parametrize(
    "expectation",
    [
        {"require_exists": True},
        {"expected_version": 1},
        {"expected_deleted": False},
        {"expected_deleted": True},
        {"chunks_count": 0},
        {"chunks_count": 3},
        {"expected_fields": {}},
        {"expected_fields": {"title": "accepted title"}},
    ],
)
def test_consistency_rejects_lost_accepted_parent_even_without_orphan_vectors(
    expectation,
):
    from tests.e2e.non_analysis.oracles import assert_consistent

    with pytest.raises(AssertionError, match="Expected SQL parent is absent"):
        assert_consistent(
            {"sql": None, "points": []},
            SimpleNamespace(),
            parent_id="accepted",
            **expectation,
        )


def test_explicit_missing_state_still_allows_absence_but_rejects_orphan_points():
    from tests.e2e.non_analysis.oracles import assert_consistent

    assert_consistent(
        {"sql": None, "points": []},
        SimpleNamespace(),
        parent_id="missing",
        require_exists=False,
    )
    with pytest.raises(
        AssertionError, match="Vector points exist without a SQL parent"
    ):
        assert_consistent(
            {"sql": None, "points": [{"id": "orphan"}]},
            SimpleNamespace(),
            require_exists=False,
        )


@pytest.mark.parametrize("residual", [True, False])
def test_both_ingest_compensation_failures_cannot_pass_with_residual_state(
    tmp_path, monkeypatch, residual
):
    import httpx

    from tests.e2e.non_analysis import resilience

    state = {
        "sql": {"id": "fixture", "version": 1} if residual else None,
        "points": [{"id": "abandoned", "payload": {"chunk_status": "staging"}}]
        if residual
        else [],
    }
    harness = SimpleNamespace(
        config=SimpleNamespace(artifacts_dir=tmp_path, secrets=lambda: ()),
        snapshot=lambda parent: state,
    )
    controller = FaultController(tmp_path / "faults")
    monkeypatch.setattr(
        resilience,
        "_prepare",
        lambda h, method: ("fixture", {"sql": None, "points": []}, "request"),
    )

    def outbox_request(h, method, parent, request):
        for rule in controller._schedule()["rules"]:
            for _ in range(rule["attempt"]):
                invocation = controller.invocation(
                    rule["operation"], parent, request_id=request
                )
                try:
                    controller.hit(invocation, rule["timing"])
                except Exception:
                    pass
        return httpx.Response(
            201, json={"data": {"suggestionId": parent, "version": 1, "chunksCount": 1}}
        )

    monkeypatch.setattr(resilience, "_request", outbox_request)
    scenario = resilience.ResilienceScenario(
        "ING-F08",
        "both_compensations_failed",
        "ingest_compensation",
        parameters={"sql_cleanup": True, "vector_cleanup": True},
    )
    if not residual:
        with pytest.raises(AssertionError, match="persistent SQL record"):
            resilience._execute_ingest_compensation(harness, scenario, controller)
    else:
        resilience._execute_ingest_compensation(harness, scenario, controller)
    controller.assert_triggered()
    recorded = json.loads(
        (
            tmp_path / "fault_evidence/ING-F08-both_compensations_failed/settled.json"
        ).read_text(encoding="utf-8")
    )
    assert recorded["stores"]["fixture"] == state


@pytest.mark.parametrize("outcome", ["orphan", "missing", "coherent"])
def test_deleted_noop_without_qdrant_requires_coherent_existing_tombstone(
    tmp_path, monkeypatch, outcome
):
    import httpx

    from tests.e2e.non_analysis import resilience
    from tests.e2e.non_analysis.harness import LiveHarness

    state = {
        "sql": None
        if outcome == "missing"
        else {"id": "fixture", "version": 2, "is_deleted": True},
        "points": [{"id": "orphan", "payload": {"chunk_status": "active"}}]
        if outcome == "orphan"
        else [],
    }
    harness = SimpleNamespace(
        config=SimpleNamespace(artifacts_dir=tmp_path, secrets=lambda: ()),
        snapshot=lambda parent: state,
    )
    harness.assert_consistent = lambda parent, **expected: (
        LiveHarness.assert_consistent(harness, parent, **expected)
    )
    controller = FaultController(tmp_path / "faults")
    monkeypatch.setattr(resilience, "_seed", lambda h, label: "fixture")
    monkeypatch.setattr(
        resilience,
        "_request",
        lambda *args, **kwargs: httpx.Response(200, json={"status": 200}),
    )
    scenario = resilience.ResilienceScenario(
        "DEL-13", "deleted_noop_without_qdrant", "delete_no_qdrant", method="DELETE"
    )
    if outcome == "coherent":
        resilience._execute_delete_no_qdrant(harness, scenario, controller)
    else:
        with pytest.raises(
            AssertionError,
            match="retains vector points"
            if outcome == "orphan"
            else "Expected SQL parent is absent",
        ):
            resilience._execute_delete_no_qdrant(harness, scenario, controller)
    assert not controller.events(kind="fault_matched"), (
        "No-op must still prove that it never contacted Qdrant"
    )


@pytest.mark.parametrize("outcome", ["absent", "staging", "wrong_count", "coherent"])
def test_race_ingest_first201_requires_coherence_before_competing_write_baseline(
    tmp_path, monkeypatch, outcome
):
    import httpx

    from tests.e2e.non_analysis import resilience
    from tests.e2e.non_analysis.harness import LiveHarness
    from tests.e2e.non_analysis.oracles import STATUS_TITLES

    row = {
        "id": "fixture",
        "version": 1,
        "is_deleted": False,
        "title": "accepted title",
        "problem": None,
        "solution": None,
        "status_id": 1,
        "context_title": None,
        "shamsi_date": None,
        "committee_scrutiny_id": None,
        "secretariat_scrutiny_id": None,
    }
    point = {
        "id": "accepted-point",
        "payload": {
            "parent_id": "fixture",
            "chunk_type": "title",
            "content": "accepted title",
            "chunk_status": "staging" if outcome == "staging" else "active",
            "status": STATUS_TITLES[1],
            "context_title": None,
            "date": None,
            "committee_scrutiny_id": None,
            "secretariat_scrutiny_id": None,
        },
        "vector": {"dense": [1.0], "sparse": {"indices": [1], "values": [0.5]}},
    }
    state = {
        "sql": None if outcome == "absent" else row,
        "points": [] if outcome == "absent" else [point],
    }
    harness = SimpleNamespace(
        config=SimpleNamespace(
            artifacts_dir=tmp_path,
            secrets=lambda: (),
            request_timeout=5,
            dense_dimension=1,
            dense_name="dense",
            sparse_name="sparse",
        ),
        new_id=lambda label: "fixture",
        snapshot=lambda parent: state,
    )
    harness.assert_consistent = lambda parent, **expected: (
        LiveHarness.assert_consistent(harness, parent, **expected)
    )
    controller = FaultController(tmp_path / "faults")

    def request(h, method, parent, request_id, suffix):
        controller.hit(
            controller.invocation("sql.read", parent, request_id=request_id),
            "after",
            found=False,
        )
        first = suffix == "برنده اول"
        return httpx.Response(
            201 if first else 409,
            json={"data": {"chunksCount": 2 if outcome == "wrong_count" else 1}},
        )

    monkeypatch.setattr(resilience, "_request", request)
    scenario = resilience.ResilienceScenario(
        "ING-F10", "same_id_both_duplicate_checks", "race_ingest"
    )
    if outcome == "coherent":
        resilience._execute_race_ingest(harness, scenario, controller)
        baseline = json.loads(
            (
                tmp_path
                / "fault_evidence/ING-F10-same_id_both_duplicate_checks/accepted_first.json"
            ).read_text(encoding="utf-8")
        )
        assert baseline["stores"]["fixture"] == state
    else:
        message = {
            "absent": "Expected SQL parent is absent",
            "staging": "lifecycle state",
            "wrong_count": "HTTP chunk count",
        }[outcome]
        with pytest.raises(AssertionError, match=message):
            resilience._execute_race_ingest(harness, scenario, controller)
        assert not (
            tmp_path
            / "fault_evidence/ING-F10-same_id_both_duplicate_checks/accepted_first.json"
        ).exists()
    controller.assert_triggered()


@pytest.mark.parametrize("explicit_match", [False, True])
def test_inherited_test_qdrant_exports_do_not_ban_the_guarded_default_listener(
    tmp_path, monkeypatch, explicit_match
):
    from tests.database_safety import DatabaseTestConfig, TestDatabaseSafetyError
    from tests.e2e.non_analysis import harness
    from tests.e2e.non_analysis.config import E2EConfig

    database = DatabaseTestConfig(
        "127.0.0.1",
        7442,
        "tavanir_test_db",
        "tavanir_test",
        "test-password",
        "admin-password",
        "127.0.0.1",
        7343,
        7344,
        "vector-key",
        "offline-marker",
    )
    config = E2EConfig(
        database,
        repo_root=tmp_path,
        run_id="offline",
        artifacts_dir=tmp_path / "evidence",
        api_key="test-key",
    )
    (tmp_path / ".env").write_text(
        "QDRANT_PORT=6333\nQDRANT_GRPC_PORT=6334\nPOSTGRES_PORT=5432\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("QDRANT_PORT", "7343")
    monkeypatch.setenv("QDRANT_GRPC_PORT", "7344")
    monkeypatch.setenv("POSTGRES_PORT", "7442")
    monkeypatch.setattr(
        harness.subprocess,
        "Popen",
        lambda *args, **kwargs: pytest.fail(
            "Constructor control must never launch a host"
        ),
    )
    overrides = {"E2E_FAULT_DIR": str(tmp_path / "faults")}
    if explicit_match:
        overrides.update(QDRANT_PORT="7343", QDRANT_GRPC_PORT="7344")
    process = harness.AppProcess(
        config,
        app="tests.e2e.non_analysis.bootstrap:create_app",
        factory=True,
        overrides=overrides,
        port=19990,
    )
    assert process.factory and process.process is None
    with pytest.raises(TestDatabaseSafetyError, match="development service ports"):
        harness.AppProcess(config, overrides={"QDRANT_PORT": "6333"}, port=19990)
    with pytest.raises(TestDatabaseSafetyError, match="gRPC listener"):
        harness.AppProcess(config, overrides={"QDRANT_GRPC_PORT": "19996"}, port=19990)
    with pytest.raises(
        TestDatabaseSafetyError, match="real|live run-owned proxy proof"
    ):
        harness.AppProcess(config, overrides={"QDRANT_PORT": "19994"}, port=19990)
    monkeypatch.setenv("QDRANT_PORT", "19995")
    permissive_spoof = SimpleNamespace(validate_owned_endpoint=lambda **kwargs: None)
    with pytest.raises(TestDatabaseSafetyError, match="development service ports"):
        harness.AppProcess(
            config,
            overrides={"QDRANT_PORT": "19995"},
            qdrant_proxy_proof=permissive_spoof,
            port=19990,
        )


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH"])
@pytest.mark.parametrize("violation", [None, "status", "code", "pointer", "writes"])
def test_typed_normalization_fault_obeys_422_contract_and_preserves_store(
    tmp_path, monkeypatch, method, violation
):
    import httpx

    from src.application.exceptions import TextNormalizationError
    from tests.e2e.non_analysis import resilience

    before = {
        "sql": None if method == "POST" else {"id": "fixture", "version": 1},
        "points": [],
    }
    after = (
        before
        if violation != "writes"
        else {"sql": {"id": "fixture", "version": 2}, "points": []}
    )
    harness = SimpleNamespace(
        config=SimpleNamespace(artifacts_dir=tmp_path, secrets=lambda: ()),
        snapshot=lambda parent: after,
    )
    controller = FaultController(tmp_path / "faults")
    scenario = next(
        item
        for item in resilience.RESILIENCE_SCENARIOS
        if item.case_id == "DEP-05"
        and item.variant_id == f"{method.lower()}_normalizer"
    )
    monkeypatch.setattr(
        resilience, "_prepare", lambda *args: ("fixture", before, "norm-request")
    )

    def request(h, method, parent, request_id):
        with pytest.raises(TextNormalizationError):
            controller.hit(
                controller.invocation(
                    "normalizer.normalize", parent, request_id=request_id
                ),
                "before",
            )
        return httpx.Response(
            500 if violation == "status" else 422,
            json={
                "errors": [
                    {
                        "code": "INTERNAL_ERROR"
                        if violation == "code"
                        else "TEXT_NORMALIZATION_FAILED",
                        "source": {
                            "pointer": "/other" if violation == "pointer" else "/data"
                        },
                    }
                ]
            },
        )

    monkeypatch.setattr(resilience, "_request", request)
    if violation is None:
        resilience._execute_early(harness, scenario, controller)
    else:
        with pytest.raises(AssertionError):
            resilience._execute_early(harness, scenario, controller)
    controller.assert_triggered()


@pytest.mark.parametrize("deleted", [False, True])
def test_put_typed_normalization_fault_obeys_422_contract_for_active_and_deleted_parents(
    tmp_path, monkeypatch, deleted
):
    import httpx

    from src.application.exceptions import TextNormalizationError
    from tests.e2e.non_analysis import resilience

    state = {
        "sql": {"id": "fixture", "version": 2 if deleted else 1, "is_deleted": deleted},
        "points": [],
    }
    harness = SimpleNamespace(
        config=SimpleNamespace(artifacts_dir=tmp_path, secrets=lambda: ()),
        snapshot=lambda parent: state,
    )
    controller = FaultController(tmp_path / "faults")
    scenario = resilience.ResilienceScenario(
        "PUT-12",
        "normalization-contract",
        "put_failure",
        method="PUT",
        parameters={"phase": "normalizer.normalize", "deleted": deleted},
    )
    monkeypatch.setattr(resilience, "_seed", lambda *args: "fixture")

    def request(h, method, parent, request_id):
        if method == "DELETE":
            return httpx.Response(200)
        with pytest.raises(TextNormalizationError):
            controller.hit(
                controller.invocation(
                    "normalizer.normalize", parent, request_id=request_id
                ),
                "before",
            )
        return httpx.Response(
            422,
            json={
                "errors": [
                    {
                        "code": "TEXT_NORMALIZATION_FAILED",
                        "source": {"pointer": "/data"},
                    }
                ]
            },
        )

    monkeypatch.setattr(resilience, "_request", request)
    resilience._execute_put_failure(harness, scenario, controller)
    controller.assert_triggered()


def test_generic_normalization_runtime_fault_retains_500_contract(
    tmp_path, monkeypatch
):
    import httpx

    from tests.e2e.non_analysis import resilience

    state = {"sql": None, "points": []}
    harness = SimpleNamespace(
        config=SimpleNamespace(artifacts_dir=tmp_path, secrets=lambda: ()),
        snapshot=lambda parent: state,
    )
    controller = FaultController(tmp_path / "faults")
    scenario = resilience.ResilienceScenario(
        "DEP-05",
        "generic-normalization-runtime",
        "early",
        parameters={
            "operation": "normalizer.normalize",
            "error": "runtime",
            "status": 500,
        },
    )
    monkeypatch.setattr(
        resilience, "_prepare", lambda *args: ("fixture", state, "norm-request")
    )

    def request(h, method, parent, request_id):
        with pytest.raises(RuntimeError):
            controller.hit(
                controller.invocation(
                    "normalizer.normalize", parent, request_id=request_id
                ),
                "before",
            )
        return httpx.Response(500, json={"errors": [{"code": "INTERNAL_ERROR"}]})

    monkeypatch.setattr(resilience, "_request", request)
    resilience._execute_early(harness, scenario, controller)
    controller.assert_triggered()
