"""Instrumented subprocess factory preserving the real app and DI graph.

Only collaborators are wrapped. The original lifespan still initializes/shuts
down resources, and no use case, repository algorithm, or production file is
replaced. Every wrapper delegates to the existing implementation unless its
explicit run-owned schedule matches this exact invocation.
"""
from __future__ import annotations

import inspect
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, get_origin
from urllib.parse import unquote

from tests.e2e.non_analysis.proxy import FaultController, REQUEST_CONTEXT, input_fingerprint


METHOD_OPERATIONS = {
    "get_by_id": "sql.read", "get_by_ids": "sql.read_many",
    "save": "sql.save", "save_batch": "sql.save_many",
    "soft_delete": "sql.soft_delete", "delete": "sql.delete",
    "delete_batch": "sql.delete_many", "commit": "sql.commit",
    "rollback": "sql.rollback", "try_acquire_advisory_lock": "sql.lock",
    "chunk": "chunker.chunk", "embed_document": "sparse.embed_one",
    "embed_documents": "sparse.embed", "embed_query": "sparse.query",
    "normalize": "normalizer.normalize", "normalize_async": "normalizer.normalize_async",
    "normalize_batch": "normalizer.batch", "normalize_batch_async": "normalizer.batch_async",
    "upsert_chunk": "vector.upsert_one", "upsert_chunks_batch": "vector.upsert",
    "activate_staging_chunks": "vector.promote", "activate_staging_chunks_batch": "vector.promote_many",
    "delete_chunks_by_parent_id": "vector.purge", "delete_chunks_by_parent_ids": "vector.purge_many",
    "delete_chunks_by_ids": "vector.delete_ids", "delete_staging_chunks": "vector.delete_staging",
    "delete_deprecated_chunks": "vector.delete_deprecated", "delete_superseded_chunks": "vector.superseded",
}


def _parent(method: str, args: tuple[Any, ...], fallback: str = "") -> str:
    if args:
        value = args[0]
        if method in {"get_by_id", "soft_delete", "delete", "delete_chunks_by_parent_id",
                      "activate_staging_chunks", "delete_staging_chunks", "delete_deprecated_chunks",
                      "delete_superseded_chunks"}:
            return str(value)
        if hasattr(value, "id"):
            return str(value.id)
        if hasattr(value, "parent_id"):
            return str(value.parent_id)
        if isinstance(value, (list, tuple)) and value and hasattr(value[0], "parent_id"):
            parents = {str(chunk.parent_id) for chunk in value}
            if len(parents) == 1:
                return next(iter(parents))
    return fallback or REQUEST_CONTEXT.get().get("parent_id", "")


def _result_evidence(method: str, result: Any, args: tuple[Any, ...]) -> dict[str, Any]:
    data: dict[str, Any] = {"delegate_called": True}
    if method in {"get_by_id", "save"}:
        entity = result if method == "get_by_id" else args[0]
        data.update(found=entity is not None,
                    version=getattr(entity, "version", None), is_deleted=getattr(entity, "is_deleted", None))
    if method == "try_acquire_advisory_lock":
        data["lock_acquired"] = bool(result)
    if method in {"upsert_chunks_batch", "chunk"}:
        chunks = result if method == "chunk" else args[0]
        data["chunk_ids"] = [str(chunk.chunk_id) for chunk in chunks]
        data["chunks_count"] = len(chunks)
    if method in {"commit", "upsert_chunks_batch", "activate_staging_chunks",
                  "delete_chunks_by_parent_id", "delete_superseded_chunks", "delete_chunks_by_ids"}:
        data["applied"] = True
    return data


