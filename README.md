# Dock Python SDK

The Python client for [Dock](https://github.com/usedock/dock): isolated Linux machines for agents, on your laptop, your servers, or our cloud.

> **Status:** not published to PyPI yet.

## Install

Not published to PyPI yet. Install from a checkout:

```sh
pip install -e .
```

Python 3.9 or newer. The only runtime dependency is `httpx`.

## Example

```python
from usedock import Dock

with Dock() as client:  # reads DOCK_API_KEY and DOCK_API_URL
    dock = client.docks.create(
        workspace_id="...", name="demo", cpus=1, memory_mib=1024, disk_gib=10
    )
    try:
        run = client.docks.exec(dock.id, "python3 -c 'print(2 ** 10)'")
        print(run.stdout, run.exit_code)

        client.docks.files.write(dock.id, "/home/user/work/hello.txt", "hi
")
        print(client.docks.files.read(dock.id, "/home/user/work/hello.txt"))
    finally:
        client.docks.delete(dock.id)
```

Methods on `client.docks`: `create`, `list`, `get`, `update`, `exec`, `stop`,
`resume`, `branch`, `delete`, and `files.write` / `files.read` / `files.list`.
`client.operations.get(id)` polls an operation. Create, stop, resume and branch
return when the change is done. Sizes use `cpus`, `memory_mib`, `disk_gib`.

Results are dataclasses (`DockInfo`, `ExecResult`, `Operation`). Only `id`,
`name` and `state` are relied on; unknown response fields are kept in `.raw`.

The API has no file routes, so `files.*` run one `exec` call: content travels
as base64, paths are single-quoted, and one write is capped at 48 KB
(`ValueError` above that). A non-zero exit raises `DockError` with code
`file_command_failed`.

## Errors

Every failure raises `DockError` with `code` (the API code such as
`dock_not_found` or `validation_error`), `status` (HTTP status, 0 for local
failures such as `network_error`) and `message`.

```python
from usedock import DockError

try:
    client.docks.get("00000000-0000-4000-8000-000000000000")
except DockError as err:
    print(err.code, err.status)
```

## Configuration

| Variable | Meaning | Default |
| --- | --- | --- |
| `DOCK_API_KEY` | API key (`dock_...`) | required |
| `DOCK_API_URL` | Control plane origin, without `/v1` | `https://api.usedock.io` |

`Dock(api_key=..., base_url=...)` overrides both.

## Development and scenarios

```sh
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
ruff check . && ruff format --check . && mypy && pytest
```

The client is checked against the shared scenario suite in
[usedock/dock `sdk-scenarios/`](https://github.com/usedock/dock/tree/main/sdk-scenarios),
pinned by commit in `SCENARIOS_REF`. Tests read it from `DOCK_SCENARIOS_DIR`
(default `../dock/sdk-scenarios`) and skip with a reason when it is absent.
Offline mode replays the recorded fixtures against a local fake server. Set
`DOCK_API_URL`, `DOCK_API_KEY` and `DOCK_WORKSPACE_ID` to also run every
scenario against a real control plane (use a throwaway workspace; scenarios
create and delete docks).

## Design

- Written by hand, not generated, so names read the way you would say them: `client.docks.create`, `client.docks.exec`, `client.docks.branch`.
- Only public routes. Fleet, admin and internal routes never appear.
- The same nouns and verbs as the [TypeScript](https://github.com/usedock/dock-js) and [Go](https://github.com/usedock/dock-go) SDKs, and one shared scenario suite (create, exec, stop, resume, branch, delete) that each SDK runs.
- Semver; a major version matches an API version.

## Contributing

Contributions are welcome. Every contributor signs the CLA; the CLA bot asks on your first pull request in each repository. API changes start in [usedock/dock](https://github.com/usedock/dock) and link their SDK pull requests.

## Security

Report vulnerabilities to [security@usedock.io](mailto:security@usedock.io), not in public issues.

## License

[Apache-2.0](LICENSE).

Copyright (C) 2026 Paranjay.
