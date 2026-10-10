# Dock Python SDK

The Python client for [Dock](https://github.com/usedock/dock): isolated Linux machines for agents, on your laptop, your servers, or our cloud.

> **Status:** not released yet. This SDK is being written by hand.

## Proposed API: install

Not published yet; the package name is not claimed.

```sh
pip install usedock
```

## Proposed API: example

Nothing below works yet; it shows the intended shape.

```python
from usedock import Dock

with Dock.create(cpus=2, memory="4gb") as dock:   # deleted on exit
    run = dock.exec("python -c 'print(2 ** 10)'")
    print(run.stdout)
```

The client reads `DOCK_API_KEY` and the current context: a self-hosted control plane, or Dock Cloud (coming soon).

## Design

- Written by hand, not generated, so names read the way you would say them: `Dock.create`, `dock.exec`, `dock.branch`.
- Only public routes. Fleet, admin and internal routes never appear.
- The same nouns and verbs as the [TypeScript](https://github.com/usedock/dock-js) and [Go](https://github.com/usedock/dock-go) SDKs, and, planned, one shared scenario suite (create, exec, stop, resume, branch, delete) run against a real control plane.
- Semver; a major version matches an API version.

## Contributing

Contributions are welcome. Every contributor signs the CLA; the CLA bot asks on your first pull request in each repository. API changes start in [usedock/dock](https://github.com/usedock/dock) and link their SDK pull requests.

## Security

Report vulnerabilities to [security@usedock.io](mailto:security@usedock.io), not in public issues.

## License

[Apache-2.0](LICENSE).

Copyright (C) 2026 Paranjay.
