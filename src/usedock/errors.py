from __future__ import annotations


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
