"""Owned forwarding proxy and an acknowledged, process-safe fault schedule.

The control directory is private runner state, never an HTTP administration API.
Every invocation is keyed by request, operation, parent/fingerprint, and attempt.
Barriers signal arrival before waiting and expire loudly. Event files survive an
application crash; after-forward events distinguish applied writes from rejection.
"""
from __future__ import annotations

import asyncio
import base64
import contextvars
import copy
import hashlib
import json
import os
import re
import socket
import struct
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


REQUEST_CONTEXT: contextvars.ContextVar[dict[str, str]] = contextvars.ContextVar(
    "non_analysis_fault_request", default={}
)


@dataclass(frozen=True)
class FaultRule:
    rule_id: str
    operation: str
    action: str = "raise"
    timing: str = "before"
    parent_id: str | None = None
    request_id: str | None = None
    attempt: int | list[int] | None = 1
    fingerprint: str | None = None
    barrier_timeout: float = 30.0
    error: str = "runtime"
    status: int = 503
    response: Any = None
    response_headers: dict[str, str] | None = None

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", self.rule_id):
            raise ValueError("Fault rule ID must be a safe filename")
        if self.action not in {"raise", "barrier", "zero", "cancel", "reject", "response", "lose_response", "reset"}:
            raise ValueError(f"Unsupported fault action: {self.action}")
        if self.timing not in {"before", "after"}:
            raise ValueError("Fault timing must be before or after")
        if self.action == "lose_response" and self.timing != "after":
            raise ValueError("A lost response must happen after actual forwarding")
        if self.barrier_timeout <= 0:
            raise ValueError("Barrier timeout must be positive")


class BarrierExpired(TimeoutError):
    pass


