# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Write auto_ontology/server/route_permissions.json from the public API spec.

Upstream checked permissions in its Next.js gateway, one ``withPermission`` per
route, and recorded each in the spec as ``x-auto-ontology-permissions``. On
Hopsworks the FastAPI app checks them itself, from the table this writes. Path
parameters are normalised to ``{}`` because the gateway and FastAPI name them
differently. Routes the spec never had are added from :data:`EXTRA`.

Run: uv run python -m dev_tools.generate_route_permissions
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "docs" / "openapi" / "auto-ontology-api.json"
OUTPUT = ROOT / "auto_ontology" / "server" / "route_permissions.json"

#: Routes added on Hopsworks, or that only the backend served upstream.
EXTRA: dict[str, list[str]] = {
    "GET /api/me": [],
    "GET /api/sources": ["connection:read"],
    "POST /api/sources": ["connection:manage"],
    "DELETE /api/sources/{}": ["connection:manage"],
    "POST /api/semantic-compilation/trigger": ["semanticCompilation:manage"],
    "GET /api/sql-attributes": ["catalog:read"],
}

#: Routes upstream had that the Hopsworks app does not serve.
DROPPED = re.compile(
    r"^/api/(auth|api-tokens|invitations|sso-discovery|sso-providers|zones|groups|connections)(/|$)"
)


def key(method: str, path: str) -> str:
    return f"{method.upper()} {re.sub(r'\{[^}]+\}', '{}', path)}"


def build() -> dict[str, list[str]]:
    spec = json.loads(SPEC.read_text())
    table: dict[str, list[str]] = {}
    for path, operations in spec["paths"].items():
        if DROPPED.match(path):
            continue
        for method, operation in operations.items():
            if not isinstance(operation, dict):
                continue
            permissions = operation.get("x-auto-ontology-permissions") or {}
            if permissions == "public":
                table[key(method, path)] = []
                continue
            table[key(method, path)] = sorted(
                f"{resource}:{action}"
                for resource, actions in permissions.items()
                for action in actions
            )
    table.update(EXTRA)
    return dict(sorted(table.items()))


def main() -> None:
    OUTPUT.write_text(json.dumps(build(), indent=2) + "\n")
    print(f"wrote {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
