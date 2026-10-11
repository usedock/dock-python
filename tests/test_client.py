import base64
import copy
import json
import os
import pickle
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

import httpx
import pytest

from usedock import MAX_WRITE_BYTES, UNSET, Dock, DockError, DockState
from usedock.client import MAX_COMMAND_BYTES, shell_quote

DOCK = {"id": "d1", "name": "n", "state": "ready", "cpus": 2, "extraUnknown": {"a": 1}}


def make(handler: Callable[[httpx.Request], httpx.Response]) -> Dock:
    return Dock("dock_test", "http://api.test", transport=httpx.MockTransport(handler))


def ok(data: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json={"ok": True, "data": data})


def recorder(response: httpx.Response) -> Tuple[Dock, List[httpx.Request]]:
    seen: List[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return response

    return make(handler), seen


def body_of(req: httpx.Request) -> Dict[str, Any]:
    result: Dict[str, Any] = json.loads(req.content) if req.content else {}
    return result


def test_env_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCK_API_KEY", "dock_env")
    monkeypatch.setenv("DOCK_API_URL", "http://env.test/")
    client = Dock()
    assert str(client._http.base_url).rstrip("/") == "http://env.test"
    assert client._http.headers["authorization"] == "Bearer dock_env"


def test_default_base_url_and_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DOCK_API_URL", raising=False)
    monkeypatch.delenv("DOCK_API_KEY", raising=False)
    with pytest.raises(ValueError):
        Dock()
    assert str(Dock("dock_x")._http.base_url).startswith("https://api.usedock.io")


def test_create_maps_camel_case_and_omits_unset() -> None:
    client, seen = recorder(ok(DOCK, 201))
    dock = client.docks.create(
        workspace_id="w",
        name="n",
        image="ubuntu-24.04",
        cpus=1,
        memory_mib=1024,
        disk_gib=10,
        ttl_seconds=60,
        env={"A": "b"},
        idempotency_key="k",
    )
    req = seen[0]
    assert (req.method, req.url.path) == ("POST", "/v1/docks")
    assert req.headers["authorization"] == "Bearer dock_test"
    assert req.headers["idempotency-key"] == "k"
    assert body_of(req) == {
        "workspaceId": "w",
        "name": "n",
        "image": "ubuntu-24.04",
        "cpus": 1,
        "memoryMiB": 1024,
        "diskGiB": 10,
        "ttlSeconds": 60,
        "env": {"A": "b"},
    }
    assert dock.id == "d1" and dock.state == "ready" and dock.cpus == 2
    assert dock.raw["extraUnknown"] == {"a": 1}


def test_models_map_null_strings_to_empty() -> None:
    # Legacy docks have a null name; str(None) would surface as "None".
    client, _ = recorder(ok({"id": "d", "name": None, "state": "ready"}))
    assert client.docks.get("d").name == ""


def test_models_tolerate_minimal_payload() -> None:
    client, _ = recorder(ok({"id": "d", "name": "n", "state": "ready"}))
    dock = client.docks.get("d")
    assert dock.cpus is None and dock.memory_mib is None


def test_list_query() -> None:
    client, seen = recorder(ok([DOCK]))
    docks = client.docks.list(filter="x", all=True)
    assert [d.id for d in docks] == ["d1"]
    assert dict(seen[0].url.params) == {"filter": "x", "all": "true"}
    client.docks.list()
    assert not seen[1].url.query


def test_get_and_path_escaping() -> None:
    client, seen = recorder(ok(DOCK))
    client.docks.get("a/b")
    assert seen[0].method == "GET" and seen[0].url.raw_path == b"/v1/docks/a%2Fb"


def test_update() -> None:
    client, seen = recorder(ok(DOCK))
    client.docks.update("d1", name="x", disk_gib=5)
    assert (seen[0].method, seen[0].url.path) == ("PATCH", "/v1/docks/d1")
    assert body_of(seen[0]) == {"name": "x", "diskGiB": 5}


def test_exec() -> None:
    client, seen = recorder(
        ok({"exitCode": 3, "stdout": "o", "stderr": "e", "durationMs": 4, "truncated": True})
    )
    res = client.docks.exec("d1", "ls", timeout_seconds=5, env={"A": "1"}, cwd="/tmp")
    assert body_of(seen[0]) == {
        "command": "ls",
        "timeoutSeconds": 5,
        "env": {"A": "1"},
        "cwd": "/tmp",
    }
    assert (res.exit_code, res.stdout, res.stderr, res.truncated, res.duration_ms) == (
        3,
        "o",
        "e",
        True,
        4,
    )


def test_stop_resume_branch() -> None:
    client, seen = recorder(ok(DOCK, 202))
    client.docks.stop("d1")
    assert (seen[0].url.path, seen[0].content) == ("/v1/docks/d1/stop", b"")
    client.docks.stop("d1", force=True)
    assert body_of(seen[1]) == {"force": True}
    client.docks.resume("d1", cpus=2, no_env=True)
    assert seen[2].url.path == "/v1/docks/d1/resume"
    assert body_of(seen[2]) == {"cpus": 2, "noEnv": True}
    client.docks.branch("d1", name="b", memory_mib=2048, environment="e", idempotency_key="k")
    assert seen[3].url.path == "/v1/docks/d1/branch"
    assert body_of(seen[3]) == {"name": "b", "memoryMiB": 2048, "environment": "e"}
    assert seen[3].headers["idempotency-key"] == "k"


def test_delete_sends_confirm_header() -> None:
    op = {"operation": {"id": "op1", "targetType": "dock", "targetId": "d1", "status": "completed"}}
    client, seen = recorder(ok(op, 202))
    result = client.docks.delete("d1")
    assert seen[0].method == "DELETE"
    assert seen[0].headers["x-confirm-delete"] == "d1"
    assert (result.id, result.status, result.target_id) == ("op1", "completed", "d1")


def test_operations_get() -> None:
    client, seen = recorder(ok({"id": "op1", "status": "running"}))
    assert client.operations.get("op1").status == "running"
    assert seen[0].url.path == "/v1/operations/op1"


def test_error_envelope() -> None:
    resp = httpx.Response(404, json={"ok": False, "code": "dock_not_found", "message": "gone"})
    client, _ = recorder(resp)
    with pytest.raises(DockError) as info:
        client.docks.get("d1")
    assert (info.value.code, info.value.status, info.value.message) == (
        "dock_not_found",
        404,
        "gone",
    )


def test_non_json_and_network_errors() -> None:
    client, _ = recorder(httpx.Response(502, text="bad gateway"))
    with pytest.raises(DockError) as info:
        client.docks.get("d1")
    assert (info.value.code, info.value.status) == ("invalid_response", 502)

    def boom(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(DockError) as net:
        make(boom).docks.get("d1")
    assert net.value.code == "network_error"


def exec_ok(
    stdout: str = "", exit_code: int = 0, stderr: str = "", truncated: bool = False
) -> httpx.Response:
    return ok({"exitCode": exit_code, "stdout": stdout, "stderr": stderr, "truncated": truncated})


def test_shell_quote() -> None:
    assert shell_quote("it's.txt") == "'it'\\''s.txt'"
    assert shell_quote("x'; rm -rf ~; '") == "'x'\\''; rm -rf ~; '\\'''"


def test_files_write_command() -> None:
    client, seen = recorder(exec_ok())
    assert client.docks.files.write("d1", "/w/a b.txt", "hi\n") == "/w/a b.txt"
    enc = base64.b64encode(b"hi\n").decode()
    assert body_of(seen[0])["command"] == (
        "d=$(dirname -- '/w/a b.txt'; echo x) && mkdir -p -- \"${d%??}\" && "
        f"printf '%s' '{enc}' | base64 -d > '/w/a b.txt'"
    )


def test_files_write_quotes_hostile_path() -> None:
    client, seen = recorder(exec_ok())
    client.docks.files.write("d1", "x'; rm -rf ~; '", b"\x00\xff")
    command = body_of(seen[0])["command"]
    assert "'x'\\''; rm -rf ~; '\\'''" in command


def test_files_write_too_large_is_file_too_large() -> None:
    client, seen = recorder(exec_ok())
    with pytest.raises(DockError) as info:
        client.docks.files.write("d1", "/a", "x" * (MAX_WRITE_BYTES + 1))
    assert (info.value.code, info.value.status) == ("file_too_large", 0)
    assert len(seen) == 0


def largest_accepted_write(client: Dock, path: str) -> int:
    for size in range(MAX_WRITE_BYTES, 0, -3):
        try:
            client.docks.files.write("d1", path, "x" * size)
        except DockError as exc:
            assert exc.code == "file_too_large"
            continue
        return size
    return 0


@pytest.mark.parametrize(
    "path",
    ["/a", "/home/user/work/" + "p" * 200, "/w/" + "é" * 300],
    ids=["short", "long", "multibyte"],
)
def test_files_write_never_sends_a_command_over_64kb(path: str) -> None:
    # 48 KB of content is exactly 64 KB of base64, so the whole command (template
    # and the quoted path, twice) is over the API's 64 KB limit, which counts
    # UTF-8 bytes. The SDK must refuse it locally instead of sending a request the
    # API rejects with 422.
    client, seen = recorder(exec_ok())
    with pytest.raises(DockError) as info:
        client.docks.files.write("d1", path, "x" * MAX_WRITE_BYTES)
    assert info.value.code == "file_too_large"
    assert largest_accepted_write(client, path) > 47 * 1024
    assert len(seen) == 1
    command = body_of(seen[0])["command"]
    assert len(command.encode("utf-8")) <= MAX_COMMAND_BYTES
    assert len(command.encode("utf-8")) > MAX_COMMAND_BYTES - 8


LIST_COMMAND = (
    "p='/d' && case $p in /*) ;; *) p=./$p ;; esac && test -d \"$p\" && "
    'find -H "$p" -mindepth 1 -maxdepth 1 -exec sh -c '
    '\'for f; do printf "%s" "${f##*/}" | base64 -w0; echo; done\' sh {} +'
)


def b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode()


def test_files_read_and_list() -> None:
    enc = b64("héllo\n")
    client, seen = recorder(exec_ok(enc))
    assert client.docks.files.read("d1", "/a") == "héllo\n"
    assert body_of(seen[0])["command"] == "base64 -w0 -- '/a'"
    listing = "\n".join([b64("b"), "", b64("a\nb"), b64("é")]) + "\n"
    client2, seen2 = recorder(exec_ok(listing))
    assert client2.docks.files.list("d1", "/d") == ["b", "a\nb", "é"]
    assert body_of(seen2[0])["command"] == LIST_COMMAND


def test_files_nonzero_exit_is_error() -> None:
    client, _ = recorder(exec_ok("", 1, "cat: no such file\n"))
    for call in (
        lambda: client.docks.files.read("d1", "/missing"),
        lambda: client.docks.files.list("d1", "/missing"),
        lambda: client.docks.files.write("d1", "/missing/x", "hi"),
    ):
        with pytest.raises(DockError) as info:
            call()
        assert (info.value.code, info.value.status) == ("file_command_failed", 0)
        assert "no such file" in info.value.message


def test_files_truncated_output_is_error() -> None:
    # The API clips stdout at 1 MiB (a multiple of 4), so a clipped base64
    # prefix decodes cleanly; the helper must not return the partial file.
    clipped = base64.b64encode(b"a" * 900_000).decode()[: 1 << 20]
    client, _ = recorder(exec_ok(clipped, truncated=True))
    with pytest.raises(DockError) as info:
        client.docks.files.read("d1", "/big")
    assert (info.value.code, info.value.status) == ("output_truncated", 0)
    client2, _ = recorder(exec_ok(b64("a") + "\n" + b64("b") + "\n", truncated=True))
    with pytest.raises(DockError) as info2:
        client2.docks.files.list("d1", "/d")
    assert info2.value.code == "output_truncated"


def _bash_supports_helpers() -> bool:
    bash = shutil.which("bash")
    if not bash:
        return False
    probe = subprocess.run(
        [bash, "-c", "printf x | base64 -w0 && mkdir -p -- . && find -H . -maxdepth 0"],
        capture_output=True,
    )
    return probe.returncode == 0


needs_bash = pytest.mark.skipif(
    not _bash_supports_helpers(), reason="needs bash with GNU base64 and find"
)

HOSTILE_NAMES = [
    "plain.txt",
    "with space.txt",
    "-leading-dash",
    "bang!name",
    'it\'s "quoted" $HOME `x`',
    "line\nbreak",
    "trailing\n",
    "é中\U0001f600",
]


def bash_client(cwd: Path) -> Dock:
    bash = shutil.which("bash")
    assert bash

    def handler(request: httpx.Request) -> httpx.Response:
        proc = subprocess.run(
            [bash, "-c", json.loads(request.content)["command"]],
            cwd=cwd,
            capture_output=True,
        )
        return ok(
            {
                "exitCode": proc.returncode,
                "stdout": proc.stdout.decode("utf-8", errors="replace"),
                "stderr": proc.stderr.decode("utf-8", errors="replace"),
                "truncated": False,
            }
        )

    return make(handler)


@needs_bash
@pytest.mark.parametrize("name", HOSTILE_NAMES, ids=[repr(n) for n in HOSTILE_NAMES])
def test_files_hostile_names_round_trip_in_bash(tmp_path: Path, name: str) -> None:
    files = bash_client(tmp_path).docks.files
    # Relative paths: "-leading-dash" must not be read as an option, and a
    # trailing newline in the directory name must survive the dirname step.
    files.write("d1", f"{name}/sub/{name}", "payload é\n")
    assert files.read("d1", f"{name}/sub/{name}") == "payload é\n"
    assert files.list("d1", f"{name}/sub") == [name]
    assert files.list("d1", ".") == [name]
    # Absolute path.
    # (the root comes from bash itself: on Windows a C:/ path is not absolute to it).
    root = subprocess.run(
        [shutil.which("bash") or "bash", "-c", "pwd"], cwd=tmp_path, capture_output=True, text=True
    ).stdout.strip()
    files.write("d1", f"{root}/{name}/abs", "x")
    assert files.read("d1", f"{root}/{name}/abs") == "x"
    assert sorted(files.list("d1", f"{root}/{name}")) == ["abs", "sub"]


@needs_bash
def test_files_list_includes_hidden_and_follows_symlinked_dir(tmp_path: Path) -> None:
    files = bash_client(tmp_path).docks.files
    files.write("d1", "real/.hidden", "h")
    files.write("d1", "real/visible", "v")
    try:
        (tmp_path / "link").symlink_to(tmp_path / "real", target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")
    assert sorted(files.list("d1", "link")) == [".hidden", "visible"]
    with pytest.raises(DockError) as info:
        files.list("d1", "real/visible")
    assert info.value.code == "file_command_failed"


def test_update_ttl_null_unset_and_value() -> None:
    client, seen = recorder(ok(DOCK))
    client.docks.update("d1", name="x")
    client.docks.update("d1", ttl_seconds=None)
    client.docks.update("d1", ttl_seconds=UNSET)
    client.docks.update("d1", ttl_seconds=300)
    assert [body_of(r) for r in seen] == [
        {"name": "x"},
        {"ttlSeconds": None},
        {},
        {"ttlSeconds": 300},
    ]
    assert b'"ttlSeconds":null' in seen[1].content.replace(b" ", b"")


def test_unset_survives_copy_and_pickle() -> None:
    assert repr(UNSET) == "UNSET" and not UNSET
    assert copy.copy(UNSET) is UNSET
    assert copy.deepcopy(UNSET) is UNSET
    assert pickle.loads(pickle.dumps(UNSET)) is UNSET
    client, seen = recorder(ok(DOCK))
    client.docks.update("d1", **copy.deepcopy({"name": "x", "ttl_seconds": UNSET}))
    assert body_of(seen[0]) == {"name": "x"}


def test_stop_resume_return_dock_state() -> None:
    client, _ = recorder(ok({"id": "d1", "state": "stopping", "extra": 1}, 202))
    for result in (client.docks.stop("d1"), client.docks.resume("d1")):
        assert isinstance(result, DockState)
        assert (result.id, result.state, result.raw["extra"]) == ("d1", "stopping", 1)


def test_exec_idempotency_key_header() -> None:
    client, seen = recorder(exec_ok("x"))
    client.docks.exec("d1", "true", idempotency_key="k1")
    client.docks.exec("d1", "true")
    assert seen[0].headers["idempotency-key"] == "k1"
    assert "idempotency-key" not in seen[1].headers
    assert body_of(seen[0]) == {"command": "true"}


def test_files_read_bytes_and_non_utf8() -> None:
    blob = b"\xff\xfe\x00binary"
    enc = base64.b64encode(blob).decode()
    client, seen = recorder(exec_ok(enc))
    assert client.docks.files.read_bytes("d1", "/b") == blob
    assert body_of(seen[0])["command"] == "base64 -w0 -- '/b'"
    with pytest.raises(DockError) as info:
        client.docks.files.read("d1", "/b")
    assert (info.value.code, info.value.status) == ("file_not_utf8", 0)


def _run_scenarios(required: bool, tmp_path: Path) -> "subprocess.CompletedProcess[str]":
    env = {k: v for k, v in os.environ.items() if not k.startswith("DOCK_")}
    env["DOCK_SCENARIOS_DIR"] = str(tmp_path / "missing")
    if required:
        env["DOCK_SCENARIOS_REQUIRED"] = "1"
    scenarios = Path(__file__).with_name("test_scenarios.py")
    return subprocess.run(
        [sys.executable, "-m", "pytest", str(scenarios), "-q", "-p", "no:cacheprovider"],
        env=env,
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )


def test_missing_scenarios_skip_by_default_but_fail_when_required(tmp_path: Path) -> None:
    default = _run_scenarios(False, tmp_path)
    assert default.returncode == 0 and "skipped" in default.stdout
    required = _run_scenarios(True, tmp_path)
    assert required.returncode != 0 and "DOCK_SCENARIOS_REQUIRED" in required.stdout