def wrap_collaborator(interface: type, delegate: Any, controller: FaultController,
                      *, parent_callback: Any = None) -> Any:
    """Construct an explicit ABC implementation with transparent forwarding.

    Generated methods cover the interface's complete abstract surface. This is
    test composition, not a service locator; the delegate and controller are
    required constructor dependencies. Unknown methods cannot be intercepted
    silently: they use an explicit method-name operation in the event journal.
    """
    interface = get_origin(interface) or interface

    def initialize(self: Any, *, delegate: Any, controller: FaultController) -> None:
        self._delegate = delegate
        self._controller = controller

    def prepare(self: Any, method: str, args: tuple[Any, ...]) -> dict[str, Any]:
        parent = _parent(method, args)
        if parent_callback and parent:
            parent_callback(parent)
        metadata: dict[str, Any] = {}
        if method.startswith("normalize") or method.startswith("embed"):
            metadata["fingerprint"] = input_fingerprint(args[0] if args else None)
        return self._controller.invocation(METHOD_OPERATIONS.get(method, method), parent, **metadata)

    namespace: dict[str, Any] = {"__init__": initialize, "__module__": __name__}
    for method in sorted(interface.__abstractmethods__):
        specification = getattr(interface, method)
        if isinstance(specification, property):
            namespace[method] = property(lambda self, name=method: getattr(self._delegate, name))
        elif inspect.iscoroutinefunction(specification):
            def build_async(name: str):
                async def forwarded(self: Any, *args: Any, **kwargs: Any) -> Any:
                    invocation = prepare(self, name, args)
                    try:
                        before = await self._controller.ahit(invocation, "before", delegate_called=False, applied=False)
                        if before and before["action"] == "zero":
                            self._controller.record("zero_result", **invocation, delegate_called=False)
                            return []
                        result = await getattr(self._delegate, name)(*args, **kwargs)
                        after = await self._controller.ahit(invocation, "after", **_result_evidence(name, result, args))
                        if after and after["action"] == "response" and after.get("response") == {"__transform__": "malformed_sparse"}:
                            # A deliberately malformed collaborator return exercises
                            # the real downstream DTO/Qdrant validation boundary.
                            from types import SimpleNamespace
                            result = list(result)
                            result[0] = SimpleNamespace(indices=[1, 2], values=[0.5])
                        return result
                    except BaseException as error:
                        self._controller.record("collaborator_error", **invocation, error_type=type(error).__name__)
                        raise
                return forwarded
            namespace[method] = build_async(method)
        else:
            def build_sync(name: str):
                def forwarded(self: Any, *args: Any, **kwargs: Any) -> Any:
                    invocation = prepare(self, name, args)
                    try:
                        before = self._controller.hit(invocation, "before", delegate_called=False, applied=False)
                        if before and before["action"] == "zero":
                            return []
                        result = getattr(self._delegate, name)(*args, **kwargs)
                        self._controller.hit(invocation, "after", delegate_called=True)
                        return result
                    except BaseException as error:
                        self._controller.record("collaborator_error", **invocation, error_type=type(error).__name__)
                        raise
                return forwarded
            namespace[method] = build_sync(method)
    wrapper_class = type(f"Instrumented{interface.__name__}", (interface,), namespace)
    return wrapper_class(delegate=delegate, controller=controller)


def wrap_unit_of_work(delegate: Any, controller: FaultController) -> Any:
    from src.application.interfaces import IUnitOfWork
    from src.domain.interfaces import ISuggestionRepository

    class InstrumentedUnitOfWork(IUnitOfWork):
        def __init__(self, *, delegate: IUnitOfWork, controller: FaultController) -> None:
            self._delegate = delegate
            self._controller = controller
            self._parent_id = ""
            self._repository = None

        def _set_parent(self, parent_id: str) -> None:
            self._parent_id = parent_id

        @property
        def suggestions(self):
            if self._repository is None:
                self._repository = wrap_collaborator(ISuggestionRepository, self._delegate.suggestions,
                                                    self._controller, parent_callback=self._set_parent)
            return self._repository

        @property
        def checkpoints(self):
            return self._delegate.checkpoints

        @property
        def skipped_suggestions(self):
            return self._delegate.skipped_suggestions

        async def __aenter__(self):
            await self._delegate.__aenter__()
            self._repository = None
            self._parent_id = ""
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            try:
                await self._delegate.__aexit__(exc_type, exc_value, traceback)
            finally:
                self._repository = None

        async def _call(self, name: str, *args):
            invocation = self._controller.invocation(METHOD_OPERATIONS[name], self._parent_id)
            await self._controller.ahit(invocation, "before", delegate_called=False, applied=False)
            result = await getattr(self._delegate, name)(*args)
            await self._controller.ahit(invocation, "after", **_result_evidence(name, result, args))
            return result

        async def commit(self):
            return await self._call("commit")

        async def rollback(self):
            return await self._call("rollback")

        async def try_acquire_advisory_lock(self, lock_key: int):
            return await self._call("try_acquire_advisory_lock", lock_key)

    return InstrumentedUnitOfWork(delegate=delegate, controller=controller)


class FaultRequestContext:
    def __init__(self, app: Any, *, controller: FaultController) -> None:
        self.app = app
        self.controller = controller

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {key.decode().lower(): value.decode() for key, value in scope["headers"]}
        path = scope.get("path", "")
        if "/analyze" in path:
            await send({"type": "http.response.start", "status": 403, "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body", "body": b'{"error":"analysis excluded from E2E"}'})
            return
        request_id = headers.get("x-e2e-operation-id", uuid.uuid4().hex)
        parent = headers.get("x-e2e-parent-id", "")
        if not parent and path.startswith("/api/v1/suggestions/") and scope.get("method") in {"PUT", "PATCH", "DELETE"}:
            parent = unquote(path.rsplit("/", 1)[-1])
        token = REQUEST_CONTEXT.set({"request_id": request_id, "parent_id": parent})
        self.controller.record("request_started", request_id=request_id, parent_id=parent,
                               method=scope.get("method"), path=path)
        try:
            await self.app(scope, receive, send)
        finally:
            self.controller.record("request_finished", request_id=request_id, parent_id=parent)
            REQUEST_CONTEXT.reset(token)


