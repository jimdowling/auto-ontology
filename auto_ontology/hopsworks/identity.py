# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Who is calling, as the Hopsworks app proxy says, and their project role.

The proxy signs every request it forwards for a member with the member's
username, the time, and an HMAC-SHA256 hex digest of ``username + "\\n" +
epochSeconds`` under the app's secret (``HOPSWORKS_APP_IDENTITY_KEY``). Other
pods in the project namespace can reach the app's Service directly, which is
why an unsigned or stale request is refused rather than trusted.

The role comes from the project's member list, read with the app's own
Hopsworks identity and cached briefly: a member whose role changes keeps the
old one for at most :data:`ROLE_CACHE_SECONDS`.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass

USER_HEADER = "x-hopsworks-user"
TIME_HEADER = "x-hopsworks-user-time"
SIGNATURE_HEADER = "x-hopsworks-user-signature"
KEY_ENV = "HOPSWORKS_APP_IDENTITY_KEY"

#: How old a signature may be, in seconds. Covers clock skew between the
#: Payara pod and the app pod, and a request queued behind a slow one.
MAX_SIGNATURE_AGE_SECONDS = 300
ROLE_CACHE_SECONDS = 60

#: Hopsworks project roles, as the member list spells them, to ontology roles.
PROJECT_ROLES = {
    "Data owner": "admin",
    "Data scientist": "editor",
    "Observer": "reader",
    "Feature store restricted": "reader",
}


class IdentityError(Exception):
    """The request carries no valid proxy signature, or the caller is not a member."""


@dataclass(frozen=True)
class Caller:
    username: str
    role: str


def verify(
    headers: Mapping[str, str], *, key: str | None = None, now: float | None = None
) -> str:
    """The signed username. Raises :class:`IdentityError` when the signature is
    missing, wrong or older than :data:`MAX_SIGNATURE_AGE_SECONDS`, or names a
    public-link visitor (an empty username)."""
    secret = key if key is not None else os.environ.get(KEY_ENV)
    if not secret:
        raise IdentityError(
            f"{KEY_ENV} is not set: the app was created without identity signing"
        )
    username = headers.get(USER_HEADER)
    stamp = headers.get(TIME_HEADER)
    signature = headers.get(SIGNATURE_HEADER)
    if username is None or not stamp or not signature:
        raise IdentityError("request was not signed by the Hopsworks app proxy")
    try:
        signed_at = int(stamp)
    except ValueError:
        raise IdentityError("malformed signature time") from None
    current = time.time() if now is None else now
    if abs(current - signed_at) > MAX_SIGNATURE_AGE_SECONDS:
        raise IdentityError("stale signature")
    expected = hmac.new(
        secret.encode("utf-8"), f"{username}\n{signed_at}".encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, signature.lower()):
        raise IdentityError("bad signature")
    if not username:
        raise IdentityError("public-link visitors cannot use the ontology")
    return username


class MemberRoles:
    """Project member roles, refreshed at most every :data:`ROLE_CACHE_SECONDS`."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._roles: dict[str, str] = {}
        self._profiles: dict[str, dict[str, str]] = {}
        self._loaded_at = 0.0

    def _refresh(self) -> None:
        from auto_ontology.hopsworks.client import login

        members = login().get_members()
        self._roles = {member.username: member.role for member in members}
        self._profiles = {
            member.username: {
                "id": member.username,
                "name": " ".join(filter(None, (member.first_name, member.last_name)))
                or member.username,
                "email": member.email or "",
            }
            for member in members
        }
        self._loaded_at = time.monotonic()

    def profile(self, username: str) -> dict[str, str] | None:
        """``{id, name, email}`` of member ``username``, or ``None`` when not a member."""
        with self._lock:
            if time.monotonic() - self._loaded_at > ROLE_CACHE_SECONDS:
                self._refresh()
            found = self._profiles.get(username)
        return dict(found) if found else None

    def all(self) -> dict[str, str]:
        """Every member's ontology role, by username."""
        with self._lock:
            if time.monotonic() - self._loaded_at > ROLE_CACHE_SECONDS:
                self._refresh()
            roles = dict(self._roles)
        return {
            username: PROJECT_ROLES[project_role]
            for username, project_role in roles.items()
            if project_role in PROJECT_ROLES
        }

    def role(self, username: str) -> str | None:
        """The ontology role of ``username``, or ``None`` when not a member."""
        with self._lock:
            if time.monotonic() - self._loaded_at > ROLE_CACHE_SECONDS:
                self._refresh()
            project_role = self._roles.get(username)
        return PROJECT_ROLES.get(project_role) if project_role else None


member_roles = MemberRoles()


def caller_from(headers: Mapping[str, str]) -> Caller:
    """The verified caller. Raises :class:`IdentityError` when unsigned or not a member."""
    username = verify(headers)
    role = member_roles.role(username)
    if role is None:
        raise IdentityError(f"{username} is not a member of this project")
    return Caller(username=username, role=role)
