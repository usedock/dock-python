from __future__ import annotations

import base64
import os
from types import TracebackType
from typing import Any, Dict, List, Mapping, Optional, Type, Union
from urllib.parse import quote

import httpx

from .errors import DockError
from .models import DockInfo, ExecResult, Operation

DEFAULT_BASE_URL = "https://api.usedock.io"

# One exec command is capped at 64 KB; base64 inflates content by 4/3.
MAX_WRITE_BYTES = 48 * 1024


def shell_quote(value: str) -> str:
    """Quote ``value`` as one POSIX shell word: single quotes, each ' written as '\\''."""
    return "'" + value.replace("'", "'\\''") + "'"


def _body(**fields: Any) -> Dict[str, Any]:
    """Drop unset (None) fields; absent args are omitted, never sent as null."""
    return {k: v for k, v in fields.items() if v is not None}


def _seg(value: str) -> str:
    return quote(value, safe="")


class Dock:
    """Synchronous client for the Dock API.

    ``api_key`` defaults to ``DOCK_API_KEY`` and ``base_url`` to ``DOCK_API_URL``
    (then ``https://api.usedock.io``).
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        *,
        timeout: float = 120.0,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        key = api_key or os.environ.get("DOCK_API_KEY")
        if not key:
            raise ValueError("api_key is required: pass it or set DOCK_API_KEY")
        url = base_url or os.environ.get("DOCK_API_URL") or DEFAULT_BASE_URL
        self._http = httpx.Client(
            base_url=url.rstrip("/"),
            headers={"Authorization": f"Bearer {key}"},
            timeout=timeout,
            transport=transport,
        )
        self.docks = Docks(self)
        self.operations = Operations(self)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Dock:
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        self.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, str]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        try:
            response = self._http.request(
                method,
                path,
                json=body if body else None,
                params=params,
                headers=headers,
            )
        except httpx.HTTPError as exc:
            raise DockError("network_error", 0, str(exc)) from exc
        try:
            envelope = response.json()
        except ValueError:
            envelope = None
        if not isinstance(envelope, dict):
            raise DockError("invalid_response", response.status_code, "response was not JSON")
        if envelope.get("ok") is True and response.is_success:
            return envelope.get("data")
        raise DockError(
            str(envelope.get("code") or "unknown_error"),
            response.status_code,
            str(envelope.get("message") or response.reason_phrase),
        )


class Docks:
    def __init__(self, client: Dock) -> None:
        self._c = client
        self.files = Files(self)

    def create(
        self,
        *,
        workspace_id: Optional[str] = None,
        name: Optional[str] = None,
        image: Optional[str] = None,
        cpus: Optional[int] = None,
        memory_mib: Optional[int] = None,
        disk_gib: Optional[int] = None,
        ttl_seconds: Optional[int] = None,
        env: Optional[Mapping[str, str]] = None,
        environment: Optional[str] = None,
        no_env: Optional[bool] = None,
        idempotency_key: Optional[str] = None,
    ) -> DockInfo:
        data = self._c._request(
            "POST",
            "/v1/docks",
            body=_body(
                workspaceId=workspace_id,
                name=name,
                image=image,
                cpus=cpus,
                memoryMiB=memory_mib,
                diskGiB=disk_gib,
                ttlSeconds=ttl_seconds,
                env=dict(env) if env is not None else None,
                environment=environment,
                noEnv=no_env,
            ),
            headers={"idempotency-key": idempotency_key} if idempotency_key else None,
        )
        return DockInfo.from_dict(data)

    def list(self, *, filter: Optional[str] = None, all: Optional[bool] = None) -> List[DockInfo]:
        params: Dict[str, str] = {}
        if filter is not None:
            params["filter"] = filter
        if all is not None:
            params["all"] = "true" if all else "false"
        data = self._c._request("GET", "/v1/docks", params=params or None)
        return [DockInfo.from_dict(d) for d in data]

    def get(self, dock_id: str) -> DockInfo:
        return DockInfo.from_dict(self._c._request("GET", f"/v1/docks/{_seg(dock_id)}"))

    def update(
        self,
        dock_id: str,
        *,
        name: Optional[str] = None,
        cpus: Optional[int] = None,
        memory_mib: Optional[int] = None,
        disk_gib: Optional[int] = None,
        ttl_seconds: Optional[int] = None,
    ) -> DockInfo:
        data = self._c._request(
            "PATCH",
            f"/v1/docks/{_seg(dock_id)}",
            body=_body(
                name=name,
                cpus=cpus,
                memoryMiB=memory_mib,
                diskGiB=disk_gib,
                ttlSeconds=ttl_seconds,
            ),
        )
        return DockInfo.from_dict(data)

    def exec(
        self,
        dock_id: str,
        command: str,
        *,
        timeout_seconds: Optional[int] = None,
        env: Optional[Mapping[str, str]] = None,
        cwd: Optional[str] = None,
    ) -> ExecResult:
        data = self._c._request(
            "POST",
            f"/v1/docks/{_seg(dock_id)}/exec",
            body=_body(
                command=command,
                timeoutSeconds=timeout_seconds,
                env=dict(env) if env is not None else None,
                cwd=cwd,
            ),
        )
        return ExecResult.from_dict(data)

    def stop(self, dock_id: str, *, force: Optional[bool] = None) -> DockInfo:
        data = self._c._request("POST", f"/v1/docks/{_seg(dock_id)}/stop", body=_body(force=force))
        return DockInfo.from_dict(data)

    def resume(
        self,
        dock_id: str,
        *,
        cpus: Optional[int] = None,
        memory_mib: Optional[int] = None,
        disk_gib: Optional[int] = None,
        ttl_seconds: Optional[int] = None,
        environment: Optional[str] = None,
        no_env: Optional[bool] = None,
    ) -> DockInfo:
        data = self._c._request(
            "POST",
            f"/v1/docks/{_seg(dock_id)}/resume",
            body=_body(
                cpus=cpus,
                memoryMiB=memory_mib,
                diskGiB=disk_gib,
                ttlSeconds=ttl_seconds,
                environment=environment,
                noEnv=no_env,
            ),
        )
        return DockInfo.from_dict(data)

    def branch(
        self,
        dock_id: str,
        *,
        name: Optional[str] = None,
        image: Optional[str] = None,
        cpus: Optional[int] = None,
        memory_mib: Optional[int] = None,
        disk_gib: Optional[int] = None,
        ttl_seconds: Optional[int] = None,
        env: Optional[Mapping[str, str]] = None,
        environment: Optional[str] = None,
        no_env: Optional[bool] = None,
        idempotency_key: Optional[str] = None,
    ) -> DockInfo:
        data = self._c._request(
            "POST",
            f"/v1/docks/{_seg(dock_id)}/branch",
            body=_body(
                name=name,
                image=image,
                cpus=cpus,
                memoryMiB=memory_mib,
                diskGiB=disk_gib,
                ttlSeconds=ttl_seconds,
                env=dict(env) if env is not None else None,
                environment=environment,
                noEnv=no_env,
            ),
            headers={"idempotency-key": idempotency_key} if idempotency_key else None,
        )
        return DockInfo.from_dict(data)

    def delete(self, dock_id: str) -> Operation:
        data = self._c._request(
            "DELETE",
            f"/v1/docks/{_seg(dock_id)}",
            headers={"x-confirm-delete": dock_id},
        )
        return Operation.from_dict(data["operation"])


class Files:
    """File helpers. The API has no file routes, so each call is one ``exec``."""

    def __init__(self, docks: Docks) -> None:
        self._docks = docks

    def _run(self, dock_id: str, command: str, what: str) -> ExecResult:
        result = self._docks.exec(dock_id, command)
        if result.exit_code != 0:
            detail = result.stderr.strip() or f"exit code {result.exit_code}"
            raise DockError("file_command_failed", 0, f"{what}: {detail}")
        return result

    def write(self, dock_id: str, path: str, content: Union[str, bytes]) -> str:
        raw = content.encode("utf-8") if isinstance(content, str) else content
        if len(raw) > MAX_WRITE_BYTES:
            raise ValueError(
                f"content is {len(raw)} bytes; one write is limited to {MAX_WRITE_BYTES}"
            )
        q = shell_quote(path)
        encoded = base64.b64encode(raw).decode("ascii")
        command = f"mkdir -p -- \"$(dirname -- {q})\" && printf '%s' '{encoded}' | base64 -d > {q}"
        self._run(dock_id, command, f"write {path}")
        return path

    def read(self, dock_id: str, path: str) -> str:
        result = self._run(dock_id, f"base64 -w0 -- {shell_quote(path)}", f"read {path}")
        return base64.b64decode(result.stdout).decode("utf-8")

    def list(self, dock_id: str, path: str) -> List[str]:
        result = self._run(dock_id, f"ls -1A -- {shell_quote(path)}", f"list {path}")
        return [line for line in result.stdout.split("\n") if line]


class Operations:
    def __init__(self, client: Dock) -> None:
        self._c = client

    def get(self, operation_id: str) -> Operation:
        data = self._c._request("GET", f"/v1/operations/{_seg(operation_id)}")
        return Operation.from_dict(data)
