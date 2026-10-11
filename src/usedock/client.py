from __future__ import annotations

import base64
import os
from types import TracebackType
from typing import Any, Dict, List, Mapping, Optional, Sequence, Type, Union
from urllib.parse import quote

import httpx

from .errors import DockError, error_for
from .models import (
    Connector,
    ConnectorState,
    DockInfo,
    DockState,
    Environment,
    ExecResult,
    Image,
    Operation,
    Port,
)

DEFAULT_BASE_URL = "https://api.usedock.io"

# One exec command is capped at 64 KB; base64 inflates content by 4/3, so a
# write can never exceed 48 KB. The real limit is the whole command (content
# plus the quoted path, twice, plus the template); ``Files.write`` raises
# ``DockError("file_too_large")`` before sending when it is over.
#
# Statuses on file-helper errors match dock-js and dock-go: ``file_command_failed``
# and ``output_truncated`` carry 200 (the HTTP exec succeeded), ``file_too_large``
# carries 0 (it is raised client-side, nothing was sent).
MAX_WRITE_BYTES = 48 * 1024
MAX_COMMAND_BYTES = 64 * 1024


def shell_quote(value: str) -> str:
    """Quote ``value`` as one POSIX shell word: single quotes, each ' written as '\\''."""
    return "'" + value.replace("'", "'\\''") + "'"


class _Unset:
    def __repr__(self) -> str:
        return "UNSET"

    def __bool__(self) -> bool:
        return False

    def __reduce__(self) -> str:
        # copy, deepcopy and pickle return the module-level singleton, so
        # ``is UNSET`` checks still hold on copied keyword arguments.
        return "UNSET"


UNSET: Any = _Unset()
"""Default for arguments where ``None`` is meaningful: omit the field. Pass ``None`` to send
JSON ``null`` (``update(ttl_seconds=None)`` turns auto-stop off)."""


def _body(**fields: Any) -> Dict[str, Any]:
    """Drop unset (None or UNSET) fields; absent args are omitted, never sent as null."""
    return {k: v for k, v in fields.items() if v is not None and v is not UNSET}


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
        self.connectors = Connectors(self)
        self.images = Images(self)
        self.environments = Environments(self)

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
        raise error_for(
            str(envelope.get("code") or "unknown_error"),
            response.status_code,
            str(envelope.get("message") or response.reason_phrase),
        )


class Docks:
    def __init__(self, client: Dock) -> None:
        self._c = client
        self.files = Files(self)
        self.ports = Ports(self)

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
        connectors: Optional[Sequence[str]] = None,
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
                connectors=list(connectors) if connectors is not None else None,
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
        ttl_seconds: Optional[int] = UNSET,
    ) -> DockInfo:
        data = self._c._request(
            "PATCH",
            f"/v1/docks/{_seg(dock_id)}",
            body={
                **_body(name=name, cpus=cpus, memoryMiB=memory_mib, diskGiB=disk_gib),
                **({} if ttl_seconds is UNSET else {"ttlSeconds": ttl_seconds}),
            },
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
        idempotency_key: Optional[str] = None,
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
            headers={"idempotency-key": idempotency_key} if idempotency_key else None,
        )
        return ExecResult.from_dict(data)

    def stop(self, dock_id: str, *, force: Optional[bool] = None) -> DockState:
        data = self._c._request("POST", f"/v1/docks/{_seg(dock_id)}/stop", body=_body(force=force))
        return DockState.from_dict(data)

    def resume(
        self,
        dock_id: str,
        *,
        cpus: Optional[int] = None,
        memory_mib: Optional[int] = None,
        disk_gib: Optional[int] = None,
        ttl_seconds: Optional[int] = UNSET,
        environment: Optional[str] = None,
        no_env: Optional[bool] = None,
    ) -> DockState:
        data = self._c._request(
            "POST",
            f"/v1/docks/{_seg(dock_id)}/resume",
            body={
                **_body(
                    cpus=cpus,
                    memoryMiB=memory_mib,
                    diskGiB=disk_gib,
                    environment=environment,
                    noEnv=no_env,
                ),
                **({} if ttl_seconds is UNSET else {"ttlSeconds": ttl_seconds}),
            },
        )
        return DockState.from_dict(data)

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


