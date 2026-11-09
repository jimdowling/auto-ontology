# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The caller's name as routers read it."""

import pytest
from fastapi import HTTPException, Request

from auto_ontology.hopsworks.identity import Caller
from auto_ontology.server.identity import resolve_internal_user


def _request(caller: Caller | None) -> Request:
    request = Request(
        {"type": "http", "method": "POST", "path": "/api/tags", "headers": []}
    )
    if caller is not None:
        request.state.caller = caller
    return request


def test_the_verified_caller_names_the_user() -> None:
    assert (
        resolve_internal_user(_request(Caller("meb10000", "admin")), required=True)
        == "meb10000"
    )


def test_a_missing_caller_is_none_when_optional() -> None:
    assert resolve_internal_user(_request(None), required=False) is None


def test_a_missing_caller_is_refused_when_required() -> None:
    with pytest.raises(HTTPException) as exc_info:
        resolve_internal_user(_request(None), required=True)
    assert exc_info.value.status_code == 401


def test_a_client_header_is_not_an_identity() -> None:
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/tags",
            "headers": [(b"x-auto-ontology-user-id", b"admin")],
        }
    )
    assert resolve_internal_user(request, required=False) is None