class FaultController:
    """Filesystem protocol shared by runner, proxy threads, and owned app.

    Atomic per-event files avoid interleaved JSONL writes across processes. Counters
    belong to each controller/process and include a schedule epoch; installing a
    new schedule explicitly resets attempts even in a persistent app process.
    """

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory).resolve()
        self.events_directory = self.directory / "events"
        self.gates_directory = self.directory / "gates"
        self.events_directory.mkdir(parents=True, exist_ok=True)
        self.gates_directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._attempts: dict[tuple[str, ...], int] = {}
        self._epoch = ""

    def install(self, rules: list[FaultRule]) -> str:
        ids = [rule.rule_id for rule in rules]
        if len(set(ids)) != len(ids):
            raise ValueError("Fault rule IDs must be unique")
        epoch = uuid.uuid4().hex
        payload = {"epoch": epoch, "rules": [asdict(rule) for rule in rules]}
        path = self.directory / "rules.json"
        temp = self.directory / f"rules-{epoch}.tmp"
        temp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, path)
        self.record("schedule_installed", epoch=epoch, rule_ids=ids)
        return epoch

    def _schedule(self) -> dict[str, Any]:
        path = self.directory / "rules.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"epoch": "initial", "rules": []}

    def invocation(self, operation: str, parent_id: str | None = None, **metadata: Any) -> dict[str, Any]:
        context = REQUEST_CONTEXT.get()
        schedule = self._schedule()
        parent = parent_id or context.get("parent_id", "")
        request_id = metadata.pop("request_id", context.get("request_id", ""))
        # Count operation attempts across distinct batch bodies. Fingerprints
        # constrain rule matches but cannot reset the later-batch ordinal.
        key = (request_id, operation, parent)
        with self._lock:
            if self._epoch != schedule["epoch"]:
                self._attempts.clear()
                self._epoch = schedule["epoch"]
            attempt = self._attempts.get(key, 0) + 1
            self._attempts[key] = attempt
        return {"epoch": schedule["epoch"], "invocation_id": uuid.uuid4().hex,
                "operation": operation, "parent_id": parent, "request_id": request_id,
                "attempt": attempt, **metadata}

    def record(self, kind: str, **data: Any) -> dict[str, Any]:
        event = {"kind": kind, "time_ns": time.time_ns(), "pid": os.getpid(), **data}
        path = self.events_directory / f"{event['time_ns']:020d}-{uuid.uuid4().hex}.json"
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(event, ensure_ascii=False, default=str), encoding="utf-8")
        os.replace(temp, path)
        return event

    def events(self, **criteria: Any) -> list[dict[str, Any]]:
        events = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(self.events_directory.glob("*.json"))]
        return [event for event in events if all(event.get(key) == value for key, value in criteria.items())]

    def wait(self, timeout: float = 30.0, **criteria: Any) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            matches = self.events(**criteria)
            if matches:
                return matches[-1]
            time.sleep(0.01)  # Polling a recorded phase event, never timing a race.
        self.record("wait_expired", criteria=criteria, timeout=timeout)
        raise BarrierExpired(f"No acknowledged phase event for {criteria}")

    def release(self, rule_id: str, *, epoch: str | None = None) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", rule_id):
            raise ValueError("Unsafe barrier ID")
        epoch = epoch or self._schedule()["epoch"]
        (self.gates_directory / f"{epoch}-{rule_id}.release").touch()
        self.record("barrier_released", rule_id=rule_id, epoch=epoch)

    def release_all(self) -> None:
        schedule = self._schedule()
        for rule in schedule["rules"]:
            if rule["action"] == "barrier":
                self.release(rule["rule_id"], epoch=schedule["epoch"])

    def unmatched_rules(self) -> list[str]:
        schedule = self._schedule()
        fired = {event["rule_id"] for event in self.events(kind="fault_matched", epoch=schedule["epoch"])}
        return [rule["rule_id"] for rule in schedule["rules"] if rule["rule_id"] not in fired]

    def assert_triggered(self) -> None:
        schedule = self._schedule()
        matches = self.events(kind="fault_matched", epoch=schedule["epoch"])
        missing = self.unmatched_rules()
        if missing:
            raise AssertionError(f"Fault schedule did not trigger: {missing}")
        incomplete = {}
        for rule in schedule["rules"]:
            attempts = rule.get("attempt")
            if isinstance(attempts, list):
                required = {attempt for attempt in attempts if type(attempt) is int}
                observed = {event["attempt"] for event in matches if event["rule_id"] == rule["rule_id"]}
                if required - observed:
                    incomplete[rule["rule_id"]] = sorted(required - observed)
        if incomplete:
            raise AssertionError(f"Fault schedule missed required attempts: {incomplete}")
        expired = self.events(epoch=schedule["epoch"], kind="barrier_expired")
        if expired:
            raise AssertionError(f"Fault barriers expired: {expired}")

    def hit(self, invocation: dict[str, Any], timing: str, **evidence: Any) -> dict[str, Any] | None:
        self.record("phase", **invocation, timing=timing, **evidence)
        schedule = self._schedule()
        if schedule["epoch"] != invocation["epoch"]:
            return None
        decision = None
        for rule in schedule["rules"]:
            if rule["operation"] != invocation["operation"] or rule["timing"] != timing:
                continue
            if any(rule.get(key) is not None and rule[key] != invocation.get(key)
                   for key in ("request_id", "parent_id", "fingerprint")):
                continue
            attempts = rule.get("attempt")
            if attempts is not None and invocation["attempt"] not in (attempts if isinstance(attempts, list) else [attempts]):
                continue
            self.record("fault_matched", **invocation, timing=timing, rule_id=rule["rule_id"], action=rule["action"], **evidence)
            if rule["action"] == "barrier":
                self.record("barrier_entered", **invocation, timing=timing, rule_id=rule["rule_id"], **evidence)
                gate = self.gates_directory / f"{invocation['epoch']}-{rule['rule_id']}.release"
                deadline = time.monotonic() + rule["barrier_timeout"]
                while not gate.exists():
                    if time.monotonic() >= deadline:
                        self.record("barrier_expired", **invocation, rule_id=rule["rule_id"])
                        raise BarrierExpired(f"Barrier {rule['rule_id']} expired")
                    time.sleep(0.01)
                self.record("barrier_passed", **invocation, rule_id=rule["rule_id"])
            else:
                decision = rule
                if rule["action"] in {"raise", "cancel"}:
                    self._raise(rule)
        return decision

    async def ahit(self, invocation: dict[str, Any], timing: str, **evidence: Any) -> dict[str, Any] | None:
        return await asyncio.to_thread(self.hit, invocation, timing, **evidence)

    @staticmethod
    def _raise(rule: dict[str, Any]) -> None:
        if rule["action"] == "cancel":
            raise asyncio.CancelledError(f"Injected cancellation: {rule['rule_id']}")
        message = f"Injected {rule['error']} fault: {rule['rule_id']}"
        if rule["error"] == "vector":
            from src.domain.exceptions import VectorStorageError
            raise VectorStorageError(message)
        if rule["error"] == "sparse":
            from src.application.exceptions import SparseEmbedderError
            raise SparseEmbedderError(message)
        if rule["error"] == "chunker":
            from src.domain.exceptions import SuggestionChunkingError
            raise SuggestionChunkingError(message)
        if rule["error"] == "chunking":
            from src.domain.exceptions import ChunkingError
            raise ChunkingError(message)
        if rule["error"] == "connection":
            import httpx
            raise httpx.ConnectError(message)
        if rule["error"] == "normalizer":
            from src.application.exceptions import TextNormalizationError
            raise TextNormalizationError(message)
        raise RuntimeError(message)


