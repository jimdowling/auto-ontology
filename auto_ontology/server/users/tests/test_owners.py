# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Who may own a row, and who may edit one."""

from __future__ import annotations

import pytest
from fastapi import HTTPException, Request

from auto_ontology.dal.owners import EditSubject
from auto_ontology.hopsworks.identity import Caller
from auto_ontology.server import owners


def _request(caller: Caller) -> Request:
    request = Request(
        {"type": "http", "method": "PATCH", "path": "/api/terms/t", "headers": []}
    )
    request.state.caller = caller
    return request


def _subject(owner_id: str | None = None) -> EditSubject:
    return EditSubject(owner_id=owner_id, permission="catalog:edit")


def test_an_editor_may_edit_the_catalog() -> None:
    owners.enforce_edit(_request(Caller("scientist", "editor")), _subject())


def test_a_reader_may_not() -> None:
    with pytest.raises(HTTPException) as exc_info:
        owners.enforce_edit(_request(Caller("observer", "reader")), _subject())
    assert exc_info.value.status_code == 403


def test_a_reader_may_edit_a_row_they_own() -> None:
    owners.enforce_edit(
        _request(Caller("observer", "reader")), _subject(owner_id="observer")
    )


def test_an_owner_must_be_a_member_whose_role_grants_the_edit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roles = {"owner": "admin", "scientist": "editor", "observer": "reader"}
    monkeypatch.setattr(owners.member_roles, "role", roles.get)
    assert owners.require_assignable("scientist", "catalog:edit") == "scientist"
    for refused in ("observer", "stranger"):
        with pytest.raises(owners.UnassignableOwner):
            owners.require_assignable(refused, "catalog:edit")


def test_a_blank_owner_id_means_unassigned() -> None:
    assert owners.normalize_owner_id("  ") is None
    assert owners.owner_from_body("", "catalog:edit") is None
