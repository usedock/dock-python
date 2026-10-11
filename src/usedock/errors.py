from __future__ import annotations

from typing import Dict, Type


class DockError(Exception):
    """An error response from the Dock API, or a failure the SDK detected itself.

    ``code`` is the stable machine-readable API code (``dock_not_found``,
    ``validation_error``, ...). ``status`` is the HTTP status, or 0 when the
    error was raised locally (for example a failed file helper).
    """

    def __init__(self, code: str, status: int, message: str) -> None:
        super().__init__(f"{code} ({status}): {message}")
        self.code = code
        self.status = status
        self.message = message


class ConnectorNotConnectedError(DockError):
    """``connector_not_connected`` (409): a requested connector is not connected."""


class ConnectorAdminOnlyError(DockError):
    """``connector_admin_only`` (403): only organization admins can launch or open docks
    that use connectors."""


class ConnectorNotFoundError(DockError):
    """``connector_not_found`` (404): disconnecting a connector that is not connected."""


class ImageUnknownError(DockError):
    """``image_unknown`` (400): the image is not in the Dockyard catalog."""


class ImageUnavailableError(DockError):
    """``image_unavailable`` (400): the image is in the catalog but no host serves it right now."""


_BY_CODE: Dict[str, Type[DockError]] = {
    "connector_not_connected": ConnectorNotConnectedError,
    "connector_admin_only": ConnectorAdminOnlyError,
    "connector_not_found": ConnectorNotFoundError,
    "image_unknown": ImageUnknownError,
    "image_unavailable": ImageUnavailableError,
}


def error_for(code: str, status: int, message: str) -> DockError:
    """The typed subclass for a known API code, else a plain ``DockError``."""
    return _BY_CODE.get(code, DockError)(code, status, message)
