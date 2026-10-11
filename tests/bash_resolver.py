"""Resolves the bash the tests may spawn.

On Windows a bare `bash` can be the WSL launcher (System32 or WindowsApps), and running it
starts WSL, so it is never used there.
"""

import os
import re
import sys
from typing import Callable, Mapping, Optional, Tuple

GIT_BASH_PATHS = (
    "C:\\Program Files\\Git\\bin\\bash.exe",
    "C:\\Program Files\\Git\\usr\\bin\\bash.exe",
)


def is_safe_windows_bash(path: str) -> bool:
    norm = path.replace("/", "\\").lower()
    if not re.match(r"^[a-z]:\\", norm):
        return False
    if re.match(r"^[a-z]:\\windows\\(system32|sysnative|syswow64)\\", norm):
        return False
    return "windowsapps" not in norm.split("\\")


def resolve_bash(
    platform: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
    exists: Callable[[str], bool] = os.path.exists,
) -> Tuple[Optional[str], str]:
    """Return (bash, skip_reason); exactly one of them is non-empty."""
    platform = sys.platform if platform is None else platform
    env = os.environ if env is None else env
    if platform != "win32":
        return "bash", ""
    configured = env.get("DOCK_TEST_BASH")
    if configured:
        if not is_safe_windows_bash(configured):
            return None, (
                f"DOCK_TEST_BASH={configured} is not an absolute path "
                "outside System32 and WindowsApps"
            )
        if not exists(configured):
            return None, f"DOCK_TEST_BASH={configured} does not exist"
        return configured, ""
    for path in GIT_BASH_PATHS:
        if exists(path):
            return path, ""
    return None, "no Git Bash found; set DOCK_TEST_BASH (never the WSL bash)"
