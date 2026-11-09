# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Instance settings: configuration flags, acronyms and custom prompts.

Upstream the frontend owned these tables through Prisma; on Hopsworks they are
app tables and the API serves them. Configuration values are strings: flags
are ``"true"``/``"false"``, numbers are decimal integer strings.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from auto_ontology.dal import ops
from auto_ontology.dal import schema as s
from auto_ontology.dal.session import store, write_transaction
from auto_ontology.dal.types import new_id, utcnow

_ACRONYM_COLUMNS = (
    s.acronyms.c.id,
    s.acronyms.c.name,
    s.acronyms.c.description,
    s.acronyms.c.created_at,
    s.acronyms.c.updated_at,
)


def get_configuration(key: str) -> str | None:
    """The stored value of ``key``, or ``None`` when it has never been set."""
    rows = store().query_read(
        select(s.configurations.c.value).where(s.configurations.c.key == key)
    )
    return rows[0]["value"] if rows else None


def set_configuration(key: str, value: str) -> None:
    ops.upsert(
        s.configurations,
        {"key": key, "value": value},
        key=["key"],
        set_=lambda new: {"value": new.value, "updated_at": utcnow()},
    )


def list_acronyms(*, newest_first: bool = False) -> list[dict[str, Any]]:
    """Every acronym, oldest first unless ``newest_first``."""
    order = s.acronyms.c.created_at.desc() if newest_first else s.acronyms.c.created_at
    return store().query_read(select(*_ACRONYM_COLUMNS).order_by(order))


def find_acronym(name: str) -> dict[str, Any] | None:
    rows = store().query_read(
        select(*_ACRONYM_COLUMNS).where(s.acronyms.c.name == name)
    )
    return rows[0] if rows else None


def create_acronym(name: str, description: str = "") -> dict[str, Any]:
    """Raises the driver's integrity error when the name already exists."""
    return ops.insert_returning(
        s.acronyms, {"name": name, "description": description}, _ACRONYM_COLUMNS
    )[0]


def update_acronym(acronym_id: str, **values: Any) -> dict[str, Any] | None:
    """Update ``name`` and/or ``description``; ``None`` when the id is unknown."""
    rows = ops.update_returning(
        s.acronyms, s.acronyms.c.id == acronym_id, values, _ACRONYM_COLUMNS
    )
    return rows[0] if rows else None


def delete_acronym(acronym_id: str) -> bool:
    return bool(
        ops.delete_returning(
            s.acronyms, s.acronyms.c.id == acronym_id, [s.acronyms.c.id]
        )
    )


def list_prompts() -> list[dict[str, Any]]:
    return store().query_read(select(s.prompts.c.id, s.prompts.c.content))


def get_prompt(prompt_id: str) -> dict[str, Any] | None:
    rows = store().query_read(
        select(s.prompts.c.id, s.prompts.c.content).where(s.prompts.c.id == prompt_id)
    )
    return rows[0] if rows else None


def list_analytics(
    since: Any, skip: int, limit: int | None
) -> tuple[list[dict[str, Any]], int]:
    """Questions asked since ``since``, newest first, paged; and their total."""
    table = s.conversation_analytics
    where = table.c.question_timestamp >= since
    total = store().query_read(
        select(func.count().label("n")).select_from(table).where(where)
    )[0]["n"]
    query = (
        select(*table.c)
        .where(where)
        .order_by(table.c.question_timestamp.desc())
        .offset(skip)
    )
    if limit is not None:
        query = query.limit(limit)
    return store().query_read(query), int(total)


def create_prompt(content: str) -> dict[str, Any]:
    prompt_id = new_id()
    with write_transaction():
        store().query_write(s.prompts.insert().values(id=prompt_id, content=content))
    return {"id": prompt_id, "content": content}


def update_prompt(prompt_id: str, content: str) -> dict[str, Any] | None:
    rows = ops.update_returning(
        s.prompts,
        s.prompts.c.id == prompt_id,
        {"content": content},
        [s.prompts.c.id, s.prompts.c.content],
    )
    return rows[0] if rows else None


def delete_prompt(prompt_id: str) -> bool:
    return bool(
        ops.delete_returning(s.prompts, s.prompts.c.id == prompt_id, [s.prompts.c.id])
    )
