# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The app proxy's signed identity, and member roles."""

from __future__ import annotations

import hashlib
import hmac

import pytest

from auto_ontology.hopsworks import identity
from auto_ontology.hopsworks.identity import (
    MAX_SIGNATURE_AGE_SECONDS,
    IdentityError,
    caller_from,
    verify,
)

KEY = "app-secret"
NOW = 1_800_000_000


def _signed(username: str, at: int = NOW, key: str = KEY) -> dict[str, str]:
    signature = hmac.new(
        key.encode(), f"{username}\n{at}".encode(), hashlib.sha256
    ).hexdigest()
    return {
        "x-hopsworks-user": username,
        "x-hopsworks-user-time": str(at),
        "x-hopsworks-user-signature": signature,
    }


def test_a_proxy_signature_names_the_member() -> None:
    assert verify(_signed("meb10000"), key=KEY, now=NOW) == "meb10000"


def test_the_java_signer_hex_format_is_accepted_in_either_case() -> None:
    headers = _signed("meb10000")
    headers["x-hopsworks-user-signature"] = headers[
        "x-hopsworks-user-signature"
    ].upper()
    assert verify(headers, key=KEY, now=NOW) == "meb10000"


@pytest.mark.parametrize(
    ("headers", "reason"),
    [
        ({}, "not signed"),
        (_signed("meb10000", key="other"), "bad signature"),
        (_signed("meb10000", at=NOW - MAX_SIGNATURE_AGE_SECONDS - 1), "stale"),
        (_signed(""), "public-link visitors"),
        ({**_signed("meb10000"), "x-hopsworks-user": "someone-else"}, "bad signature"),
    ],
)
def test_anything_else_is_refused(headers: dict[str, str], reason: str) -> None:
    with pytest.raises(IdentityError, match=reason):
        verify(headers, key=KEY, now=NOW)


def test_without_a_key_nothing_is_trusted() -> None:
    with pytest.raises(IdentityError, match="identity signing"):
        verify(_signed("meb10000"), key="", now=NOW)


def test_project_roles_map_onto_ontology_roles(monkeypatch: pytest.MonkeyPatch) -> None:
    roles = identity.MemberRoles()
    monkeypatch.setattr(
        roles,
        "_refresh",
        lambda: setattr(
            roles,
            "_roles",
            {
                "owner": "Data owner",
                "scientist": "Data scientist",
                "observer": "Observer",
                "restricted": "Feature store restricted",
                "leaving": "Under removal",
            },
        ),
    )
    assert [
        roles.role(u) for u in ("owner", "scientist", "observer", "restricted")
    ] == [
        "admin",
        "editor",
        "reader",
        "reader",
    ]
    assert roles.role("leaving") is None
    assert roles.role("stranger") is None


def test_a_non_member_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(identity.KEY_ENV, KEY)
    monkeypatch.setattr(identity.member_roles, "role", lambda username: None)
    monkeypatch.setattr(identity.time, "time", lambda: NOW)
    with pytest.raises(IdentityError, match="not a member"):
        caller_from(_signed("stranger"))
