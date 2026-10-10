"""Runs the shared SDK scenarios from usedock/dock (sdk-scenarios/).

Offline mode replays fixtures/<name>.json against a local fake HTTP server.
Live mode (DOCK_API_URL, DOCK_API_KEY, DOCK_WORKSPACE_ID set) runs the same
scenarios against a real control plane.
"""

import json
import os
import re
import secrets
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, Iterator, List, Tuple

import pytest
import yaml
from jsonschema import validate

from usedock import Dock, DockError

ROOT = Path(__file__).resolve().parent.parent
SCENARIOS_DIR = Path(
    os.environ.get("DOCK_SCENARIOS_DIR") or (ROOT.parent / "dock" / "sdk-scenarios")
)
HAVE_SCENARIOS = (SCENARIOS_DIR / "ops.yaml").is_file()
LIVE = bool(
    os.environ.get("DOCK_API_URL")
    and os.environ.get("DOCK_API_KEY")
    and os.environ.get("DOCK_WORKSPACE_ID")
)

NOT_FOUND = {"ok": False, "code": "dock_not_found", "message": "Dock not found"}

ARG_NAMES = {
    "workspaceId": "workspace_id",
    "memoryMiB": "memory_mib",
    "diskGiB": "disk_gib",
    "ttlSeconds": "ttl_seconds",
    "timeoutSeconds": "timeout_seconds",
    "noEnv": "no_env",
}


def subset(want: Any, got: Any) -> bool:
    if isinstance(want, dict):
        return isinstance(got, dict) and all(
            k in got and subset(v, got[k]) for k, v in want.items()
        )
    return want == got


class FakeServer:
    def __init__(self, exchanges: List[Dict[str, Any]]) -> None:
        self.exchanges = exchanges
        self.used = [False] * len(exchanges)
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _handle(self) -> None:
                length = int(self.headers.get("content-length") or 0)
                raw = self.rfile.read(length) if length else b""
                body = json.loads(raw) if raw else {}
                headers = {k.lower(): v for k, v in self.headers.items()}
                status, payload = outer.match(self.command, self.path.split("?")[0], body, headers)
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_PATCH = do_DELETE = _handle  # noqa: N815

            def log_message(self, *args: Any) -> None:
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_port}"

    def match(
        self, method: str, path: str, body: Dict[str, Any], headers: Dict[str, str]
    ) -> Tuple[int, Dict[str, Any]]:
        for i, ex in enumerate(self.exchanges):
            req = ex["request"]
            if (
                not self.used[i]
                and req["method"] == method
                and req["path"] == path
                and subset(req.get("body", {}), body)
                and subset(req.get("headers", {}), headers)
            ):
                self.used[i] = True
                return int(ex["response"]["status"]), ex["response"]["body"]
        return 404, NOT_FOUND

    def __enter__(self) -> "FakeServer":
        self.thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def substitute(value: Any, variables: Dict[str, Any]) -> Any:
    if isinstance(value, str):
        whole = re.fullmatch(r"\$\{(\w+)\}", value)
        if whole:
            return variables[whole.group(1)]
        return re.sub(r"\$\{(\w+)\}", lambda m: str(variables[m.group(1)]), value)
    if isinstance(value, dict):
        return {k: substitute(v, variables) for k, v in value.items()}
    if isinstance(value, list):
        return [substitute(v, variables) for v in value]
    return value


def unresolved(value: Any, variables: Dict[str, Any]) -> bool:
    return any(name not in variables for name in re.findall(r"\$\{(\w+)\}", json.dumps(value)))


def call(client: Dock, ops: Dict[str, Any], op: str, args: Dict[str, Any]) -> Tuple[int, Any]:
    """Call the SDK for an op; return (status, data)."""
    args = dict(args)
    kwargs = {ARG_NAMES.get(k, k): v for k, v in args.items() if k not in ("dockId", "path")}
    dock_id = args.get("dockId")
    status = 200
    if op in ops["http"]:
        status = ops["http"][op]["status"]
    if op == "docks.create":
        return status, client.docks.create(**kwargs).raw
    if op == "docks.list":
        return status, [d.raw for d in client.docks.list(**kwargs)]
    if op == "docks.get":
        return status, client.docks.get(dock_id).raw
    if op == "docks.update":
        return status, client.docks.update(dock_id, **kwargs).raw
    if op == "docks.exec":
        command = kwargs.pop("command")
        return status, client.docks.exec(dock_id, command, **kwargs).raw
    if op == "docks.stop":
        return status, client.docks.stop(dock_id, **kwargs).raw
    if op == "docks.resume":
        return status, client.docks.resume(dock_id, **kwargs).raw
    if op == "docks.branch":
        return status, client.docks.branch(dock_id, **kwargs).raw
    if op == "docks.delete":
        return status, {"operation": client.docks.delete(dock_id).raw}
    if op == "operations.get":
        return status, client.operations.get(args["operationId"]).raw
    if op == "docks.files.write":
        return status, {"path": client.docks.files.write(dock_id, args["path"], args["content"])}
    if op == "docks.files.read":
        return status, {"content": client.docks.files.read(dock_id, args["path"])}
    if op == "docks.files.list":
        return status, {"entries": client.docks.files.list(dock_id, args["path"])}
    raise AssertionError(f"scenario uses an op the runner does not map: {op}")


