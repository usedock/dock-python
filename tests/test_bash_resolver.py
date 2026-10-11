from typing import Dict, List

import pytest

from bash_resolver import resolve_bash

GIT = "C:\\Program Files\\Git\\bin\\bash.exe"
GIT_USR = "C:\\Program Files\\Git\\usr\\bin\\bash.exe"


def win(env: Dict[str, str], present: List[str]):  # type: ignore[no-untyped-def]
    return resolve_bash("win32", env, lambda p: p in present)


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_uses_bash_from_path_off_windows(platform: str) -> None:
    assert resolve_bash(platform, {}, lambda p: False) == ("bash", "")


def test_prefers_git_bash_bin_then_usr_bin() -> None:
    assert win({}, [GIT, GIT_USR])[0] == GIT
    assert win({}, [GIT_USR])[0] == GIT_USR


def test_skips_with_reason_when_nothing_found() -> None:
    bash, reason = win({}, [])
    assert bash is None
    assert "DOCK_TEST_BASH" in reason


def test_accepts_safe_override() -> None:
    p = "D:\\tools\\git\\bin\\bash.exe"
    assert win({"DOCK_TEST_BASH": p}, [p])[0] == p


@pytest.mark.parametrize(
    "p",
    [
        "C:\\Windows\\System32\\bash.exe",
        "c:/windows/system32/bash.exe",
        "C:\\WINDOWS\\SYSTEM32\\bash.exe",
        "C:\\Users\\me\\AppData\\Local\\Microsoft\\WindowsApps\\bash.exe",
        "D:\\x\\windowsapps\\bash.exe",
        "bash",
        "bash.exe",
        "..\\bash.exe",
    ],
)
def test_rejects_unsafe_override_without_falling_back(p: str) -> None:
    bash, reason = win({"DOCK_TEST_BASH": p}, [p, GIT])
    assert bash is None
    assert reason


def test_skips_when_override_missing() -> None:
    assert win({"DOCK_TEST_BASH": "D:\\nope\\bash.exe"}, [GIT])[0] is None
