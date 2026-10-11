from typing import Dict, List

import pytest

from bash_resolver import Resolution, resolve_bash

GIT = "C:\\Program Files\\Git\\bin\\bash.exe"
GIT_USR = "C:\\Program Files\\Git\\usr\\bin\\bash.exe"


def win(env: Dict[str, str], present: List[str]) -> Resolution:
    return resolve_bash("win32", env, lambda p: p in present)


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_uses_bash_from_path_off_windows(platform: str) -> None:
    r = resolve_bash(platform, {}, lambda p: False, lambda n: "/usr/bin/" + n)
    assert (r.bash, r.reason) == ("/usr/bin/bash", "")


def test_skips_off_windows_without_bash() -> None:
    r = resolve_bash("linux", {}, lambda p: False, lambda n: None)
    assert r.bash is None
    assert r.reason


def test_never_looks_up_path_on_windows() -> None:
    def no_which(name: str) -> str:
        raise AssertionError("PATH lookup on Windows")

    assert resolve_bash("win32", {}, lambda p: False, no_which).bash is None


def test_prefers_git_bash_bin_then_usr_bin() -> None:
    assert win({}, [GIT, GIT_USR]).bash == GIT
    assert win({}, [GIT_USR]).bash == GIT_USR


def test_skips_with_reason_when_nothing_found() -> None:
    r = win({}, [])
    assert r.bash is None
    assert "DOCK_TEST_BASH" in r.reason


def test_accepts_safe_override() -> None:
    p = "D:\\tools\\git\\bin\\bash.exe"
    assert win({"DOCK_TEST_BASH": p}, [p]).bash == p


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
        "C:\\Windows\\.\\System32\\bash.exe",
        "C:\\Windows\\System32.\\bash.exe",
        "C:\\Windows\\\\System32\\bash.exe",
        "C:\\Windows\\System32\\..\\System32\\bash.exe",
        "C:\\Users\\me\\AppData\\Local\\Microsoft\\WINDOW~1\\bash.exe",
        "C:\\Users\\me\\AppData\\Local\\Microsoft\\WindowsApps \\bash.exe",
    ],
)
def test_rejects_unsafe_override_without_falling_back(p: str) -> None:
    r = win({"DOCK_TEST_BASH": p}, [p, GIT])
    assert r.bash is None
    assert r.reason


def test_skips_when_override_missing() -> None:
    assert win({"DOCK_TEST_BASH": "D:\\nope\\bash.exe"}, [GIT]).bash is None


def test_finds_scoop_git_and_puts_usr_bin_first_on_path() -> None:
    p = "C:\\Users\\me\\scoop\\apps\\git\\current\\bin\\bash.exe"
    r = win({"USERPROFILE": "C:\\Users\\me", "Path": "C:\\x"}, [p])
    assert r.bash == p
    cur = "C:\\Users\\me\\scoop\\apps\\git\\current"
    assert r.env["Path"] == f"{cur}\\usr\\bin;{cur}\\bin;C:\\x"


@pytest.mark.parametrize("p", ["C:\\Windows\\SysWOW64\\bash.exe", "C:/Windows/Sysnative/bash.exe"])
def test_rejects_syswow64_and_sysnative(p: str) -> None:
    assert win({"DOCK_TEST_BASH": p}, [p]).bash is None
