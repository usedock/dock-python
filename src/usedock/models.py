from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


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