def input_fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def provider_vector_values(vector: list[float] | str) -> list[float]:
    """Read OpenAI array/base64 float32 wire values for controlled fault proof."""
    if isinstance(vector, str):
        raw = base64.b64decode(vector, validate=True)
        if not raw or len(raw) % 4:
            raise ValueError("Provider base64 vector must contain complete float32 values")
        return list(struct.unpack(f"<{len(raw) // 4}f", raw))
    if not isinstance(vector, list) or not vector or any(type(value) not in {int, float} for value in vector):
        raise ValueError("Provider vector must be a numeric array or base64 float32")
    return list(vector)


def _provider_vector_wire(values: list[float], original: list[float] | str) -> list[float] | str:
    if isinstance(original, str):
        return base64.b64encode(struct.pack(f"<{len(values)}f", *values)).decode("ascii")
    return values


def transform_provider_response(raw: bytes, transform: str) -> bytes:
    """Preserve real vectors while introducing a single protocol defect."""
    if transform == "decoding":
        return b"not JSON: deliberately malformed owned provider response"
    value = json.loads(raw)
    items = value["data"]
    if transform == "missing":
        value["data"] = items[:-1]
    elif transform == "extra":
        value["data"] = [*items, {**items[-1], "index": len(items)}]
    elif transform == "reordered":
        value["data"] = list(reversed(items))
    elif transform == "duplicate_indices":
        for item in items:
            item["index"] = 0
    elif transform == "missing_indices":
        for item in items:
            item["index"] += len(items)
    elif transform == "wrong_dimension":
        for item in items:
            original = item["embedding"]
            item["embedding"] = _provider_vector_wire(provider_vector_values(original)[:-1], original)
    elif transform == "nonfinite":
        original = items[0]["embedding"]
        values = provider_vector_values(original)
        values[0] = float("nan")
        items[0]["embedding"] = _provider_vector_wire(values, original)
    else:
        raise ValueError("Unknown controlled response transform")
    return json.dumps(value).encode()


def classify_request(path: str, body: Any, provider: str) -> tuple[str, str, str]:
    """Parse REST operation identity without using production repositories."""
    path = urlsplit(path).path
    if provider == "embedding":
        return "http.embedding", "", input_fingerprint(body.get("input") if isinstance(body, dict) else body)
    if not isinstance(body, dict):
        body = {}
    points = body.get("points", [])
    parent = ""
    if isinstance(points, list) and points and isinstance(points[0], dict):
        parents = {str(point.get("payload", {}).get("parent_id", "")) for point in points}
        parent = next(iter(parents)) if len(parents) == 1 else ""
    qfilter = body.get("filter") or {}
    if not isinstance(qfilter, dict):
        qfilter = {}
    for condition in qfilter.get("must", []) if isinstance(qfilter, dict) else []:
        if condition.get("key") == "parent_id":
            parent = str(condition.get("match", {}).get("value", ""))
    operation = "http.qdrant.other"
    if "/points/delete" in path:
        operation = "http.qdrant.delete"
        if qfilter.get("must_not"):
            operation = "http.qdrant.superseded"
        elif isinstance(points, list) and points:
            operation = "http.qdrant.delete_ids"
    elif "/points/payload" in path:
        operation = "http.qdrant.promote" if body.get("payload", {}).get("chunk_status") == "active" else "http.qdrant.demote"
    elif path.rstrip("/").endswith("/points") and points:
        operation = "http.qdrant.upsert"
    return operation, parent, input_fingerprint(body)


def _endpoint_identity(url: str) -> tuple:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    host = "127.0.0.1" if host == "localhost" else host
    return parsed.scheme.lower(), host, parsed.port or (443 if parsed.scheme == "https" else 80), parsed.path.rstrip("/"), parsed.query, parsed.fragment