def run_op(client: Dock, ops: Dict[str, Any], op: str, args: Dict[str, Any]) -> Dict[str, Any]:
    try:
        status, data = call(client, ops, op, args)
        return {"status": status, "ok": True, "data": data}
    except DockError as err:
        return {"status": err.status, "ok": False, "code": err.code}


def dig(envelope: Dict[str, Any], path: str) -> Any:
    cur: Any = envelope
    for part in path.split("."):
        cur = cur[part]
    return cur


def data_matches(want: Any, got: Any) -> bool:
    if want == "$any":
        return got is not None
    if isinstance(want, dict):
        return isinstance(got, dict) and all(
            k in got and data_matches(v, got[k]) for k, v in want.items()
        )
    if isinstance(want, list):
        return (
            isinstance(got, list)
            and len(want) == len(got)
            and all(data_matches(w, g) for w, g in zip(want, got))
        )
    return bool(want == got)


def run_scenario(
    client: Dock, ops: Dict[str, Any], scenario: Dict[str, Any], variables: Dict[str, Any]
) -> None:
    try:
        for step in scenario["steps"]:
            args = substitute(step.get("args", {}), variables)
            envelope = run_op(client, ops, step["op"], args)
            for var, path in step.get("capture", {}).items():
                variables[var] = dig(envelope, path)
            expect = step["expect"]
            where = f"{scenario['name']} step {step['id']}"
            assert envelope["status"] == expect["status"], f"{where}: {envelope}"
            assert envelope["ok"] == expect["ok"], f"{where}: {envelope}"
            if "code" in expect:
                assert envelope.get("code") == expect["code"], f"{where}: {envelope}"
            if "data" in expect:
                want = substitute(expect["data"], variables)
                assert data_matches(want, envelope.get("data")), f"{where}: {envelope}"
    finally:
        for step in scenario.get("cleanup", []):
            if unresolved(step.get("args", {}), variables):
                continue
            run_op(client, ops, step["op"], substitute(step.get("args", {}), variables))


def load() -> Tuple[Dict[str, Any], Dict[str, Any], List[Path]]:
    ops = yaml.safe_load((SCENARIOS_DIR / "ops.yaml").read_text(encoding="utf-8"))
    schema = json.loads((SCENARIOS_DIR / "schema" / "scenario.schema.json").read_text("utf-8"))
    return ops, schema, sorted((SCENARIOS_DIR / "scenarios").glob("*.yaml"))


def names() -> List[str]:
    if not HAVE_SCENARIOS:
        return []
    return [p.stem for p in load()[2]]


@pytest.fixture(scope="module")
def suite() -> Iterator[Tuple[Dict[str, Any], Dict[str, Any]]]:
    if not HAVE_SCENARIOS:
        if os.environ.get("DOCK_SCENARIOS_REQUIRED") == "1":
            pytest.fail(f"sdk-scenarios not found at {SCENARIOS_DIR} (DOCK_SCENARIOS_REQUIRED=1)")
        pytest.skip(f"sdk-scenarios not found at {SCENARIOS_DIR}; set DOCK_SCENARIOS_DIR")
    ops, schema, _ = load()
    yield ops, schema


def read_scenario(schema: Dict[str, Any], name: str) -> Dict[str, Any]:
    scenario: Dict[str, Any] = yaml.safe_load(
        (SCENARIOS_DIR / "scenarios" / f"{name}.yaml").read_text(encoding="utf-8")
    )
    validate(scenario, schema)
    assert scenario["name"] == name
    return scenario


def test_scenarios_present(suite: Any) -> None:
    assert names(), "no scenarios found"


@pytest.mark.parametrize("name", names() or ["<missing>"])
def test_scenario_offline(name: str, suite: Any) -> None:
    ops, schema = suite
    scenario = read_scenario(schema, name)
    fixture = json.loads((SCENARIOS_DIR / "fixtures" / f"{name}.json").read_text("utf-8"))
    variables: Dict[str, Any] = dict(fixture["variables"])
    with FakeServer(fixture["exchanges"]) as server:
        client = Dock("dock_fake", server.url)
        run_scenario(client, ops, scenario, variables)


@pytest.mark.skipif(not LIVE, reason="set DOCK_API_URL, DOCK_API_KEY and DOCK_WORKSPACE_ID")
@pytest.mark.parametrize("name", names() or ["<missing>"])
def test_scenario_live(name: str, suite: Any) -> None:
    ops, schema = suite
    scenario = read_scenario(schema, name)
    variables: Dict[str, Any] = {
        "workspaceId": os.environ["DOCK_WORKSPACE_ID"],
        "run": secrets.token_hex(3),
    }
    with Dock() as client:
        run_scenario(client, ops, scenario, variables)


def test_runner_reports_mismatch(suite: Any) -> None:
    """The runner must fail on a wrong expectation, not pass vacuously."""
    ops, _ = suite
    scenario: Dict[str, Any] = {
        "name": "x",
        "steps": [
            {
                "id": "get",
                "op": "docks.get",
                "args": {"dockId": "d"},
                "expect": {"status": 200, "ok": True},
            }
        ],
    }
    with FakeServer([]) as server:
        with pytest.raises(AssertionError):
            run_scenario(Dock("dock_fake", server.url), ops, scenario, {})