class Ports:
    """Exposed dock ports. New ports are ``private``; ``public`` opens the URL to anyone."""

    def __init__(self, docks: Docks) -> None:
        self._c = docks._c

    def list(self, dock_id: str) -> List[Port]:
        data = self._c._request("GET", f"/v1/docks/{_seg(dock_id)}/ports")
        return [Port.from_dict(d) for d in data]

    def expose(self, dock_id: str, port: int, *, visibility: Optional[str] = None) -> Port:
        """Expose ``port`` (``visibility`` ``"public"`` or ``"private"``, default private for a
        new port). Exposing it again returns the same URL; passing ``visibility`` then
        changes it, and omitting it keeps the current one."""
        data = self._c._request(
            "POST",
            f"/v1/docks/{_seg(dock_id)}/ports",
            body=_body(port=port, visibility=visibility),
        )
        return Port.from_dict(data)

    def remove(self, dock_id: str, port: int) -> None:
        """Unexpose ``port``; raises ``port_not_found`` (404) when it is not exposed."""
        self._c._request("DELETE", f"/v1/docks/{_seg(dock_id)}/ports/{int(port)}")


class Files:
    """File helpers. The API has no file routes, so each call is one ``exec``."""

    def __init__(self, docks: Docks) -> None:
        self._docks = docks

    def _run(self, dock_id: str, command: str, what: str) -> ExecResult:
        result = self._docks.exec(dock_id, command)
        if result.exit_code != 0:
            detail = result.stderr.strip() or f"exit code {result.exit_code}"
            raise DockError("file_command_failed", 200, f"{what}: {detail}")
        if result.truncated:
            # The API clips stdout/stderr at 1 MiB; a clipped base64 prefix still
            # decodes, so returning it would silently hand back partial content.
            raise DockError(
                "output_truncated", 200, f"{what}: output exceeded the exec output limit"
            )
        return result

    @staticmethod
    def _check_size(command: str, what: str) -> None:
        size = len(command.encode("utf-8"))
        if size > MAX_COMMAND_BYTES:
            raise DockError(
                "file_too_large",
                0,
                f"{what}: the exec command would be {size} bytes; the limit is "
                f"{MAX_COMMAND_BYTES} (the path is too long)",
            )

    def write(self, dock_id: str, path: str, content: Union[str, bytes]) -> str:
        raw = content.encode("utf-8") if isinstance(content, str) else content
        if len(raw) > MAX_WRITE_BYTES:
            # Cheap early check: over 48 KB always exceeds the command limit, so
            # skip base64-encoding (and building a command from) huge input.
            raise DockError(
                "file_too_large",
                0,
                f"write {path}: content is {len(raw)} bytes; the limit is {MAX_WRITE_BYTES} "
                f"bytes (the exec command is capped at {MAX_COMMAND_BYTES} bytes)",
            )
        q = shell_quote(path)
        encoded = base64.b64encode(raw).decode("ascii")
        command = (
            f'd=$(dirname -- {q}; echo x) && mkdir -p -- "${{d%??}}" && '
            f"printf '%s' '{encoded}' | base64 -d > {q}"
        )
        if len(command.encode("utf-8")) > MAX_COMMAND_BYTES:
            raise DockError(
                "file_too_large",
                0,
                f"write {path}: content is {len(raw)} bytes; with this path the exec command "
                f"would exceed {MAX_COMMAND_BYTES} bytes (about 48 KB of content minus the path)",
            )
        self._run(dock_id, command, f"write {path}")
        return path

    def read_bytes(self, dock_id: str, path: str) -> bytes:
        command = f"base64 -w0 -- {shell_quote(path)}"
        self._check_size(command, f"read {path}")
        result = self._run(dock_id, command, f"read {path}")
        return base64.b64decode(result.stdout)

    def read(self, dock_id: str, path: str) -> str:
        raw = self.read_bytes(dock_id, path)
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DockError(
                "file_not_utf8", 0, f"read {path}: not valid UTF-8; use read_bytes"
            ) from exc

    def list(self, dock_id: str, path: str) -> List[str]:
        command = (
            f'p={shell_quote(path)} && case $p in /*) ;; *) p=./$p ;; esac && test -d "$p" && '
            'find -H "$p" -mindepth 1 -maxdepth 1 -exec sh -c '
            '\'for f; do printf "%s" "${f##*/}" | base64 -w0; echo; done\' sh {} +'
        )
        self._check_size(command, f"list {path}")
        result = self._run(dock_id, command, f"list {path}")
        return [
            base64.b64decode(line).decode("utf-8", errors="replace")
            for line in result.stdout.split("\n")
            if line
        ]


