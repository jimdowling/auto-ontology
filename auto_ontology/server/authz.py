# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Who the caller is and what they may do, for every request.

:class:`IdentityMiddleware` verifies the Hopsworks app proxy's signature and
resolves the caller's project role (:mod:`auto_ontology.hopsworks.identity`),
refusing anything unsigned except the readiness probe. :func:`authorize`, an
app-wide dependency, then checks the route's permissions against the role, from
``route_permissions.json`` (generated from upstream's public API spec by
``dev_tools/generate_route_permissions.py``). A route missing from that table is
admin-only, so a new route is closed until someone lists it.

Readers (Observers and feature-store-restricted members) cannot preview data
sources in Hopsworks, so ``sample_values`` -- profiled values from those
sources -- are removed from every JSON response they get, whichever endpoint
carries them.

Rows store the username of whoever created, modified or tagged them; on the
routes in :data:`AUTHOR_PATHS` each such row also gets ``created_by_user``,
``modified_by_user`` or ``tagged_by_user`` as ``{id, name, email}`` of that
member, or ``None`` for an account that is no longer one.

For local runs without the proxy, ``ONTOLOGY_DEV_USER`` (and optionally
``ONTOLOGY_DEV_ROLE``, default ``admin``) names the caller; it is refused when
the identity key is set, so it cannot loosen a deployed app.
"""

from __future__ import annotations

import json
import logging
import os
import re
from functools import cache
from importlib import resources
from typing import Any

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from auto_ontology.hopsworks.identity import (
    KEY_ENV,
    Caller,
    IdentityError,
    caller_from,
    member_roles,
)
from auto_ontology.server.users.permissions import permissions_for_role

logger = logging.getLogger(__name__)

#: Paths answered without a caller: the readiness and liveness probes.
OPEN_PATHS = frozenset({"/health", "/api/health", "/api/health/live"})

#: Routes whose rows carry ``created_by``, ``modified_by`` or ``tagged_by``.
AUTHOR_PATHS = ("/api/tags", "/api/rules", "/api/sql-attributes/", "/api/terms/")
_AUTHOR_COLUMNS = {
    "created_by": "created_by_user",
    "modified_by": "modified_by_user",
    "tagged_by": "tagged_by_user",
}

_PARAMETER = re.compile(r"\{[^}]+\}")


@cache
def route_permissions() -> dict[str, frozenset[str]]:
    raw = json.loads(
        resources.files("auto_ontology.server")
        .joinpath("route_permissions.json")
        .read_text()
    )
    return {route: frozenset(permissions) for route, permissions in raw.items()}


def _dev_caller() -> Caller | None:
    user = os.environ.get("ONTOLOGY_DEV_USER")
    if not user or os.environ.get(KEY_ENV):
        return None
    return Caller(username=user, role=os.environ.get("ONTOLOGY_DEV_ROLE", "admin"))


def _strip_sample_values(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: _strip_sample_values(v) for k, v in value.items() if k != "sample_values"
        }
    if isinstance(value, list):
        return [_strip_sample_values(item) for item in value]
    return value


def _author(username: Any) -> dict[str, str] | None:
    if not username:
        return None
    try:
        return member_roles.profile(username)
    except Exception as exc:
        # The request already succeeded; a members lookup failing only costs the name.
        logger.warning("Could not resolve author %s: %s", username, exc)
        return None


def _with_authors(payload: Any) -> Any:
    data = payload.get("data") if isinstance(payload, dict) else None
    for row in data if isinstance(data, list) else [data]:
        if not isinstance(row, dict):
            continue
        for column, author in _AUTHOR_COLUMNS.items():
            if column in row:
                row[author] = _author(row[column])
    return payload


class IdentityMiddleware(BaseHTTPMiddleware):
    """Sets ``request.state.caller``, or answers 401/403 itself."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.url.path in OPEN_PATHS:
            return await call_next(request)
        caller = _dev_caller()
        if caller is None:
            try:
                caller = caller_from(request.headers)
            except IdentityError as exc:
                logger.warning(
                    "Refused %s %s: %s", request.method, request.url.path, exc
                )
                status = 403 if "not a member" in str(exc) else 401
                return JSONResponse({"detail": str(exc)}, status_code=status)
        request.state.caller = caller
        response = await call_next(request)
        strip = caller.role == "reader"
        authors = request.url.path.startswith(AUTHOR_PATHS)
        if not (strip or authors) or not response.headers.get(
            "content-type", ""
        ).startswith("application/json"):
            return response
        body = b"".join([chunk async for chunk in response.body_iterator])
        headers = {
            k: v for k, v in response.headers.items() if k.lower() != "content-length"
        }
        payload = json.loads(body or b"null")
        if authors and response.status_code < 400:
            payload = _with_authors(payload)
        if strip:
            payload = _strip_sample_values(payload)
        return JSONResponse(payload, status_code=response.status_code, headers=headers)


def current_caller(request: Request) -> Caller:
    """The verified caller. Raises 401 when the middleware set none."""
    caller = getattr(request.state, "caller", None)
    if caller is None:
        raise HTTPException(status_code=401, detail="No verified caller")
    return caller


def has_permission(caller: Caller, permission: str) -> bool:
    return permission in permissions_for_role(caller.role)


def authorize(request: Request) -> None:
    """403 unless the caller holds every permission the matched route requires."""
    if request.url.path in OPEN_PATHS:
        return
    route = request.scope.get("route")
    if route is None or not request.url.path.startswith("/api/"):
        return
    caller = current_caller(request)
    required = route_permissions().get(
        f"{request.method} {_PARAMETER.sub('{}', route.path)}"
    )
    if required is None:
        if caller.role != "admin":
            raise HTTPException(status_code=403, detail="Admins only")
        return
    granted = set(permissions_for_role(caller.role))
    missing = sorted(required - granted)
    if missing:
        raise HTTPException(
            status_code=403, detail=f"Missing permission: {', '.join(missing)}"
        )
