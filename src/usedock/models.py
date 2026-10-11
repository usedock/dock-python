from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


def _opt_int(data: Dict[str, Any], key: str) -> Optional[int]:
    value = data.get(key)
    return value if isinstance(value, int) else None


def _str(data: Dict[str, Any], key: str) -> str:
    """A string field; missing or null (legacy docks have no name) becomes ""."""
    value = data.get(key)
    return value if isinstance(value, str) else ""


def _opt_str(data: Dict[str, Any], key: str) -> Optional[str]:
    value = data.get(key)
    return value if isinstance(value, str) else None


def _str_list(data: Dict[str, Any], key: str) -> List[str]:
    value = data.get(key)
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


@dataclass
class DockInfo:
    """A dock. Only ``id``, ``name`` and ``state`` are guaranteed; the full
    response, including fields this SDK does not know yet, is in ``raw``."""

    id: str
    name: str
    state: str
    workspace_id: Optional[str] = None
    image: Optional[str] = None
    runtime: Optional[str] = None
    cpus: Optional[int] = None
    memory_mib: Optional[int] = None
    disk_gib: Optional[int] = None
    connectors: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DockInfo:
        return cls(
            id=_str(data, "id"),
            name=_str(data, "name"),
            state=_str(data, "state"),
            workspace_id=_opt_str(data, "workspaceId"),
            image=_opt_str(data, "image"),
            runtime=_opt_str(data, "runtime"),
            cpus=_opt_int(data, "cpus"),
            memory_mib=_opt_int(data, "memoryMiB"),
            disk_gib=_opt_int(data, "diskGiB"),
            connectors=_str_list(data, "connectors"),
            raw=data,
        )


@dataclass
class DockState:
    """The ``{id, state}`` answer of ``stop`` and ``resume``; the response is in ``raw``."""

    id: str
    state: str
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DockState:
        return cls(id=_str(data, "id"), state=_str(data, "state"), raw=data)


@dataclass
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str
    truncated: bool = False
    duration_ms: Optional[int] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ExecResult:
        return cls(
            exit_code=_opt_int(data, "exitCode") or 0,
            stdout=_str(data, "stdout"),
            stderr=_str(data, "stderr"),
            truncated=bool(data.get("truncated", False)),
            duration_ms=_opt_int(data, "durationMs"),
            raw=data,
        )


@dataclass
class Operation:
    id: str
    status: str
    target_type: Optional[str] = None
    target_id: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Operation:
        return cls(
            id=_str(data, "id"),
            status=_str(data, "status"),
            target_type=_opt_str(data, "targetType"),
            target_id=_opt_str(data, "targetId"),
            raw=data,
        )


@dataclass
class Connector:
    """A workspace connector. ``status`` is ``connected``, ``not_connected`` or
    ``reauth_required``; ``read_only`` kinds (github, model-keys) cannot be connected by token.
    ``credential_type`` is ``oauth``, ``personal_token``, ``bot_token``, ``org_token``,
    ``user_token``, ``token`` or ``None`` (not connected or not recorded)."""

    kind: str
    type: str
    status: str
    account_label: Optional[str] = None
    scopes: List[str] = field(default_factory=list)
    oauth_available: bool = False
    read_only: bool = False
    updated_at: Optional[str] = None
    credential_type: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Connector:
        return cls(
            kind=_str(data, "kind"),
            type=_str(data, "type"),
            status=_str(data, "status"),
            account_label=_opt_str(data, "accountLabel"),
            scopes=_str_list(data, "scopes"),
            oauth_available=bool(data.get("oauthAvailable", False)),
            read_only=bool(data.get("readOnly", False)),
            updated_at=_opt_str(data, "updatedAt"),
            credential_type=_opt_str(data, "credentialType"),
            raw=data,
        )


@dataclass
class ConnectorState:
    """The ``{kind, status}`` answer of ``connectors.disconnect``."""

    kind: str
    status: str
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ConnectorState:
        return cls(kind=_str(data, "kind"), status=_str(data, "status"), raw=data)


@dataclass
class Image:
    """A Dockyard catalog image; ``available`` is whether a host serves it right now."""

    name: str
    description: str = ""
    arch: List[str] = field(default_factory=list)
    size_mib: Optional[int] = None
    contents: str = ""
    available: bool = False
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Image:
        return cls(
            name=_str(data, "name"),
            description=_str(data, "description"),
            arch=_str_list(data, "arch"),
            size_mib=_opt_int(data, "sizeMiB"),
            contents=_str(data, "contents"),
            available=bool(data.get("available", False)),
            raw=data,
        )


@dataclass
class Port:
    """An exposed dock port. ``visibility`` is ``public`` or ``private``; ``url`` is
    ``None`` while hosted ports are off on the deployment."""

    port: int
    visibility: str
    url: Optional[str] = None
    created_at: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Port:
        return cls(
            port=_opt_int(data, "port") or 0,
            visibility=_str(data, "visibility"),
            url=_opt_str(data, "url"),
            created_at=_opt_str(data, "createdAt"),
            raw=data,
        )


@dataclass
class Environment:
    """An environment. ``provider_keys`` is how the organization's provider keys reach
    docks: ``gateway`` (default) keeps them in the control plane and gives the dock a
    placeholder key plus gateway base URLs; ``plain`` writes the real key into the dock,
    so anyone who can run a command in it can read the key (weaker; admins only).
    ``egress_allow`` is ``None`` when egress is open minus private ranges. Variables are
    listed by name only (``var_names``); values are never returned."""

    id: str
    organization_id: str
    name: str
    provider_keys: str = "gateway"
    is_default: bool = False
    current_version: Optional[int] = None
    secrets_access: Optional[str] = None
    safe_for_third_parties: bool = False
    pass_github: bool = False
    pass_secrets: bool = False
    pass_dock_credentials: bool = False
    pass_agents_credentials: bool = False
    egress_allow: Optional[List[str]] = None
    var_names: List[str] = field(default_factory=list)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Environment:
        egress = data.get("egressAllow")
        return cls(
            id=_str(data, "id"),
            organization_id=_str(data, "organizationId"),
            name=_str(data, "name"),
            provider_keys=_opt_str(data, "providerKeys") or "gateway",
            is_default=bool(data.get("isDefault", False)),
            current_version=_opt_int(data, "currentVersion"),
            secrets_access=_opt_str(data, "secretsAccess"),
            safe_for_third_parties=bool(data.get("safeForThirdParties", False)),
            pass_github=bool(data.get("passGithub", False)),
            pass_secrets=bool(data.get("passSecrets", False)),
            pass_dock_credentials=bool(data.get("passDockCredentials", False)),
            pass_agents_credentials=bool(data.get("passAgentsCredentials", False)),
            egress_allow=_str_list(data, "egressAllow") if isinstance(egress, list) else None,
            var_names=_str_list(data, "varNames"),
            created_at=_opt_str(data, "createdAt"),
            updated_at=_opt_str(data, "updatedAt"),
            raw=data,
        )