class Operations:
    def __init__(self, client: Dock) -> None:
        self._c = client

    def get(self, operation_id: str) -> Operation:
        data = self._c._request("GET", f"/v1/operations/{_seg(operation_id)}")
        return Operation.from_dict(data)


class Connectors:
    """Workspace tool connections. Admins connect and disconnect; members can list.
    Tokens are never returned."""

    def __init__(self, client: Dock) -> None:
        self._c = client

    def list(self, workspace_id: str) -> List[Connector]:
        data = self._c._request("GET", f"/v1/workspaces/{_seg(workspace_id)}/connectors")
        return [Connector.from_dict(d) for d in data]

    def connect(self, workspace_id: str, kind: str, token: str) -> Connector:
        data = self._c._request(
            "PUT",
            f"/v1/workspaces/{_seg(workspace_id)}/connectors/{_seg(kind)}",
            body={"token": token},
        )
        return Connector.from_dict(data)

    def disconnect(self, workspace_id: str, kind: str) -> ConnectorState:
        data = self._c._request(
            "DELETE", f"/v1/workspaces/{_seg(workspace_id)}/connectors/{_seg(kind)}"
        )
        return ConnectorState.from_dict(data)


class Images:
    """The Dockyard image catalog."""

    def __init__(self, client: Dock) -> None:
        self._c = client

    def list(self) -> List[Image]:
        return [Image.from_dict(d) for d in self._c._request("GET", "/v1/images")]


class Environments:
    """Organization environments. ``ref`` is an id or a name; pass ``organization_id``
    when addressing by name."""

    def __init__(self, client: Dock) -> None:
        self._c = client

    def list(self, organization_id: str) -> List[Environment]:
        data = self._c._request(
            "GET", "/v1/environments", params={"organizationId": organization_id}
        )
        return [Environment.from_dict(d) for d in data]

    def get(self, ref: str, *, organization_id: Optional[str] = None) -> Environment:
        data = self._c._request(
            "GET", f"/v1/environments/{_seg(ref)}", params=_org_params(organization_id)
        )
        return Environment.from_dict(data)

    def update(
        self,
        ref: str,
        *,
        organization_id: Optional[str] = None,
        name: Optional[str] = None,
        is_default: Optional[bool] = None,
        secrets_access: Optional[str] = None,
        safe_for_third_parties: Optional[bool] = None,
        pass_github: Optional[bool] = None,
        pass_secrets: Optional[bool] = None,
        pass_dock_credentials: Optional[bool] = None,
        pass_agents_credentials: Optional[bool] = None,
        provider_keys: Optional[str] = None,
        egress_allow: Optional[List[str]] = UNSET,
    ) -> Environment:
        """Update posture. ``provider_keys`` is ``"gateway"`` (default; keys stay in the
        control plane) or ``"plain"`` (the real key is written into the dock; admins only).
        ``egress_allow=None`` clears the allowlist; leave it out to keep it."""
        body = _body(
            name=name,
            isDefault=is_default,
            secretsAccess=secrets_access,
            safeForThirdParties=safe_for_third_parties,
            passGithub=pass_github,
            passSecrets=pass_secrets,
            passDockCredentials=pass_dock_credentials,
            passAgentsCredentials=pass_agents_credentials,
            providerKeys=provider_keys,
        )
        if egress_allow is not UNSET:
            body["egressAllow"] = egress_allow
        data = self._c._request(
            "PATCH",
            f"/v1/environments/{_seg(ref)}",
            body=body,
            params=_org_params(organization_id),
        )
        return Environment.from_dict(data)


def _org_params(organization_id: Optional[str]) -> Optional[Dict[str, str]]:
    return {"organizationId": organization_id} if organization_id else None
