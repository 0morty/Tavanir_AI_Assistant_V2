"""Owned single-worker Uvicorn subprocess, ordinary TCP HTTP, and evidence."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import http.client
import ipaddress
import json
import os
import re
import runpy
import socket
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from dataclasses import replace
from pathlib import Path
from urllib.parse import unquote, urlsplit

import httpx
from dotenv import dotenv_values

from tests.database_safety import TestDatabaseSafetyError
from tests.e2e.non_analysis.config import E2EConfig
from tests.e2e.non_analysis.infrastructure import ManagedTestInfrastructure, free_port
from tests.e2e.non_analysis.oracles import FixtureRegistry, RawStoreOracle, assert_consistent, assert_unchanged, canonical


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _write_process_records(path: Path, records: list[dict] | dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _windows_process_rows(filter_text: str) -> list[dict]:
    # filter_text is constructed only from validated integer PIDs below.
    command = (
        "$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); "
        f"$e2eProcessRows = @(Get-CimInstance Win32_Process -Filter '{filter_text}' -ErrorAction Stop); "
        "$e2eProcessRows | Select-Object ProcessId,ParentProcessId,ExecutablePath,CommandLine | ConvertTo-Json -Compress"
    )
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise TestDatabaseSafetyError("Cannot query trusted Windows process identity")
    values = json.loads(result.stdout) if result.stdout.strip() else []
    return values if isinstance(values, list) else [values]


def _windows_api():
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)]
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.TerminateProcess.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    return kernel, ctypes, wintypes


def _windows_handle_creation(kernel, ctypes, wintypes, handle):
    timestamps = [wintypes.FILETIME() for _ in range(4)]
    if not kernel.GetProcessTimes(handle, *(ctypes.byref(item) for item in timestamps)):
        raise TestDatabaseSafetyError("Cannot verify native process creation identity")
    return str((timestamps[0].dwHighDateTime << 32) | timestamps[0].dwLowDateTime)


def _windows_console_path():
    kernel, ctypes, wintypes = _windows_api()
    kernel.GetSystemDirectoryW.argtypes = [wintypes.LPWSTR, wintypes.UINT]
    kernel.GetSystemDirectoryW.restype = wintypes.UINT
    buffer = ctypes.create_unicode_buffer(32768)
    length = kernel.GetSystemDirectoryW(buffer, len(buffer))
    if not length or length >= len(buffer):
        raise TestDatabaseSafetyError("Cannot establish trusted Windows console-host location")
    return str(Path(buffer.value) / "conhost.exe")


def _is_owned_console_host(identity: dict, parent: dict) -> bool:
    if os.name != "nt" or identity.get("parent_pid") != parent.get("pid"):
        return False
    expected = _windows_console_path()
    if os.path.normcase(identity.get("executable", "")) != os.path.normcase(expected):
        return False
    # CREATE_NO_WINDOW starts this specific system helper below the venv launcher.
    # Preserve the actual trusted OS identity; no arbitrary child executable is accepted.
    commands = {prefix + suffix + " 0x4" for prefix, suffix in
                (("", expected), ("", '"' + expected + '"'), ("\\??\\", expected), ('"\\??\\', expected + '"'))}
    if identity.get("command_line", "").casefold() not in {item.casefold() for item in commands}:
        return False
    try:
        return int(identity["creation_id"]) >= int(parent["creation_id"])
    except (KeyError, TypeError, ValueError):
        return False


def _query_process_identity(pid: int) -> dict | None:
    if type(pid) is not int or pid <= 0:
        raise TestDatabaseSafetyError("Owned process PID must be a positive integer")
    if os.name == "nt":
        rows = _windows_process_rows(f"ProcessId = {pid}")
        if not rows:
            return None
        if len(rows) != 1 or not rows[0].get("ExecutablePath") or not rows[0].get("CommandLine"):
            raise TestDatabaseSafetyError("Windows process identity is unavailable or ambiguous")
        kernel, ctypes, wintypes = _windows_api()
        handle = kernel.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            if not _windows_process_rows(f"ProcessId = {pid}"):
                return None  # The process exited between CIM and the native query.
            raise TestDatabaseSafetyError("Cannot open the owned process for identity verification")
        try:
            creation = _windows_handle_creation(kernel, ctypes, wintypes, handle)
        finally:
            kernel.CloseHandle(handle)
        row = rows[0]
        return {"pid": pid, "parent_pid": row["ParentProcessId"], "creation_id": creation, "executable": row["ExecutablePath"], "command_line": row["CommandLine"]}
    proc = Path(f"/proc/{pid}")
    try:
        stat = (proc / "stat").read_text().rsplit(")", 1)[1].split()
        command = (proc / "cmdline").read_bytes().split(b"\0")
        argv = [item.decode("utf-8", errors="strict") for item in command if item]
        if not argv:
            return None  # exited/zombie processes have no executable command
        return {"pid": pid, "parent_pid": int(stat[1]), "creation_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip() + ":" + stat[19], "executable": str((proc / "exe").resolve(strict=True)), "command_line": subprocess.list2cmdline(argv)}
    except FileNotFoundError:
        return None
    except (OSError, ValueError, UnicodeError):
        raise TestDatabaseSafetyError("Cannot query trusted process identity") from None


def _query_owned_children(identity: dict, command: list[str]) -> list[dict]:
    if os.name != "nt":
        return []  # A single-worker POSIX Python host does not use the venv launcher.
    children = []
    tail = subprocess.list2cmdline(command[1:])
    for row in _windows_process_rows(f"ParentProcessId = {identity['pid']}"):
        child = _query_process_identity(int(row["ProcessId"]))
        if child is None:
            continue
        if not child["command_line"].endswith(tail) and not _is_owned_console_host(child, identity):
            raise TestDatabaseSafetyError("Unexpected child process prevents safe owned-app recovery")
        children.append(child)
    return children


def _terminate_verified_process(identity: dict, timeout: float):
    current = _query_process_identity(identity["pid"])
    if current is None:
        return
    if current != identity:
        raise TestDatabaseSafetyError("Refusing to terminate a reused or changed process PID")
    if os.name == "nt":
        kernel, ctypes, wintypes = _windows_api()
        handle = kernel.OpenProcess(0x1000 | 0x0001 | 0x00100000, False, identity["pid"])
        if not handle:
            if _query_process_identity(identity["pid"]) is None:
                return
            raise TestDatabaseSafetyError("Cannot open verified process termination handle")
        try:
            if _windows_handle_creation(kernel, ctypes, wintypes, handle) != identity["creation_id"]:
                raise TestDatabaseSafetyError("Process creation changed before termination")
            if not kernel.TerminateProcess(handle, 137) or kernel.WaitForSingleObject(handle, int(timeout * 1000)) != 0:
                raise TestDatabaseSafetyError("Owned process did not terminate within its deadline")
        finally:
            kernel.CloseHandle(handle)
        return
    import signal
    if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
        raise TestDatabaseSafetyError("This OS cannot safely terminate a recovered process by creation identity")
    descriptor = os.pidfd_open(identity["pid"])
    try:
        if _query_process_identity(identity["pid"]) != identity:
            raise TestDatabaseSafetyError("Process creation changed before termination")
        signal.pidfd_send_signal(descriptor, signal.SIGKILL)
    finally:
        os.close(descriptor)


def recover_and_stop(config: E2EConfig, artifacts_dir: Path | None = None) -> dict:
    """Settle only persisted, OS-verified owned app processes before DB cleanup."""
    directory = Path(artifacts_dir or config.artifacts_dir).resolve()
    path = directory / "owned-processes.json"
    if not path.exists():
        raise TestDatabaseSafetyError("Owned process recovery evidence is missing; safe cleanup cannot be established")
    records = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise TestDatabaseSafetyError("Owned process recovery evidence is invalid")
    stopped = []
    for record in records:
        generation = record.get("generation")
        command = record.get("command")
        if record.get("run_id") != config.run_id or record.get("target") != config.redacted() or type(generation) is not int or generation <= 0:
            raise TestDatabaseSafetyError("Owned process recovery belongs to another run or target")
        stop_file = directory / f"stop-{generation}.signal"
        if record.get("stop_file") != str(stop_file) or not isinstance(command, list) or len(command) < 9 or command[1:4] != ["-m", "tests.e2e.non_analysis.harness", "--serve"] or "--stop-file" not in command or command[command.index("--stop-file") + 1] != str(stop_file):
            raise TestDatabaseSafetyError("Owned process recovery command or stop-file is outside its run")
        if record.get("verified_stopped") is True:
            continue
        identities = record.get("identities")
        if not isinstance(identities, list) or not identities:
            raise TestDatabaseSafetyError("Owned process creation identities are missing")
        alive = []
        for identity in identities:
            current = _query_process_identity(identity["pid"])
            if current is None:
                continue
            if current != identity or (not current["command_line"].endswith(subprocess.list2cmdline(command[1:])) and not _is_owned_console_host(current, identities[0])):
                raise TestDatabaseSafetyError("Live process identity is uncertain; refusing recovery actions")
            alive.append(identity)
        _assert_phase_descendants(identities, {})
        if alive:
            stop_file.touch()
            deadline = time.monotonic() + config.shutdown_timeout
            while alive and time.monotonic() < deadline:
                time.sleep(0.05)
                remaining = []
                for identity in alive:
                    current = _query_process_identity(identity["pid"])
                    if current is not None:
                        if current != identity:
                            raise TestDatabaseSafetyError("Process identity changed during graceful recovery")
                        remaining.append(identity)
                alive = remaining
            for identity in reversed(alive):
                _terminate_verified_process(identity, config.shutdown_timeout)
            for identity in identities:
                if _query_process_identity(identity["pid"]) is not None:
                    raise TestDatabaseSafetyError("Recovered app process remains live; refusing database cleanup")
            stopped.extend(identity["pid"] for identity in identities)
        _assert_phase_descendants(identities, {})
        record["verified_stopped"] = True
        record["stopped_utc"] = _utc_now()
        _write_process_records(path, records)
    return {"verified": True, "stopped_pids": stopped, "generations": len(records)}


def _phase_paths(config):
    directory = Path(config.artifacts_dir).resolve()
    return directory / "owned-pytest-process.json", directory / "pytest-arguments.json", directory / "pytest-start.signal"


def _phase_command(config, arguments_file, ready_file):
    return [config.python_executable, "-m", "tests.e2e.non_analysis.harness", "--pytest-args-file", str(arguments_file),
            "--phase-ready-file", str(ready_file), "--phase-startup-timeout", str(config.startup_timeout)]


def _validate_phase_record(config):
    journal, arguments_file, ready_file = _phase_paths(config)
    if not journal.is_file():
        raise TestDatabaseSafetyError("Owned pytest process proof is missing; refusing cleanup")
    record = json.loads(journal.read_text(encoding="utf-8"))
    if record.get("run_id") != config.run_id or record.get("target") != config.redacted() or record.get("command") != _phase_command(config, arguments_file, ready_file):
        raise TestDatabaseSafetyError("Owned pytest process proof belongs to another run or target")
    if not arguments_file.is_file() or hashlib.sha256(arguments_file.read_bytes()).hexdigest() != record.get("arguments_sha256"):
        raise TestDatabaseSafetyError("Owned pytest argument evidence changed or is missing")
    if record.get("kind", "pytest") == "preparation":
        arguments = json.loads(arguments_file.read_text(encoding="utf-8"))
        expected = (record.get("approval") or {}).get("script_sha256")
        if _preparation_approval(arguments, expected) != record.get("approval"):
            raise TestDatabaseSafetyError("Preparation module or script approval changed")
    elif record.get("kind", "pytest") != "pytest":
        raise TestDatabaseSafetyError("Owned Python execution kind is unsupported")
    identities = record.get("identities")
    if not isinstance(identities, list) or not identities:
        raise TestDatabaseSafetyError("Owned pytest creation identities are missing")
    return journal, record


def _known_application_identities(config):
    known = {}
    for path in Path(config.artifacts_dir).rglob("owned-processes.json"):
        records = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(records, list):
            raise TestDatabaseSafetyError("Application descendant proof is invalid")
        for record in records:
            if record.get("verified_stopped") is True:
                continue
            generation = record.get("generation")
            command = record.get("command")
            stop_file = path.parent.resolve() / f"stop-{generation}.signal"
            if record.get("run_id") != config.run_id or record.get("target") != config.redacted() or type(generation) is not int or generation <= 0:
                raise TestDatabaseSafetyError("Application descendant belongs to another run or target")
            if record.get("stop_file") != str(stop_file) or not isinstance(command, list) or len(command) < 9 or command[1:4] != ["-m", "tests.e2e.non_analysis.harness", "--serve"] or "--stop-file" not in command or command[command.index("--stop-file") + 1] != str(stop_file):
                raise TestDatabaseSafetyError("Application descendant command cannot be proven")
            identities = record.get("identities")
            if not isinstance(identities, list) or not identities:
                raise TestDatabaseSafetyError("Application descendant creation identities are missing")
            for identity in identities:
                current = _query_process_identity(identity["pid"])
                if current is None:
                    continue
                if current != identity or (not current["command_line"].endswith(subprocess.list2cmdline(command[1:])) and not _is_owned_console_host(current, identities[0])):
                    raise TestDatabaseSafetyError("Application descendant identity is uncertain")
                known[current["pid"]] = current
    return known


def _assert_phase_descendants(identities, known_apps):
    if os.name != "nt":
        return
    owned = {identity["pid"]: identity for identity in identities}
    owned.update(known_apps)
    for identity in owned.values():
        for row in _windows_process_rows(f"ParentProcessId = {identity['pid']}"):
            child = _query_process_identity(int(row["ProcessId"]))
            if child is None:
                continue
            expected = owned.get(child["pid"])
            if child != expected:
                raise TestDatabaseSafetyError("Unexpected owned process descendant prevents safe cleanup")


def recover_owned_pytest(config: E2EConfig) -> dict:
    """Settle the launcher, pytest host and console before settling app hosts."""
    journal, record = _validate_phase_record(config)
    if record.get("verified_stopped") is True:
        return {"verified": True, "stopped_pids": [], "return_code": record.get("return_code")}
    identities, alive = record["identities"], []
    for identity in identities:
        current = _query_process_identity(identity["pid"])
        if current is None:
            continue
        if current != identity or (not current["command_line"].endswith(subprocess.list2cmdline(record["command"][1:])) and not _is_owned_console_host(current, identities[0])):
            raise TestDatabaseSafetyError("Owned pytest identity is uncertain; refusing recovery actions")
        alive.append(identity)
    _assert_phase_descendants(identities, _known_application_identities(config))
    for identity in reversed(alive):
        _terminate_verified_process(identity, config.shutdown_timeout)
    if any(_query_process_identity(identity["pid"]) is not None for identity in identities):
        raise TestDatabaseSafetyError("Owned pytest process remains live; refusing cleanup")
    # Pytest cannot create new hosts after its identities have ended. Any last
    # host it created must have durable app proof before application cleanup.
    _assert_phase_descendants(identities, _known_application_identities(config))
    record.update(verified_stopped=True, stopped_utc=_utc_now())
    _write_process_records(journal, record)
    return {"verified": True, "stopped_pids": [item["pid"] for item in alive], "return_code": record.get("return_code")}


def run_owned_pytest(config: E2EConfig, arguments: list[str], *, output, environment: dict, timeout: float,
                     _kind: str = "pytest", _approval: dict | None = None, _capture_output: bool = False) -> int:
    """Run pytest only after durable OS proof, and verify descendants on exit."""
    journal, arguments_file, ready_file = _phase_paths(config)
    if journal.exists() or arguments_file.exists() or ready_file.exists():
        raise TestDatabaseSafetyError("Owned pytest phase artifacts already exist")
    arguments_file.parent.mkdir(parents=True, exist_ok=True)
    arguments_file.write_text(json.dumps(arguments, ensure_ascii=False), encoding="utf-8")
    command = _phase_command(config, arguments_file, ready_file)
    process = subprocess.Popen(command, cwd=config.repo_root, env=environment, stdout=subprocess.PIPE if _capture_output else output,
                               stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    drain = None
    if _capture_output:
        def capture():
            for line in process.stdout:
                try:
                    output.write(sanitize(line, config))
                    output.flush()
                except (OSError, ValueError):
                    return
        drain = threading.Thread(target=capture, name="e2e-preparation-output", daemon=True)
        drain.start()
    deadline = time.monotonic() + config.startup_timeout
    while True:
        identity = _query_process_identity(process.pid)
        if identity is None or not identity["command_line"].endswith(subprocess.list2cmdline(command[1:])):
            raise TestDatabaseSafetyError("Spawned pytest process identity cannot be proven")
        children = _query_owned_children(identity, command)
        if os.name != "nt" or any(child["command_line"].endswith(subprocess.list2cmdline(command[1:])) for child in children):
            break
        if time.monotonic() >= deadline:
            raise TestDatabaseSafetyError("Pytest launcher child proof was not captured before its deadline")
        time.sleep(0.05)
    record = {"run_id": config.run_id, "target": config.redacted(), "command": command, "arguments_sha256": hashlib.sha256(arguments_file.read_bytes()).hexdigest(),
              "identities": [identity, *children], "kind": _kind, "approval": _approval,
              "started_utc": _utc_now(), "verified_stopped": False, "return_code": None}
    _write_process_records(journal, record)
    ready_file.touch()  # The child cannot import or execute pytest before this.
    try:
        return_code = process.wait(timeout=timeout)
    except BaseException:
        recover_owned_pytest(config)
        process.wait(timeout=config.shutdown_timeout)
        record = json.loads(journal.read_text(encoding="utf-8"))
        record["return_code"] = process.returncode
        _write_process_records(journal, record)
        raise
    else:
        record["return_code"] = return_code
        _write_process_records(journal, record)
        recover_owned_pytest(config)
        return return_code
    finally:
        if drain and process.poll() is not None:
            drain.join(timeout=config.shutdown_timeout)
            process.stdout.close()


def _preparation_approval(arguments, expected_script_sha256):
    if arguments == ["-m", "alembic", "upgrade", "head"]:
        return {"module": "alembic", "arguments": ["upgrade", "head"]}
    if isinstance(arguments, list) and len(arguments) == 2 and arguments[0] == "-c" and isinstance(arguments[1], str):
        actual = hashlib.sha256(arguments[1].encode("utf-8")).hexdigest()
        if expected_script_sha256 and actual == expected_script_sha256:
            return {"script_sha256": actual}
    raise TestDatabaseSafetyError("Preparation requires exact approved Alembic arguments or bootstrap script hash")


def run_owned_preparation(config: E2EConfig, arguments: list[str], *, label: str, environment: dict, timeout: float,
                          expected_script_sha256: str | None = None) -> str:
    approval = _preparation_approval(arguments, expected_script_sha256)
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,39}", label):
        raise TestDatabaseSafetyError("Preparation label must be a safe bounded artifact name")
    if any(secret in json.dumps(arguments) for secret in config.secrets()):
        raise TestDatabaseSafetyError("Preparation commands cannot contain credential values")
    owned = replace(config, artifacts_dir=config.artifacts_dir / "preparation" / label)
    if any(path.exists() for path in _phase_paths(owned)):
        raise TestDatabaseSafetyError("Preparation execution artifacts already exist; previous proof and output are preserved")
    owned.artifacts_dir.mkdir(parents=True, exist_ok=True)
    path = owned.artifacts_dir / "output.log"
    with path.open("w", encoding="utf-8") as output:
        code = run_owned_pytest(owned, arguments, output=output, environment=environment, timeout=timeout,
                                _kind="preparation", _approval=approval, _capture_output=True)
    captured = path.read_text(encoding="utf-8")
    if code:
        raise TestDatabaseSafetyError(f"Owned preparation failed ({code}): {captured[-6000:]}")
    return captured


def settle_owned_preparations(config: E2EConfig) -> list[dict]:
    root = config.artifacts_dir / "preparation"
    settled = []
    directories = {path.parent for pattern in ("*/pytest-arguments.json", "*/owned-pytest-process.json", "*/pytest-start.signal") for path in root.glob(pattern)}
    for directory in sorted(directories):
        owned = replace(config, artifacts_dir=directory)
        journal, record = _validate_phase_record(owned)
        if record.get("kind") != "preparation":
            raise TestDatabaseSafetyError("Preparation directory contains unsupported ownership proof")
        settled.append(recover_owned_pytest(owned))
    return settled


def sanitize(value, config: E2EConfig):
    sensitive = {"authorization", "api-key", "x-api-key", config.api_header.lower(), "password", "api_key"}
    if isinstance(value, dict):
        return {key: "[REDACTED]" if str(key).lower() in sensitive else sanitize(item, config) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        if len(value) == 2 and isinstance(value[0], str) and value[0].lower() in sensitive:
            return [value[0], "[REDACTED]"]
        return [sanitize(item, config) for item in value]
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        for secret in config.secrets():
            value = value.replace(secret, "[REDACTED]")
    return value


def assert_non_analysis_path(path: str):
    parsed = urlsplit(path)
    if parsed.scheme or parsed.netloc:
        raise ValueError("Requests must use a local relative API path")
    decoded = parsed.path
    for _ in range(3):
        decoded = unquote(decoded)
    if decoded.rstrip("/").lower() in {"/api/v1/suggestions/analyze", "/api/v1/suggestions/generate"}:
        raise ValueError("Analysis and generation calls are excluded from this suite")
    if not decoded.startswith("/"):
        raise ValueError("HTTP path must start with /")


class AppProcess:
    def __init__(self, config: E2EConfig, artifacts_dir: Path | None = None, *, app: str = "src.main:app", overrides: dict[str, str] | None = None, factory: bool = False, port: int | None = None, qdrant_proxy_proof=None):
        self.config = config
        self.artifacts_dir = Path(artifacts_dir or config.artifacts_dir).resolve()
        self.app, self.factory = app, factory
        self.overrides = dict(overrides or {})
        self.qdrant_proxy_proof = qdrant_proxy_proof
        self._validate_overrides()
        self.port = port or free_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.process: subprocess.Popen | None = None
        self._client: httpx.Client | None = None
        self._drain: threading.Thread | None = None
        self._generation = 0
        self.events: list[dict] = []
        self.unsettled_request = False
        self._evidence_lock = threading.Lock()

    def _validate_overrides(self):
        config = self.config
        guarded = config.database.application_environment()
        # Proxy host/port may differ in an explicit fault profile. Database identity,
        # credentials, collection and alias cannot be redirected through overrides.
        protected = set(guarded) - {"QDRANT_HOST", "QDRANT_PORT", "QDRANT_GRPC_PORT", "ENVIRONMENT"}
        if any(key in protected and str(value) != guarded[key] for key, value in self.overrides.items()):
            raise TestDatabaseSafetyError("App overrides cannot change the guarded test database identity")
        proxy_host = str(self.overrides.get("QDRANT_HOST", config.database.q_host))
        try:
            is_local = proxy_host.lower().rstrip(".") == "localhost" or ipaddress.ip_address(proxy_host).is_loopback
        except ValueError:
            is_local = False
        if not is_local:
            raise TestDatabaseSafetyError("Qdrant fault proxies must be owned loopback endpoints")
        blocked = {7432, 7333, 7334}
        development = dotenv_values(config.repo_root / ".env")
        for key in ("POSTGRES_PORT", "QDRANT_PORT", "QDRANT_GRPC_PORT"):
            for value in (development.get(key), os.environ.get(key)):
                if value:
                    try:
                        blocked.add(int(value))
                    except (TypeError, ValueError):
                        raise TestDatabaseSafetyError("Development service port configuration is invalid") from None
        ports = {}
        for key in ("QDRANT_PORT", "QDRANT_GRPC_PORT"):
            try:
                value = int(self.overrides.get(key, guarded[key]))
            except (TypeError, ValueError):
                raise TestDatabaseSafetyError("Qdrant fault ports must be valid integers") from None
            if not 1 <= value <= 65535:
                raise TestDatabaseSafetyError("Qdrant fault ports must be in the TCP port range")
            # Child application exports repeat the immutable verified TEST
            # listeners. Screen only a changed listener as a fault proxy.
            if value != int(guarded[key]) and value in blocked:
                raise TestDatabaseSafetyError("Qdrant proxy overrides cannot select development service ports")
            ports[key] = value
        if ports["QDRANT_GRPC_PORT"] != config.database.q_grpc_port:
            raise TestDatabaseSafetyError("HTTP fault proxy proof cannot redirect the Qdrant gRPC listener")
        if proxy_host != config.database.q_host or ports["QDRANT_PORT"] != config.database.q_port:
            from tests.e2e.non_analysis.proxy import _ProxyOwnershipProof
            if type(self.qdrant_proxy_proof) is not _ProxyOwnershipProof:
                raise TestDatabaseSafetyError("Changed Qdrant endpoints require live run-owned proxy proof")
            try:
                self.qdrant_proxy_proof.validate_owned_endpoint(run_id=config.run_id, host=proxy_host,
                    port=ports["QDRANT_PORT"], expected_upstream=config.database.qdrant_url)
            except (AttributeError, TypeError, ValueError, RuntimeError, OSError):
                raise TestDatabaseSafetyError("Qdrant endpoint proof does not establish a live run-owned test route") from None

    @property
    def running(self):
        return self.process is not None and self.process.poll() is None

    def _event(self, name, **extra):
        event = {"event": name, "monotonic": time.monotonic(), "utc": _utc_now(), "generation": self._generation, **extra}
        self.events.append(event)
        with (self.artifacts_dir / "process-events.ndjson").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(sanitize(event, self.config), ensure_ascii=False) + "\n")

    def start(self):
        if self.running:
            raise RuntimeError("Owned application process is already running")
        self._validate_overrides()  # Fault profiles mutate overrides between restarts.
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        identity_path = self.artifacts_dir / "owned-processes.json"
        prior = json.loads(identity_path.read_text(encoding="utf-8")) if identity_path.exists() else []
        if prior:
            recover_and_stop(self.config, self.artifacts_dir)
        self._generation = max([self._generation, *(record["generation"] for record in prior)]) + 1
        self.started_utc = _utc_now()
        self.stop_file = self.artifacts_dir / f"stop-{self._generation}.signal"
        self.stop_file.unlink(missing_ok=True)
        self.log_path = self.artifacts_dir / f"application-{self._generation}.log"
        command = [self.config.python_executable, "-m", "tests.e2e.non_analysis.harness", "--serve", self.app, "--port", str(self.port), "--stop-file", str(self.stop_file)]
        if self.factory:
            command.append("--factory")
        environment = {**os.environ, **self.config.application_environment(), **{key: str(value) for key, value in self.overrides.items()}}
        self.process = subprocess.Popen(command, cwd=self.config.repo_root, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        def drain():
            with self.log_path.open("a", encoding="utf-8") as stream:
                for line in self.process.stdout:
                    stream.write(sanitize(line, self.config))
                    stream.flush()
        self._drain = threading.Thread(target=drain, name=f"e2e-log-{self._generation}", daemon=True)
        self._drain.start()
        self._client = httpx.Client(base_url=self.base_url, timeout=self.config.request_timeout, trust_env=False)
        self.command = command
        self._event("spawn", pid=self.process.pid, app=self.app, base_url=self.base_url, started_utc=self.started_utc, workers=1, reload=False, lifespan="on")
        deadline = time.monotonic() + self.config.startup_timeout
        try:
            self._persist_process_identity()
            while time.monotonic() < deadline:
                if not self.running:
                    raise RuntimeError(f"Application exited during startup; inspect {self.log_path}")
                try:
                    response = self._client.get("/health", timeout=1)
                    if response.status_code == 200:
                        metadata = self._client.get("/", timeout=1).json()
                        expected_mock = self.app == "src.presentation.mock_server:app" or environment.get("IS_MOCK", "false").lower() == "true"
                        if metadata.get("mockMode") is not expected_mock:
                            raise AssertionError("Application mode differs from requested evidence profile")
                        self._persist_process_identity()  # Include the Windows venv host child before requests.
                        self._event("ready", mock_mode=expected_mock)
                        return self
                except (httpx.TransportError, json.JSONDecodeError):
                    pass
                time.sleep(0.05)
            raise TimeoutError(f"Application startup exceeded deadline; inspect {self.log_path}")
        except BaseException:
            self.stop()
            raise

    def _persist_process_identity(self):
        identity = _query_process_identity(self.process.pid)
        if identity is None or not identity["command_line"].endswith(subprocess.list2cmdline(self.command[1:])):
            raise TestDatabaseSafetyError("Spawned app process identity cannot be proven")
        identities = [identity, *_query_owned_children(identity, self.command)]
        path = self.artifacts_dir / "owned-processes.json"
        records = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        record = {"run_id": self.config.run_id, "target": self.config.redacted(), "generation": self._generation, "base_url": self.base_url, "started_utc": self.started_utc, "command": self.command, "stop_file": str(self.stop_file.resolve()), "identities": identities, "verified_stopped": False}
        records = [item for item in records if item["generation"] != self._generation] + [record]
        _write_process_records(path, records)

    def _kill_owned_group(self):
        path = self.artifacts_dir / "owned-processes.json"
        if not path.exists():
            # The Popen handle is owned directly; no persisted recovery is trusted.
            self.process.kill()
            return
        if self.running:
            self._persist_process_identity()
        records = json.loads(path.read_text(encoding="utf-8"))
        record = next(item for item in records if item["generation"] == self._generation)
        for identity in reversed(record["identities"]):
            _terminate_verified_process(identity, self.config.shutdown_timeout)

    def request(self, method: str, path: str, *, auth: bool = True, headers: dict | list | httpx.Headers | None = None, request_id: bool | str = True, raw_headers: bool = False, follow_redirects: bool = False, **kwargs) -> httpx.Response:
        assert_non_analysis_path(path)
        if not self.running or self._client is None:
            raise RuntimeError("Owned application process is not running")
        supplied = []
        if request_id:
            supplied.append(("X-Request-Id", str(uuid.uuid4()) if request_id is True else str(request_id)))
        if auth:
            supplied.append((self.config.api_header, self.config.api_key))
        if isinstance(headers, httpx.Headers):
            custom = headers.multi_items()
        elif isinstance(headers, dict):
            custom = list(headers.items())
        else:
            custom = list(headers or [])
        custom_names = {str(key).lower() for key, _ in custom}
        supplied = [(key, value) for key, value in supplied if key.lower() not in custom_names] + custom
        started = time.monotonic()
        request_event = {"method": method.upper(), "path": path, "headers": supplied, "json": kwargs.get("json"), "content": kwargs.get("content"), "raw_headers": raw_headers}
        try:
            if raw_headers:
                if follow_redirects:
                    raise ValueError("Raw-header characterization never follows redirects")
                response = self._raw_request(method, path, supplied, kwargs)
            else:
                response = self._client.request(method, path, headers=supplied, follow_redirects=follow_redirects, **kwargs)
            request_event.update({"status": response.status_code, "response_headers": dict(response.headers), "response": response.text, "duration_seconds": time.monotonic() - started})
            return response
        except BaseException as exc:
            if isinstance(exc, (httpx.TransportError, OSError, TimeoutError)):
                self.unsettled_request = True
            request_event.update({"transport_error": type(exc).__name__, "duration_seconds": time.monotonic() - started})
            raise
        finally:
            with self._evidence_lock:
                with (self.artifacts_dir / "http.ndjson").open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(sanitize(request_event, self.config), ensure_ascii=False, default=str) + "\n")

    def _raw_request(self, method, path, headers, kwargs):
        """Wire legal field whitespace that ordinary httpx refuses before sending."""
        if not re.fullmatch(r"[A-Z]+", method.upper()) or any(char in path for char in "\r\n\x00 "):
            raise ValueError("Raw requests require a bounded ordinary HTTP method/path")
        if set(kwargs) - {"json", "content", "timeout"}:
            raise ValueError("Raw-header mode supports json, content, and timeout only")
        headers = [(str(key), str(value)) for key, value in headers]
        for key, value in headers:
            if not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", key) or len(key) > 256 or len(value) > 8192 or any(char in value for char in "\r\n\x00"):
                raise ValueError("Raw headers cannot contain request injection or unbounded fields")
        if "json" in kwargs:
            if "content" in kwargs:
                raise ValueError("Specify json or content, not both")
            body = json.dumps(kwargs["json"], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            if not any(key.lower() == "content-type" for key, value in headers):
                headers.append(("Content-Type", "application/json"))
        else:
            body = kwargs.get("content", b"")
            if isinstance(body, str):
                body = body.encode("utf-8")
            if not isinstance(body, bytes):
                raise ValueError("Raw request content must be text or bytes")
        if any(key.lower() in {"host", "content-length", "transfer-encoding", "connection"} for key, value in headers):
            raise ValueError("Raw mode owns framing headers to prevent request smuggling")
        headers += [("Host", f"127.0.0.1:{self.port}"), ("Content-Length", str(len(body))), ("Connection", "close")]
        wire = f"{method.upper()} {path} HTTP/1.1\r\n".encode("ascii")
        wire += b"".join(key.encode("ascii") + b": " + value.encode("utf-8") + b"\r\n" for key, value in headers) + b"\r\n" + body
        timeout = kwargs.get("timeout", self.config.request_timeout)
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError("Raw requests need a positive numeric timeout")
        with socket.create_connection(("127.0.0.1", self.port), timeout=timeout) as connection:
            connection.sendall(wire)
            response = http.client.HTTPResponse(connection)
            response.begin()
            content = response.read()
            result = httpx.Response(response.status, headers=response.getheaders(), content=content, request=httpx.Request(method, self.base_url + path))
            response.close()
            return result

    def stop(self, *, kill: bool = False):
        if self.process is None:
            return
        process = self.process
        if self.running:
            if kill:
                self._kill_owned_group()
                self._event("kill", pid=process.pid)
            else:
                self.stop_file.touch()
                self._event("graceful_shutdown_requested", pid=process.pid)
            try:
                process.wait(timeout=self.config.shutdown_timeout)
            except subprocess.TimeoutExpired:
                self._kill_owned_group()
                process.wait(timeout=5)
                self._event("shutdown_deadline_expired", pid=process.pid)
        if (self.artifacts_dir / "owned-processes.json").exists():
            recover_and_stop(self.config, self.artifacts_dir)
        if self._drain:
            self._drain.join(timeout=5)
        if self._client:
            self._client.close()
            self._client = None
        if process.stdout:
            process.stdout.close()
        self._event("exit", pid=process.pid, exit_code=process.returncode)

    def restart(self):
        self.stop()
        return self.start()

    def kill(self):
        self.stop(kill=True)

    def __enter__(self):
        return self.start()

    def __exit__(self, exc_type, exc, traceback):
        self.stop()


class LiveHarness:
    def __init__(self, config: E2EConfig, *, app: str = "src.main:app", overrides: dict | None = None, factory: bool = False):
        self.config = config
        self.infrastructure = ManagedTestInfrastructure(config)
        self.registry = FixtureRegistry(config)
        self.oracle = RawStoreOracle(config, verify_ownership=self.infrastructure.verify)
        self.process = AppProcess(config, app=app, overrides=overrides, factory=factory)
        self.app = self.process
        self.fault_controller = None
        self._baseline: dict | None = None
        self._cleanup_generation = 0
        self._point_templates: dict[str, list] = {}

    @property
    def registered_ids(self) -> set[str]:
        return set(self.registry.ids)

    @property
    def base_url(self):
        return self.process.base_url

    def _journal(self, *, cleanup_verified: bool = False):
        self.config.artifacts_dir.mkdir(parents=True, exist_ok=True)
        destination = self.config.artifacts_dir / "fixture-registry.json"
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(json.dumps({"run_id": self.config.run_id, "ids": sorted(self.registry.ids), "claims": {key: self.registry.claims[key] for key in sorted(self.registry.ids)}, "config": self.config.redacted(), "cleanup_verified": cleanup_verified}, indent=2), encoding="utf-8")
        temporary.replace(destination)

    def register_id(self, parent_id: str):
        if parent_id in self.registry.ids:
            return parent_id
        current = self.oracle.snapshot(parent_id)
        if current["sql"] is not None or current["points"]:
            raise TestDatabaseSafetyError("Cannot claim existing source, sentinel, or unrelated data as a fixture")
        value = self.registry.claim_absent(parent_id)
        self._journal()
        return value

    def new_id(self, label: str = "fixture"):
        value = self.registry.new_id(label)
        self._journal()
        return value

    def restore_registry(self):
        """Recover only the exact durable journal for this same run and target."""
        path = self.config.artifacts_dir / "fixture-registry.json"
        if not path.exists():
            return set()
        journal = json.loads(path.read_text(encoding="utf-8"))
        baseline_path = self.config.artifacts_dir / "sentinel-baseline.json"
        sentinel_ids = json.loads(baseline_path.read_text(encoding="utf-8")).get("sql", {}) if baseline_path.exists() else ()
        recovered = FixtureRegistry.from_journal(self.config, journal, sentinel_ids=sentinel_ids)
        self.registry.ids.update(recovered.ids)
        self.registry.claims.update(recovered.claims)
        return set(recovered.ids)

    def observe(self, name: str, data):
        self.config.artifacts_dir.mkdir(parents=True, exist_ok=True)
        record = {"name": name, "data": sanitize(data, self.config), "monotonic": time.monotonic()}
        with (self.config.artifacts_dir / "observations.ndjson").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        return record

    def request(self, method, path, **kwargs):
        if method.upper() not in {"GET", "HEAD", "OPTIONS"} and self._baseline is not None:
            # Historical background parents never become mutation fixtures.
            path_id = unquote(urlsplit(path).path).rstrip("/").rsplit("/", 1)[-1]
            body = kwargs.get("json")
            candidate_ids = [path_id]
            if isinstance(body, dict):
                candidate_ids += [body.get("id"), body.get("suggestionId")]
                if isinstance(body.get("suggestionIds"), list):
                    candidate_ids += body["suggestionIds"]
            if any(isinstance(value, str) and value.strip() in self._baseline["sql"] for value in candidate_ids):
                raise TestDatabaseSafetyError("HTTP mutations cannot target historical/source sentinels")
        if method.upper() == "DELETE":
            parent_id = unquote(urlsplit(path).path).rstrip("/").rsplit("/", 1)[-1]
            if parent_id in self.registry.ids:
                self.snapshot(parent_id)  # Retain a complete pre-delete orphan template.
        return self.process.request(method, path, **kwargs)

    def snapshot(self, parent_id):
        result = self.oracle.snapshot(parent_id)
        self.observe("raw_parent_snapshot", {"parent_id": parent_id, "snapshot": result})
        if result["points"] and parent_id in self.registry.ids:
            self._point_templates[parent_id] = result["points"]
        return result

    def all_snapshot(self):
        return self.oracle.all_snapshot()

    def assert_consistent(self, parent_id, *, require_exists=True, **expected):
        assert_consistent(self.snapshot(parent_id), self.config, parent_id=parent_id, require_exists=require_exists, **expected)

    def assert_sentinels_unchanged(self, observed: dict | None = None):
        if self._baseline is None:
            raise RuntimeError("Sentinel baseline was not captured")
        current = self.oracle.exclude(observed if observed is not None else self.oracle.all_snapshot(), self.registry.ids)
        assert_unchanged(self._baseline, current)

    def append_cloned_points(self, parent_id, lifecycle_states):
        return self.oracle.append_cloned_points(parent_id, lifecycle_states, self.registry, templates=self._point_templates.get(parent_id))

    def clear_parent_points(self, parent_id):
        self.snapshot(parent_id)
        return self.oracle.clear_parent_points(parent_id, self.registry)

    def remove_sql_row(self, parent_id):
        self.snapshot(parent_id)
        return self.oracle.remove_sql_row(parent_id, self.registry)

    def restart(self):
        return self.process.restart()

    def restart_app(self):
        return self.restart()

    def settle_requests(self):
        """A lost TCP response cannot prove the server stopped mutating stores."""
        if self.process.unsettled_request:
            self.process.stop()
            self.process.unsettled_request = False
            self.process.start()

    def cleanup(self, *, observed: dict | None = None):
        # Administrative cleanup is exact even when ordinary DELETE short-circuits.
        if observed is not None:
            before = {"sql": {key: value for key, value in observed["sql"].items() if key in self.registry.ids}, "points": [point for point in observed["points"] if (point.get("payload") or {}).get("parent_id") in self.registry.ids]}
        else:
            before = self.oracle.snapshots(sorted(self.registry.ids))
        self._cleanup_generation += 1
        (self.config.artifacts_dir / f"before-cleanup-{self._cleanup_generation}.json").write_text(canonical(before), encoding="utf-8")
        result = self.oracle.cleanup(self.registry)
        self.assert_sentinels_unchanged()
        (self.config.artifacts_dir / f"cleanup-{self._cleanup_generation}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        (self.config.artifacts_dir / "cleanup.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        self.registry.ids.clear()
        self.registry.claims.clear()
        self._point_templates.clear()
        self._journal(cleanup_verified=True)
        return result

    def __enter__(self):
        self.infrastructure.verify()
        self.restore_registry()
        current = self.oracle.exclude(self.oracle.all_snapshot(), self.registry.ids)
        baseline_path = self.config.artifacts_dir / "sentinel-baseline.json"
        if baseline_path.exists():
            self._baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
            assert_unchanged(self._baseline, current)
        else:
            self._baseline = current
            self.config.artifacts_dir.mkdir(parents=True, exist_ok=True)
            baseline_path.write_text(canonical(current), encoding="utf-8")
        self._journal()
        self.process.start()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.process.stop()
        self.cleanup()


async def _serve(app: str, port: int, stop_file: Path, factory: bool):
    import uvicorn
    config = uvicorn.Config(app, host="127.0.0.1", port=port, workers=1, reload=False, lifespan="on", factory=factory, log_level="info")
    server = uvicorn.Server(config)
    async def watch():
        while not server.should_exit:
            if stop_file.exists():
                server.should_exit = True
                return
            await asyncio.sleep(0.05)
    watcher = asyncio.create_task(watch())
    try:
        await server.serve()
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)


def _run_pytest(arguments_file: Path, ready_file: Path, startup_timeout: float):
    deadline = time.monotonic() + startup_timeout
    while not ready_file.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError("Pytest ownership acknowledgement did not arrive before startup deadline")
        time.sleep(0.05)
    arguments = json.loads(arguments_file.read_text(encoding="utf-8"))
    if not isinstance(arguments, list) or not all(isinstance(item, str) for item in arguments):
        raise ValueError("Owned pytest arguments must be a string list")
    record = json.loads((arguments_file.parent / "owned-pytest-process.json").read_text(encoding="utf-8"))
    if hashlib.sha256(arguments_file.read_bytes()).hexdigest() != record.get("arguments_sha256"):
        raise TestDatabaseSafetyError("Acknowledged Python arguments changed before execution")
    if record.get("kind", "pytest") == "preparation":
        if _preparation_approval(arguments, (record.get("approval") or {}).get("script_sha256")) != record.get("approval"):
            raise TestDatabaseSafetyError("Preparation approval does not match acknowledged arguments")
        if arguments[0] == "-m":
            sys.argv = [arguments[1], *arguments[2:]]
            runpy.run_module(arguments[1], run_name="__main__")
        else:
            sys.argv = ["-c"]
            exec(compile(arguments[1], "<owned preparation>", "exec"), {"__name__": "__main__"})
        return
    if record.get("kind", "pytest") != "pytest":
        raise TestDatabaseSafetyError("Acknowledged Python execution kind is unsupported")
    sys.argv = ["pytest", *arguments]
    runpy.run_module("pytest", run_name="__main__")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--serve")
    mode.add_argument("--pytest-args-file", type=Path)
    parser.add_argument("--phase-ready-file", type=Path)
    parser.add_argument("--phase-startup-timeout", type=float, default=120.0)
    parser.add_argument("--port", type=int)
    parser.add_argument("--stop-file", type=Path)
    parser.add_argument("--factory", action="store_true")
    args = parser.parse_args()
    if args.pytest_args_file:
        if args.phase_ready_file is None or args.phase_startup_timeout <= 0:
            parser.error("Owned pytest requires a ready file and positive startup timeout")
        _run_pytest(args.pytest_args_file, args.phase_ready_file, args.phase_startup_timeout)
    else:
        if args.port is None or args.stop_file is None:
            parser.error("Owned app requires its port and stop file")
        asyncio.run(_serve(args.serve, args.port, args.stop_file, args.factory))
