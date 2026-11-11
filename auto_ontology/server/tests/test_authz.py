# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Request identity and route permissions."""

from __future__ import annotations

import hashlib
import hmac
import time

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

from auto_ontology.hopsworks import identity
from auto_ontology.server import authz

KEY = "app-secret"


def _signed(username: str) -> dict[str, str]:
    now = int(time.time())
    signature = hmac.new(
        KEY.encode(), f"{username}\n{now}".encode(), hashlib.sha256
    ).hexdigest()
    return {
        "X-Hopsworks-User": username,
        "X-Hopsworks-User-Time": str(now),
        "X-Hopsworks-User-Signature": signature,
    }


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv(identity.KEY_ENV, KEY)
    monkeypatch.delenv("ONTOLOGY_DEV_USER", raising=False)
    roles = {"owner": "admin", "scientist": "editor", "observer": "reader"}
    monkeypatch.setattr(identity.member_roles, "role", roles.get)
    monkeypatch.setattr(
        identity.member_roles,
        "profile",
        lambda u: (
            {"id": u, "name": u.title(), "email": f"{u}@x"} if u in roles else None
        ),
    )
    monkeypatch.setattr(
        authz,
        "route_permissions",
        lambda: {
            "GET /api/terms": frozenset({"catalog:read"}),
            "POST /api/chat/completions": frozenset({"chat:use"}),
            "GET /api/columns/{}": frozenset({"catalog:read"}),
            "GET /api/tags": frozenset({"catalog:read"}),
        },
    )
    app = FastAPI(dependencies=[Depends(authz.authorize)])
    app.add_middleware(authz.IdentityMiddleware)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    # As create_app does: FastAPI 0.141 keeps an included router unflattened, so the
    # matched route carries "/terms", not "/api/terms".
    api = APIRouter()

    @api.get("/terms")
    def terms() -> list:
        return []

    @api.post("/chat/completions")
    def chat() -> dict:
        return {"answer": "42"}

    @api.get("/columns/{table_id}")
    def columns(table_id: str) -> dict:
        return {"data": [{"name": "email", "sample_values": '["a@b"]'}]}

    @api.get("/tags")
    def tags() -> dict:
        return {
            "data": [
                {"id": "t1", "created_by": "owner", "modified_by": None},
                {"id": "t2", "created_by": "gone", "modified_by": "scientist"},
            ]
        }

    @api.post("/semantic-compilation/trigger")
    def unlisted() -> dict:
        return {"status": "accepted"}

    app.include_router(api, prefix="/api")
    return TestClient(app)


def test_the_readiness_probe_needs_no_caller(client: TestClient) -> None:
    assert client.get("/health").status_code == 200


def test_an_unsigned_request_is_refused(client: TestClient) -> None:
    assert client.get("/api/terms").status_code == 401


def test_a_non_member_is_forbidden(client: TestClient) -> None:
    assert client.get("/api/terms", headers=_signed("stranger")).status_code == 403


def test_a_reader_can_read_but_not_chat(client: TestClient) -> None:
    assert client.get("/api/terms", headers=_signed("observer")).status_code == 200
    response = client.post("/api/chat/completions", headers=_signed("observer"))
    assert response.status_code == 403
    assert "chat:use" in response.json()["detail"]


def test_an_editor_can_chat(client: TestClient) -> None:
    assert (
        client.post("/api/chat/completions", headers=_signed("scientist")).status_code
        == 200
    )


def test_an_unlisted_route_is_admin_only(client: TestClient) -> None:
    path = "/api/semantic-compilation/trigger"
    assert client.post(path, headers=_signed("scientist")).status_code == 403
    assert client.post(path, headers=_signed("owner")).status_code == 200


def test_readers_never_see_sample_values(client: TestClient) -> None:
    reader = client.get("/api/columns/t1", headers=_signed("observer")).json()
    editor = client.get("/api/columns/t1", headers=_signed("scientist")).json()
    assert "sample_values" not in reader["data"][0]
    assert editor["data"][0]["sample_values"] == '["a@b"]'


def test_the_dev_caller_is_refused_once_an_identity_key_is_set(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ONTOLOGY_DEV_USER", "dev")
    assert client.get("/api/terms").status_code == 401
    monkeypatch.delenv(identity.KEY_ENV)
    assert client.get("/api/terms").status_code == 200


def test_tag_authors_are_resolved_to_project_members(client: TestClient) -> None:
    rows = client.get("/api/tags", headers=_signed("observer")).json()["data"]
    assert rows[0]["created_by_user"] == {
        "id": "owner",
        "name": "Owner",
        "email": "owner@x",
    }
    assert rows[0]["modified_by_user"] is None
    assert rows[1]["created_by_user"] is None
    assert rows[1]["modified_by_user"]["name"] == "Scientist"


def test_a_failed_member_lookup_costs_only_the_author_name(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def down(username: str) -> None:
        raise ConnectionError("Hopsworks unreachable")

    monkeypatch.setattr(identity.member_roles, "profile", down)
    response = client.get("/api/tags", headers=_signed("owner"))
    assert response.status_code == 200
    assert response.json()["data"][0]["created_by_user"] is None