def install_instrumentation(container: Any, controller: FaultController) -> None:
    from dependency_injector import providers
    from src.application.interfaces import ISparseEmbedder, ITextNormalizer
    from src.domain.interfaces import ISuggestionChunker, ISuggestionVectorRepository

    # Instrument exact REST-equivalent Qdrant phases inside the real client too;
    # this provides the demote/promote boundary that a repository wrapper alone
    # cannot observe. External profiles use ForwardingProxy instead.
    qdrant_provider = container.qdrant_client
    real_qdrant = qdrant_provider()
    qdrant_provider.override(providers.Object(QdrantPhaseClient(real_qdrant, controller)))

    # Clone the provider recipe before overriding; retaining the old overridden
    # provider would recursively resolve its own wrapper. Dependencies retain
    # their original provider identity and resource ownership.
    for name, interface in (("text_normalizer", ITextNormalizer), ("sparse_embedder", ISparseEmbedder),
                            ("suggestion_chunker", ISuggestionChunker),
                            ("suggestion_vector_repository", ISuggestionVectorRepository)):
        provider = getattr(container, name)
        real_provider = type(provider)(provider.provides, *provider.args, **provider.kwargs)
        wrapped_provider = providers.Factory(wrap_collaborator, interface=providers.Object(interface),
                                            delegate=real_provider, controller=providers.Object(controller))
        provider.override(wrapped_provider)
    provider = container.unit_of_work
    real_provider = providers.Factory(provider.provides, *provider.args, **provider.kwargs)
    provider.override(providers.Factory(wrap_unit_of_work, delegate=real_provider,
                                       controller=providers.Object(controller)))
    controller.record("instrumentation_installed", providers=["unit_of_work", "text_normalizer", "sparse_embedder",
                                                             "suggestion_chunker", "suggestion_vector_repository", "qdrant_client"])


class QdrantPhaseClient:
    """Transparent third-party client decorator; no invented production port."""
    def __init__(self, delegate: Any, controller: FaultController) -> None:
        self._delegate = delegate
        self._controller = controller

    def __getattr__(self, name):
        return getattr(self._delegate, name)

    async def _call(self, method: str, operation: str, **kwargs):
        parent = REQUEST_CONTEXT.get().get("parent_id", "")
        point_ids = []
        points = kwargs.get("points")
        if isinstance(points, list):
            point_ids = [str(getattr(point, "id", "")) for point in points]
            parents = {str(getattr(point, "payload", {}).get("parent_id", "")) for point in points}
            if len(parents) == 1:
                parent = next(iter(parents))
        qfilter = kwargs.get("points") or kwargs.get("points_selector")
        if hasattr(qfilter, "filter"):
            qfilter = qfilter.filter
        for condition in getattr(qfilter, "must", []) or []:
            if getattr(condition, "key", None) == "parent_id":
                parent = str(getattr(getattr(condition, "match", None), "value", ""))
        invocation = self._controller.invocation(operation, parent, point_ids=point_ids)
        await self._controller.ahit(invocation, "before", delegate_called=False, applied=False)
        result = await getattr(self._delegate, method)(**kwargs)
        status = getattr(getattr(result, "status", None), "value", getattr(result, "status", None))
        await self._controller.ahit(invocation, "after", delegate_called=True, applied=status == "completed", application_result=status)
        return result

    async def set_payload(self, **kwargs):
        operation = "qdrant.promote" if kwargs.get("payload", {}).get("chunk_status") == "active" else "qdrant.demote"
        return await self._call("set_payload", operation, **kwargs)

    async def upsert(self, **kwargs):
        return await self._call("upsert", "qdrant.upsert", **kwargs)

    async def delete(self, **kwargs):
        return await self._call("delete", "qdrant.delete", **kwargs)


def create_app():
    directory = os.environ.get("E2E_FAULT_DIR")
    if not directory:
        raise RuntimeError("Instrumented E2E subprocess requires E2E_FAULT_DIR")
    from src.main import create_app as real_create_app
    app = real_create_app(is_mock=False)
    controller = FaultController(Path(directory))
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def instrumented_lifespan(application):
        async with original_lifespan(application):
            install_instrumentation(application.state.container, controller)
            try:
                yield
            finally:
                controller.release_all()

    app.router.lifespan_context = instrumented_lifespan
    app.add_middleware(FaultRequestContext, controller=controller)
    return app