@dataclass(frozen=True)
class _ProxyOwnershipProof:
    proxy: ForwardingProxy
    run_id: str

    def validate_owned_endpoint(self, *, run_id: str, host: str, port: int, expected_upstream: str) -> None:
        proxy = self.proxy
        requested_host = host.lower().rstrip(".")
        requested_host = "127.0.0.1" if requested_host == "localhost" else requested_host
        if not self.run_id or run_id != self.run_id or proxy.provider != "qdrant":
            raise ValueError("Qdrant proxy proof does not belong to this run")
        if proxy._thread is None or not proxy._thread.is_alive() or proxy._server.socket.fileno() < 0:
            raise ValueError("Qdrant proxy proof requires a live owned listener")
        listener = proxy._server.socket.getsockname()
        if requested_host != listener[0] or int(port) != listener[1]:
            raise ValueError("Qdrant override does not select the owned proxy listener")
        if _endpoint_identity(proxy.upstream) != _endpoint_identity(expected_upstream):
            raise ValueError("Qdrant proxy upstream does not match the guarded test database")


class ForwardingProxy:
    """Loopback-only forwarding proxy; stores no credentials in event journals."""

    def __init__(self, upstream: str, controller: FaultController, *, provider: str,
                 host: str = "127.0.0.1", port: int = 0, upstream_timeout: float = 30.0) -> None:
        if host not in {"127.0.0.1", "localhost"}:
            raise ValueError("The E2E proxy must bind loopback")
        if provider not in {"qdrant", "embedding", "application"}:
            raise ValueError("Unsupported forwarding target")
        parsed = urlsplit(upstream)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("Upstream must be an HTTP URL without embedded credentials")
        self.upstream = upstream.rstrip("/")
        self.controller = controller
        self.provider = provider
        self.timeout = upstream_timeout
        self._upstream_responses: list[dict[str, Any]] = []
        self._responses_lock = threading.Lock()
        proxy = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_: Any) -> None:
                pass

            def do_GET(self) -> None:
                self._forward()

            do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_GET

            def _forward(self) -> None:
                raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                try:
                    body = json.loads(raw) if raw else {}
                except ValueError:
                    body = {"invalid_json_sha256": hashlib.sha256(raw).hexdigest()}
                operation, parent, fingerprint = classify_request(self.path, body, proxy.provider)
                if proxy.provider == "application":
                    if "/analyze" in self.path:
                        self._send(403, b'{"error":"analysis excluded from E2E"}', {})
                        return
                    operation = "http.application"
                    parent = self.headers.get("X-E2E-Parent-Id", "")
                invocation = proxy.controller.invocation(operation, parent, fingerprint=fingerprint,
                    request_id=self.headers.get("X-E2E-Operation-Id", ""), method=self.command,
                    path=urlsplit(self.path).path, request_body_sha256=hashlib.sha256(raw).hexdigest())
                try:
                    before = proxy.controller.hit(invocation, "before", forwarded=False, applied=False)
                    if before and before["action"] == "reset":
                        try:
                            self.connection.shutdown(socket.SHUT_RDWR)
                        except OSError:
                            pass
                        self.connection.close()
                        self.close_connection = True
                        return
                    if before and before["action"] in {"reject", "response"}:
                        replacement = json.dumps(before.get("response") or {"error": {"message": "Injected provider failure", "type": "server_error"}}).encode()
                        self._send(before["status"], replacement, {"Content-Type": "application/json", **(before.get("response_headers") or {})})
                        return
                    headers = {key: value for key, value in self.headers.items()
                               if key.lower() not in {"host", "connection", "content-length", "transfer-encoding", "accept-encoding"}}
                    request = Request(proxy.upstream + self.path, data=raw if raw else None, method=self.command, headers=headers)
                    try:
                        response = urlopen(request, timeout=proxy.timeout)
                    except HTTPError as response_error:
                        response = response_error
                    with response:
                        status = response.status
                        response_body = response.read()
                        response_headers = dict(response.headers.items())
                    if proxy.provider == "application":
                        # Keep application wire evidence in memory until the
                        # harness persists it through its configured sanitizer.
                        with proxy._responses_lock:
                            proxy._upstream_responses.append({**invocation, "status": status,
                                "headers": response_headers,
                                "body": response_body.decode("utf-8", errors="replace"),
                                "body_sha256": hashlib.sha256(response_body).hexdigest()})
                    applied = False
                    application_result = None
                    try:
                        parsed_response = json.loads(response_body)
                        application_result = parsed_response.get("result", {}).get("status") if isinstance(parsed_response.get("result"), dict) else None
                        applied = status < 300 and (proxy.provider != "qdrant" or application_result == "completed")
                    except (ValueError, AttributeError):
                        applied = status < 300 and proxy.provider != "qdrant"
                    # For Qdrant, an HTTP 200 acknowledgement can be asynchronous.
                    # Only status=completed is evidence of actual upstream application.
                    proxy.controller.record("upstream_outcome", **invocation, forwarded=True, applied=applied,
                        upstream_status=status, application_result=application_result,
                        response_sha256=hashlib.sha256(response_body).hexdigest())
                    after = proxy.controller.hit(invocation, "after", forwarded=True, applied=applied, upstream_status=status)
                    if after and after["action"] == "lose_response":
                        try:
                            self.connection.shutdown(socket.SHUT_RDWR)
                        except OSError:
                            pass
                        self.connection.close()
                        self.close_connection = True
                        return
                    if after and after["action"] == "response":
                        replacement = after["response"]
                        if isinstance(replacement, dict) and "__transform__" in replacement:
                            transformed = transform_provider_response(response_body, replacement["__transform__"])
                            proxy.controller.record("provider_response_transformed", **invocation,
                                transform=replacement["__transform__"], status=after["status"],
                                upstream_sha256=hashlib.sha256(response_body).hexdigest(),
                                transformed_sha256=hashlib.sha256(transformed).hexdigest(),
                                body=json.loads(transformed) if replacement["__transform__"] != "decoding" else transformed.decode("utf-8"))
                            # Retain association evidence using vector digests; raw
                            # inputs and credentials never enter proxy logs.
                            try:
                                original = json.loads(response_body)["data"]
                                proxy.controller.record("provider_association", **invocation,
                                    inputs=body.get("input") if isinstance(body, dict) else None,
                                    vectors=[{"index": item["index"], "digest": input_fingerprint(item["embedding"]),
                                              "vector": item["embedding"]} for item in original])
                            except (ValueError, KeyError, TypeError):
                                pass
                        else:
                            transformed = json.dumps(replacement).encode()
                        self._send(after["status"], transformed, {"Content-Type": "application/json"})
                        if isinstance(replacement, dict) and "__transform__" in replacement:
                            proxy.controller.record("provider_response_delivered", **invocation,
                                transform=replacement["__transform__"], status=after["status"],
                                transformed_sha256=hashlib.sha256(transformed).hexdigest())
                    else:
                        self._send(status, response_body, response_headers)
                except (URLError, TimeoutError, OSError, RuntimeError) as error:
                    proxy.controller.record("proxy_error", **invocation, error_type=type(error).__name__)
                    try:
                        self._send(502, b'{"error":"owned E2E forwarding failed"}', {"Content-Type": "application/json"})
                    except OSError:
                        pass

            def _send(self, status: int, body: bytes, headers: dict[str, str]) -> None:
                self.send_response(status)
                for key, value in headers.items():
                    if key.lower() not in {"content-length", "transfer-encoding", "connection", "content-encoding"}:
                        self.send_header(key, value)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(body)
                self.close_connection = True

        self._server = ThreadingHTTPServer((host, port), Handler)
        self._server.daemon_threads = True
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_port}"

    def upstream_responses(self, *, request_id: str | None = None) -> list[dict[str, Any]]:
        """Return in-memory application responses for sanitized harness evidence."""
        with self._responses_lock:
            return copy.deepcopy([record for record in self._upstream_responses
                                  if request_id is None or record["request_id"] == request_id])

    def ownership_proof(self, run_id: str) -> _ProxyOwnershipProof:
        return _ProxyOwnershipProof(self, run_id)

    def start(self) -> ForwardingProxy:
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True, name="owned-e2e-proxy")
        self._thread.start()
        self.controller.record("proxy_started", provider=self.provider, port=self._server.server_port)
        return self

    def close(self) -> None:
        self.controller.release_all()
        if self._thread is not None:
            self._server.shutdown()
            self._thread.join(timeout=5)
        self._server.server_close()
        self.controller.record("proxy_stopped", provider=self.provider)

    def __enter__(self) -> ForwardingProxy:
        return self.start()

    def __exit__(self, *_: Any) -> None:
        self.close()
