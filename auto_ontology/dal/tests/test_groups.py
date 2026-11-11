# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Groups and their membership.

Members are Hopsworks usernames stored as given; the DAL reads no account
table, so a member is reported by its stored id. Needs a migrated database.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
import os
import uuid

import pytest

pytest.importorskip("sqlalchemy")

from auto_ontology.dal import groups as dal  # noqa: E402
from auto_ontology.dal import schema as s  # noqa: E402
from auto_ontology.dal.session import store  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def require_schema() -> None:
    if not os.environ.get("MYSQL_USER"):
        pytest.skip("MYSQL_* not set")
    store().query_read(f"SELECT 1 FROM {s.user_group.name} LIMIT 1")


@pytest.fixture
def accounts() -> Iterator[Callable[..., str]]:
    """Usernames sharing a prefix, removed with the groups this test creates."""
    prefix = f"grp-{uuid.uuid4().hex[:8]}"
    created: list[str] = []

    def make(name: str | None = None) -> str:
        user_id = f"{prefix}-{name or len(created)}"
        created.append(user_id)
        return user_id

    yield make

    store().query_write(
        s.user_group.delete().where(s.user_group.c.name.like(f"{prefix}%"))
    )


def test_a_group_keeps_its_members(accounts) -> None:
    first = accounts("ada")
    second = accounts("grace")
    prefix = first.rsplit("-", 1)[0]

    created = dal.create_group(
        name=f"{prefix} Finance",
        description="books",
        color="#76b900",
        role="viewer",
        user_ids=[second, first],
    )

    assert created["description"] == "books"
    assert created["role"] == "viewer"
    assert created["users"] == [
        {"id": first, "name": first},
        {"id": second, "name": second},
    ]

    again = dal.get_group(created["id"])
    assert again is not None
    assert [user["id"] for user in again["users"]] == [first, second]


def test_names_collide_case_insensitively(accounts) -> None:
    user_id = accounts()
    prefix = user_id.rsplit("-", 1)[0]
    dal.create_group(
        name=f"{prefix} Finance",
        description=None,
        color="#000",
        role="admin",
        user_ids=[user_id],
    )
    with pytest.raises(dal.GroupNameTaken):
        dal.create_group(
            name=f"  {prefix} finance  ",
            description=None,
            color="#111",
            role="viewer",
            user_ids=[],
        )


def test_replacing_members_and_deleting_the_group(accounts) -> None:
    first = accounts("ada")
    second = accounts("grace")
    prefix = first.rsplit("-", 1)[0]
    created = dal.create_group(
        name=f"{prefix} Finance",
        description=None,
        color="#000",
        role="viewer",
        user_ids=[first],
    )

    updated = dal.update_group(
        group_id=created["id"],
        updates={"role": "admin"},
        user_ids=[second],
    )
    assert updated is not None
    assert updated["role"] == "admin"
    assert [user["id"] for user in updated["users"]] == [second]
    assert [group["id"] for group in dal.groups_for_user(second)] == [created["id"]]
    assert dal.groups_for_user(first) == []

    assert dal.delete_group(created["id"]) is True
    assert dal.get_group(created["id"]) is None
    assert dal.delete_group(created["id"]) is False


def test_directory_lists_members_with_their_group_ids(accounts) -> None:
    first = accounts("ada")
    second = accounts("grace")
    prefix = first.rsplit("-", 1)[0]
    finance = dal.create_group(
        name=f"{prefix} Finance",
        description=None,
        color="#000",
        role="viewer",
        user_ids=[first],
    )
    legal = dal.create_group(
        name=f"{prefix} Legal",
        description=None,
        color="#111",
        role="admin",
        user_ids=[first, second],
    )

    directory = dal.list_users_and_groups()
    by_id = {user["id"]: user for user in directory["users"]}
    assert by_id[first] == {
        "id": first,
        "name": first,
        "groups": [finance["id"], legal["id"]],
    }
    assert by_id[second]["groups"] == [legal["id"]]


def test_updating_a_missing_group_does_not_write_members(accounts) -> None:
    user_id = accounts()
    assert (
        dal.update_group(
            group_id="missing-group",
            updates={"color": "#fff"},
            user_ids=[user_id],
        )
        is None
    )
    assert dal.get_group("missing-group") is None


def test_a_name_race_lost_at_the_unique_key_is_still_name_taken(
    accounts, monkeypatch
) -> None:
    """The check and the insert are separate statements; a create slipping
    between them is caught by ``uq_user_group_name_lower`` instead."""
    prefix = accounts().rsplit("-", 1)[0]
    dal.create_group(
        name=f"{prefix} Finance",
        description=None,
        color="#000",
        role="viewer",
        user_ids=[],
    )
    monkeypatch.setattr(dal, "_name_taken", lambda name, **kwargs: False)
    with pytest.raises(dal.GroupNameTaken):
        dal.create_group(
            name=f"{prefix} FINANCE",
            description=None,
            color="#111",
            role="viewer",
            user_ids=[],
        )
