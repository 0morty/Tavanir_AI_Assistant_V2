"""Test-only, reversible Python tracing and secret-safe wire recording.

Line events snapshot changed locals immediately BEFORE the displayed source line.
CALL/RETURN events retain complete values, including token offsets and item bodies.
No production methods are replaced by the instrumentation.
"""

from __future__ import annotations

import dataclasses
import dis
import enum
import json
import linecache
import sys
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import FrameType
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SENSITIVE = ("api_key", "authorization", "password", "cookie", "access_token", "secret")
PREFIXES = (
    "src/application/context/",
    "src/application/prompt/prompt_builder.py",
    "src/application/llm/llm_request_builder.py",
    "src/application/reference/",
    "src/application/dtos.py",
    "src/domain/context/",
    "src/domain/overflow_strategy_stack.py",
    "src/domain/entities.py",
    "src/infrastructure/services/tokenizers/qwen_tokenizer.py",
    "src/infrastructure/services/summarizers/",
    "src/infrastructure/services/llm/",
    "src/infrastructure/services/base_openai_service.py",
    "src/infrastructure/configs/llm_provider_configs.py",
)
ACCESSORS = {
    "section_type",
    "pre_context",
    "post_context",
    "importance",
    "demand",
    "overflow_strategies",
    "supports_offset_mapping",
    "remaining_need",
    "items",
    "citation_ids",
    "history_messages",
    "citation_map",
    "sections",
    "chunks",
    "reference",
    "description",
    "details",
    "strategies",
    "restart",
    "max_restarts",
}
STATE_FILES = (
    "allocation/",
    "context_builder.py",
    "referenced_collection_section.py",
    "overflow/truncate.py",
    "llm_chunk_summarizer.py",
)


class TraceCollector:
    def __init__(self, *, secrets: tuple[str, ...] = ()) -> None:
        self.events: list[dict[str, Any]] = []
        self.scenario = "setup"
        self._secrets = tuple(value for value in secrets if value and value != "EMPTY")
        self._lock = threading.RLock()
        self._frames: dict[int, tuple[int, dict[str, Any]]] = {}
        self._next_call = 0

    def snapshot(self, value: Any, seen: frozenset[int] = frozenset()) -> Any:
        if isinstance(value, enum.Enum):
            return value.value
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            for secret in self._secrets:
                value = value.replace(secret, "[REDACTED]")
            return value
        if isinstance(value, Path):
            return str(value)
        if id(value) in seen:
            return {"cycle": type(value).__qualname__}
        seen = seen | {id(value)}
        if isinstance(value, Mapping):
            return {
                str(key): "[REDACTED]"
                if any(word in str(key).lower() for word in SENSITIVE)
                else self.snapshot(item, seen)
                for key, item in value.items()
            }
        if isinstance(value, (tuple, list)):
            return [self.snapshot(item, seen) for item in value]
        if isinstance(value, (set, frozenset)):
            return [self.snapshot(item, seen) for item in sorted(value, key=str)]
        if isinstance(value, BaseException):
            return {
                "type": type(value).__name__,
                "message": self.snapshot(str(value), seen),
            }
        if isinstance(value, type):
            return {"class": value.__module__ + "." + value.__qualname__}
        if dataclasses.is_dataclass(value):
            return {
                field.name: self.snapshot(getattr(value, field.name), seen)
                for field in dataclasses.fields(value)
            }
        module = type(value).__module__
        if module.startswith("openai.types.") and hasattr(value, "model_dump"):
            return self.snapshot(value.model_dump(mode="json"), seen)
        if module.startswith(("src.", __package__)) and hasattr(value, "__dict__"):
            return {
                "class": module + "." + type(value).__qualname__,
                "state": self.snapshot(vars(value), seen),
            }
        # Third-party transports/tokenizer internals are not application content.
        # Never traverse their credential-bearing connection pools or vocabularies.
        return {"external_type": module + "." + type(value).__qualname__}

    def emit(
        self, event: str, *, component: str = "harness", function: str = "", **data: Any
    ) -> dict:
        with self._lock:
            record = {
                "step": len(self.events) + 1,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "scenario": self.scenario,
                "event": event,
                "component": component,
                "function": function,
                "thread": threading.current_thread().name,
                **self.snapshot(data),
            }
            self.events.append(record)
            return record

    def check(self, reason: str, actual: Any, expected: Any) -> None:
        passed = actual == expected
        self.emit(
            "ASSERTION",
            reason=reason,
            actual=actual,
            expected=expected,
            status="PASS" if passed else "FAIL",
        )
        if not passed:
            raise AssertionError(f"{reason}: expected {expected!r}, got {actual!r}")

    def _trace(self, frame: FrameType, event: str, arg: Any):
        filename = Path(frame.f_code.co_filename).as_posix()
        root_prefix = ROOT.as_posix() + "/"
        if not filename.startswith(root_prefix):
            return None
        relative = filename[len(root_prefix) :]
        if not relative.startswith(PREFIXES):
            return None
        if frame.f_code.co_name in ACCESSORS or frame.f_code.co_name.startswith("<"):
            return None
        fid = id(frame)
        function = frame.f_code.co_qualname
        common = {
            "component": frame.f_globals.get("__name__", relative),
            "function": function,
            "file": relative,
            "line": frame.f_lineno,
        }
        if event == "call":
            if fid in self._frames:
                call_id, _ = self._frames[fid]
                self.emit("RESUME", call_id=call_id, **common)
            else:
                with self._lock:
                    self._next_call += 1
                    call_id = self._next_call
                    self._frames[fid] = (call_id, {})
                parent = frame.f_back
                parent_id = None
                while parent is not None:
                    if id(parent) in self._frames:
                        parent_id = self._frames[id(parent)][0]
                        break
                    parent = parent.f_back
                self.emit(
                    "CALL",
                    call_id=call_id,
                    parent_call_id=parent_id,
                    arguments=frame.f_locals,
                    **common,
                )
        elif fid in self._frames:
            call_id, previous = self._frames[fid]
            if event == "line" and any(part in relative for part in STATE_FILES):
                state = self.snapshot(
                    {
                        key: value
                        for key, value in frame.f_locals.items()
                        if key != "self"
                    }
                )
                changed = {
                    key: value
                    for key, value in state.items()
                    if key not in previous or value != previous[key]
                }
                if changed:
                    self.emit(
                        "STATE",
                        call_id=call_id,
                        changed_locals=changed,
                        decision="State before executing the displayed source line",
                        source=linecache.getline(filename, frame.f_lineno).strip(),
                        **common,
                    )
                    self._frames[fid] = (call_id, state)
            elif event == "exception":
                self.emit("EXCEPTION", call_id=call_id, error=arg[1], **common)
            elif event == "return":
                opcode = dis.opname[frame.f_code.co_code[frame.f_lasti]]
                suspended = opcode in {"YIELD_VALUE", "YIELD_FROM"}
                self.emit(
                    "SUSPEND" if suspended else "RETURN",
                    call_id=call_id,
                    result=arg,
                    state=frame.f_locals if frame.f_code.co_name == "__init__" else {},
                    **common,
                )
                if not suspended:
                    self._frames.pop(fid, None)
        return self._trace

    @contextmanager
    def instrument(self) -> Iterator[None]:
        old_sys, old_thread = sys.gettrace(), threading.gettrace()
        if old_sys is not None or old_thread is not None:
            raise RuntimeError("Run the audit without a debugger/coverage tracer")
        sys.settrace(self._trace)
        threading.settrace(self._trace)
        try:
            yield
        finally:
            sys.settrace(old_sys)
            threading.settrace(old_thread)
            self._frames.clear()


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
