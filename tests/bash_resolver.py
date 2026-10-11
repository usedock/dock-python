"""Resolves the bash the tests may spawn.

On Windows a bare `bash` can be the WSL launcher (System32 or WindowsApps), and running it
starts WSL, so it is never used there.
"""

import ntpath
import os
import re
import shutil
import sys
from typing import Callable, Dict, Mapping, NamedTuple, Optional

GIT_BASH_PATHS = (
    "C:\\Program Files\\Git\\bin\\bash.exe",
    "C:\\Program Files\\Git\\usr\\bin\\bash.exe",
)
SCOOP_SUFFIXES = (
    "\\scoop\\apps\\git\\current\\usr\\bin\\bash.exe",
    "\\scoop\\apps\\git\\current\\bin\\bash.exe",
)


class Resolution(NamedTuple):
    bash: Optional[str]
    env: Dict[str, str]
    reason: str  # why bash is unavailable; empty when bash is set


def is_safe_windows_bash(path: str) -> bool:
    norm = path.replace("/", "\\").lower()
    if not re.match(r"^[a-z]:\\", norm):
        return False
    segs = norm.split("\\")[1:]
    # Windows drops `.`/`..`, empty and trailing-dot segments and expands 8.3 names (WINDOW~1),
    # so only plain segments are accepted or the System32/WindowsApps check could be bypassed.
    # A `:` after the drive letter is an NTFS stream suffix (System32::$INDEX_ALLOCATION).
    if any(s == "" or s.endswith((".", " ")) or "~" in s or ":" in s for s in segs):
        return False
    if re.search(r"\\windows\\(system32|sysnative|syswow64)\\", norm):
        return False
    return "windowsapps" not in segs


def resolve_bash(
    platform: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
    exists: Callable[[str], bool] = os.path.exists,
    which: Callable[[str], Optional[str]] = shutil.which,
) -> Resolution:
    platform = sys.platform if platform is None else platform
    env = dict(os.environ if env is None else env)
    if platform != "win32":
        found = which("bash")
        return Resolution(found, env, "" if found else "bash not found on PATH")
    configured = env.get("DOCK_TEST_BASH")
    bash: Optional[str] = None
    if configured:
        if not is_safe_windows_bash(configured):
            return Resolution(
                None,
                env,
                f"DOCK_TEST_BASH={configured} is not an absolute path "
                "outside System32, SysWOW64, Sysnative and WindowsApps",
            )
        if not exists(configured):
            return Resolution(None, env, f"DOCK_TEST_BASH={configured} does not exist")
        bash = configured
    else:
        profile = env.get("USERPROFILE")
        candidates = list(GIT_BASH_PATHS) + (
            [profile + s for s in SCOOP_SUFFIXES] if profile else []
        )
        bash = next((p for p in candidates if exists(p)), None)
        if bash is None:
            return Resolution(
                None, env, "no Git Bash found; set DOCK_TEST_BASH (never the WSL bash)"
            )
    # Git's usr\bin first so find and base64 are the GNU tools, not System32\find.exe.
    bash_dir = ntpath.dirname(bash)
    usr_bin = ntpath.normpath(ntpath.join(bash_dir, "..", "usr", "bin"))
    key = next((k for k in env if k.upper() == "PATH"), "PATH")
    parts = list(dict.fromkeys([usr_bin, bash_dir])) + ([env[key]] if env.get(key) else [])
    env[key] = ";".join(parts)
    return Resolution(bash, env, "")
