import base64
import json
from typing import Any, Callable, Dict, List, Tuple

import httpx
import pytest

from usedock import MAX_WRITE_BYTES, Dock, DockError
from usedock.client import shell_quote

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


def exec_ok(stdout: str = "", exit_code: int = 0, stderr: str = "") -> httpx.Response:
    return ok({"exitCode": exit_code, "stdout": stdout, "stderr": stderr, "truncated": False})


def test_shell_quote() -> None:
    assert shell_quote("it's.txt") == "'it'\\''s.txt'"
    assert shell_quote("x'; rm -rf ~; '") == "'x'\\''; rm -rf ~; '\\'''"


def test_files_write_command() -> None:
    client, seen = recorder(exec_ok())
    assert client.docks.files.write("d1", "/w/a b.txt", "hi\n") == "/w/a b.txt"
    enc = base64.b64encode(b"hi\n").decode()
    assert body_of(seen[0])["command"] == (
        "mkdir -p -- \"$(dirname -- '/w/a b.txt')\" && "
        f"printf '%s' '{enc}' | base64 -d > '/w/a b.txt'"
    )


def test_files_write_quotes_hostile_path() -> None:
    client, seen = recorder(exec_ok())
    client.docks.files.write("d1", "x'; rm -rf ~; '", b"\x00\xff")
    command = body_of(seen[0])["command"]
    assert "'x'\\''; rm -rf ~; '\\'''" in command


def test_files_write_size_cap() -> None:
    client, seen = recorder(exec_ok())
    client.docks.files.write("d1", "/a", "x" * MAX_WRITE_BYTES)
    with pytest.raises(ValueError):
        client.docks.files.write("d1", "/a", "x" * (MAX_WRITE_BYTES + 1))
    assert len(seen) == 1


def test_files_read_and_list() -> None:
    enc = base64.b64encode("héllo\n".encode()).decode()
    client, seen = recorder(exec_ok(enc))
    assert client.docks.files.read("d1", "/a") == "héllo\n"
    assert body_of(seen[0])["command"] == "base64 -w0 -- '/a'"
    client2, seen2 = recorder(exec_ok("b\n\na\n"))
    assert client2.docks.files.list("d1", "/d") == ["b", "a"]
    assert body_of(seen2[0])["command"] == "ls -1A -- '/d'"


def test_files_nonzero_exit_is_error() -> None:
    client, _ = recorder(exec_ok("", 1, "cat: no such file\n"))
    with pytest.raises(DockError) as info:
        client.docks.files.read("d1", "/missing")
    assert info.value.code == "file_command_failed"
    assert "no such file" in info.value.message
