# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Column types that let the Postgres-shaped DAL run on RonDB.

Each one keeps the Python value callers already handle -- a list for what was a
``text[]``, a dict for ``jsonb``, an aware UTC datetime for ``timestamptz`` --
so the DAL's call sites need not know the store changed.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import String, Text
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.types import TypeDecorator


def new_id() -> str:
    """A fresh row id, generated client-side because MySQL has no RETURNING."""
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator):
    """``timestamptz`` on a MySQL ``DATETIME(6)`` that holds UTC.

    Binds an aware datetime as naive UTC and reads naive values back as aware
    UTC. A naive datetime bound here is taken to be UTC already.
    """

    impl = DATETIME(fsp=6)
    cache_ok = True

    def process_bind_param(
        self, value: datetime | None, dialect: Any
    ) -> datetime | None:
        if value is None or value.tzinfo is None:
            return value
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(
        self, value: datetime | None, dialect: Any
    ) -> datetime | None:
        if value is None or value.tzinfo is not None:
            return value
        return value.replace(tzinfo=UTC)


class Bounded(TypeDecorator):
    """A ``VARCHAR(length)`` that truncates on write instead of raising.

    For free text on NDB cascade-child tables, which cannot hold TEXT. MySQL in
    strict mode rejects an over-long value with "Data too long", which would
    fail a whole ingest over one verbose description.
    """

    impl = String
    cache_ok = True

    def __init__(self, length: int) -> None:
        super().__init__(length)
        self.max_length = length

    def process_bind_param(self, value: str | None, dialect: Any) -> str | None:
        if value is None or len(value) <= self.max_length:
            return value
        return value[: self.max_length]


class BoundedJSONText(Bounded):
    """A bounded ``VARCHAR`` holding a JSON document as text, kept valid JSON.

    Over-long values are shortened element by element (long strings are cut,
    then trailing list items dropped) rather than by slicing the text, which
    would leave JSON no reader can parse. A value that is not JSON is cut like
    :class:`Bounded`.
    """

    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Any) -> str | None:
        if value is None or len(value) <= self.max_length:
            return value
        try:
            document = json.loads(value)
        except ValueError:
            return value[: self.max_length]
        return _shrink_json(document, self.max_length)


def _shrink_json(document: Any, limit: int) -> str:
    if isinstance(document, dict):
        document = list(document.values()) if not document else document
    for item_cap in (200, 60, 20):
        shortened = _cap_strings(document, item_cap)
        encoded = json.dumps(shortened)
        if len(encoded) <= limit:
            return encoded
    if isinstance(document, list):
        shortened = _cap_strings(document, 20)
        while shortened and len(json.dumps(shortened)) > limit:
            shortened = shortened[:-1]
        return json.dumps(shortened)
    return json.dumps(None)


def _cap_strings(value: Any, cap: int) -> Any:
    if isinstance(value, str):
        return value[:cap]
    if isinstance(value, list):
        return [_cap_strings(item, cap) for item in value]
    if isinstance(value, dict):
        return {key: _cap_strings(item, cap) for key, item in value.items()}
    return value


class JSONList(TypeDecorator):
    """A list of strings stored as JSON text, for what was a Postgres ``text[]``.

    ``length`` makes it a bounded ``VARCHAR`` (for NDB cascade children); a list
    that does not fit then keeps its first items, or with ``keep="last"`` its
    last ones. Without ``length`` it is TEXT. ``None`` stays ``NULL``.
    """

    impl = Text
    cache_ok = True

    def __init__(self, length: int | None = None, keep: str = "first") -> None:
        super().__init__()
        self.max_length = length
        self.keep = keep

    def load_dialect_impl(self, dialect: Any) -> Any:
        if self.max_length is None:
            return dialect.type_descriptor(Text())
        return dialect.type_descriptor(String(self.max_length))

    def process_bind_param(self, value: list[str] | None, dialect: Any) -> str | None:
        if value is None:
            return None
        items = list(value)
        encoded = json.dumps(items)
        if self.max_length is None:
            return encoded
        while len(encoded) > self.max_length and items:
            items = items[1:] if self.keep == "last" else items[:-1]
            encoded = json.dumps(items)
        return encoded

    def process_result_value(self, value: str | None, dialect: Any) -> list[str] | None:
        if value is None:
            return None
        return json.loads(value)


class JSONValue(TypeDecorator):
    """Any JSON value stored as text, for what was ``jsonb``.

    ``length`` makes it a bounded ``VARCHAR`` for NDB cascade children; a value
    that does not fit raises ``ValueError`` rather than being cut into invalid
    JSON. Without ``length`` it is TEXT.
    """

    impl = Text
    cache_ok = True

    def __init__(self, length: int | None = None) -> None:
        super().__init__()
        self.max_length = length

    def load_dialect_impl(self, dialect: Any) -> Any:
        if self.max_length is None:
            return dialect.type_descriptor(Text())
        return dialect.type_descriptor(String(self.max_length))

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        if value is None:
            return None
        encoded = value if isinstance(value, str) else json.dumps(value)
        if self.max_length is not None and len(encoded) > self.max_length:
            raise ValueError(
                f"JSON value of {len(encoded)} characters exceeds the column's {self.max_length}"
            )
        return encoded

    def process_result_value(self, value: str | None, dialect: Any) -> Any:
        if value is None:
            return None
        return json.loads(value)
