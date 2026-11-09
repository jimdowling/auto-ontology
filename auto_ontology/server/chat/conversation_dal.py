# SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Persistence and bounded history loading for chat conversations.

A conversation belongs to the Hopsworks member who started it; every read and
write here is scoped by ``user_id`` (a username), and a conversation owned by
someone else reads as absent. Messages have no foreign key to their
conversation (NDB refuses TEXT on cascade children), so deleting a
conversation deletes its messages in the same transaction.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from auto_ontology.dal import schema as s
from auto_ontology.dal.session import store, write_transaction
from auto_ontology.dal.types import new_id, utcnow

logger = logging.getLogger(__name__)

_MAX_HISTORY_TURNS = 5
_MAX_HISTORY_CHARS = 12_000
_MAX_QUESTION_CHARS = 2_000
_MAX_RESPONSE_CHARS = 4_000
_MAX_SQL_CHARS = 6_000

_CONVERSATION_COLUMNS = (
    s.conversations.c.id,
    s.conversations.c.user_id,
    s.conversations.c.title,
    s.conversations.c.created_at,
    s.conversations.c.updated_at,
)
_MESSAGE_COLUMNS = (
    s.messages.c.id,
    s.messages.c.conversation_id,
    s.messages.c.role,
    s.messages.c.content,
    s.messages.c.sql_code,
    s.messages.c.sql_response,
    s.messages.c.created_at,
)


class ConversationAccessError(Exception):
    """Raised when a conversation exists but belongs to another user."""


@dataclass(frozen=True)
class ConversationTurn:
    """One completed user/assistant exchange suitable for LLM context."""

    question: str
    response: str
    sql_code: str | None = None


@dataclass(frozen=True)
class PreparedConversation:
    """Identifiers and prior history created when accepting a chat turn."""

    history: list[ConversationTurn]
    analytics_id: str


def _is_context_assistant(row: dict) -> bool:
    if row["role"] != "assistant" or row["sql_response"] is not None:
        return False
    content = (row["content"] or "").strip()
    if content.startswith("```chart") or content.startswith("```chart-carousel"):
        return False
    if content.startswith("Agent failed:") or content.startswith(
        "Agent stream failed:"
    ):
        return False
    return bool(content or row["sql_code"])


def _rows_to_history(rows: list[dict]) -> list[ConversationTurn]:
    turns: list[ConversationTurn] = []
    pending_question: str | None = None

    for row in rows:
        role = row["role"]
        if role == "user":
            pending_question = (row["content"] or "").strip()
            continue
        if pending_question and _is_context_assistant(row):
            turns.append(
                ConversationTurn(
                    question=pending_question[:_MAX_QUESTION_CHARS],
                    response=(row["content"] or "").strip()[:_MAX_RESPONSE_CHARS],
                    sql_code=(row["sql_code"] or "")[:_MAX_SQL_CHARS] or None,
                )
            )
            pending_question = None

    selected: list[ConversationTurn] = []
    used_chars = 0
    for turn in reversed(turns):
        turn_chars = len(turn.question) + len(turn.response) + len(turn.sql_code or "")
        if selected and used_chars + turn_chars > _MAX_HISTORY_CHARS:
            break
        selected.append(turn)
        used_chars += turn_chars
        if len(selected) >= _MAX_HISTORY_TURNS:
            break
    return list(reversed(selected))


def _owned(conversation_id: str, user_id: str) -> bool:
    return bool(
        store().query_read(
            select(s.conversations.c.id).where(
                s.conversations.c.id == conversation_id,
                s.conversations.c.user_id == user_id,
            )
        )
    )


def _touch(conversation_id: str) -> None:
    store().query_write(
        s.conversations.update()
        .where(s.conversations.c.id == conversation_id)
        .values(updated_at=utcnow())
    )


def prepare_conversation(
    *,
    conversation_id: uuid.UUID,
    user_id: str,
    question: str,
    source: str,
) -> PreparedConversation:
    """Verify/create a conversation, load prior turns, then persist the user turn.

    Raises :class:`ConversationAccessError` when the id names another user's
    conversation.
    """
    conversation_str = str(conversation_id)
    analytics_id = new_id()
    with write_transaction():
        owner = store().query_read(
            select(s.conversations.c.user_id)
            .where(s.conversations.c.id == conversation_str)
            .with_for_update()
        )
        if not owner:
            store().query_write(
                s.conversations.insert().values(
                    id=conversation_str,
                    user_id=user_id,
                    title=question[:50] or "New conversation",
                )
            )
        elif owner[0]["user_id"] != user_id:
            raise ConversationAccessError(conversation_str)

        rows = store().query_read(
            select(
                s.messages.c.role,
                s.messages.c.content,
                s.messages.c.sql_code,
                s.messages.c.sql_response,
            )
            .where(s.messages.c.conversation_id == conversation_str)
            .order_by(s.messages.c.created_at, s.messages.c.id)
        )
        history = _rows_to_history(rows)

        store().query_write(
            s.messages.insert().values(
                conversation_id=conversation_str, role="user", content=question
            )
        )
        store().query_write(
            s.conversation_analytics.insert().values(
                id=analytics_id, user_id=user_id, source=source, question=question
            )
        )
        _touch(conversation_str)

    return PreparedConversation(history=history, analytics_id=analytics_id)


def persist_assistant_result(
    *,
    conversation_id: uuid.UUID,
    user_id: str,
    analytics_id: str,
    response: str,
    sql_code: str | None,
) -> None:
    """Persist one final assistant turn and complete its analytics row."""
    conversation_str = str(conversation_id)
    with write_transaction():
        if not _owned(conversation_str, user_id):
            raise ConversationAccessError(conversation_str)
        store().query_write(
            s.messages.insert().values(
                conversation_id=conversation_str,
                role="assistant",
                content=response,
                sql_code=sql_code,
            )
        )
        _complete_analytics(analytics_id, user_id, response, sql_code)
        _touch(conversation_str)


def persist_result_message(
    *,
    conversation_id: uuid.UUID,
    user_id: str,
    content: str,
    sql_response: str | None,
) -> None:
    """Persist the chart/table bubble ("Message 2") for a completed turn.

    Called unconditionally from ``_pump`` so this bubble is guaranteed to
    exist -- same guarantee ``persist_assistant_result`` already gives the
    SQL answer -- instead of depending on a browser tab staying around to
    ask for it.
    """
    conversation_str = str(conversation_id)
    with write_transaction():
        if not _owned(conversation_str, user_id):
            raise ConversationAccessError(conversation_str)
        store().query_write(
            s.messages.insert().values(
                conversation_id=conversation_str,
                role="assistant",
                content=content,
                sql_response=sql_response,
            )
        )
        _touch(conversation_str)


def _complete_analytics(
    analytics_id: str, user_id: str, response: str, sql_code: str | None
) -> None:
    store().query_write(
        s.conversation_analytics.update()
        .where(
            s.conversation_analytics.c.id == analytics_id,
            s.conversation_analytics.c.user_id == user_id,
        )
        .values(response=response, sql=sql_code, response_timestamp=utcnow())
    )


def create_stateless_analytics(*, user_id: str, question: str, source: str) -> str:
    """Create analytics for an authenticated one-shot request."""
    analytics_id = new_id()
    store().query_write(
        s.conversation_analytics.insert().values(
            id=analytics_id, user_id=user_id, source=source, question=question
        )
    )
    return analytics_id


def persist_analytics_result(
    *,
    analytics_id: str,
    user_id: str,
    response: str,
    sql_code: str | None,
) -> None:
    """Complete an analytics row for a stateless authenticated request."""
    _complete_analytics(analytics_id, user_id, response, sql_code)


def list_conversations(user_id: str) -> list[dict[str, Any]]:
    """The user's conversations, newest first, without messages."""
    return store().query_read(
        select(*_CONVERSATION_COLUMNS)
        .where(s.conversations.c.user_id == user_id)
        .order_by(s.conversations.c.created_at.desc())
    )


def create_conversation(user_id: str, title: str = "") -> dict[str, Any]:
    """Start an empty conversation owned by ``user_id``."""
    conversation_id = new_id()
    with write_transaction():
        store().query_write(
            s.conversations.insert().values(
                id=conversation_id, user_id=user_id, title=title
            )
        )
        return store().query_read(
            select(*_CONVERSATION_COLUMNS).where(
                s.conversations.c.id == conversation_id
            )
        )[0]


def get_conversation(conversation_id: str, user_id: str) -> dict[str, Any] | None:
    """The conversation with its messages oldest first, or ``None`` when the
    user owns no conversation with that id."""
    rows = store().query_read(
        select(*_CONVERSATION_COLUMNS).where(
            s.conversations.c.id == conversation_id,
            s.conversations.c.user_id == user_id,
        )
    )
    if not rows:
        return None
    conversation = dict(rows[0])
    conversation["messages"] = store().query_read(
        select(*_MESSAGE_COLUMNS)
        .where(s.messages.c.conversation_id == conversation_id)
        .order_by(s.messages.c.created_at, s.messages.c.id)
    )
    return conversation


def rename_conversation(
    conversation_id: str, user_id: str, title: str
) -> dict[str, Any] | None:
    """Set the title; ``None`` when the user owns no such conversation."""
    with write_transaction():
        if not _owned(conversation_id, user_id):
            return None
        store().query_write(
            s.conversations.update()
            .where(s.conversations.c.id == conversation_id)
            .values(title=title)
        )
        return store().query_read(
            select(*_CONVERSATION_COLUMNS).where(
                s.conversations.c.id == conversation_id
            )
        )[0]


def delete_conversation(conversation_id: str, user_id: str) -> bool:
    """Delete the conversation and its messages; ``False`` when not owned."""
    with write_transaction():
        if not _owned(conversation_id, user_id):
            return False
        store().query_write(
            s.messages.delete().where(s.messages.c.conversation_id == conversation_id)
        )
        store().query_write(
            s.conversations.delete().where(s.conversations.c.id == conversation_id)
        )
        return True


def add_message(
    conversation_id: str,
    user_id: str,
    *,
    role: str,
    content: str = "",
    sql_code: str | None = None,
    sql_response: str | None = None,
) -> dict[str, Any] | None:
    """Append a message; ``None`` when the user owns no such conversation."""
    message_id = new_id()
    with write_transaction():
        if not _owned(conversation_id, user_id):
            return None
        store().query_write(
            s.messages.insert().values(
                id=message_id,
                conversation_id=conversation_id,
                role=role,
                content=content,
                sql_code=sql_code,
                sql_response=sql_response,
            )
        )
        _touch(conversation_id)
        return store().query_read(
            select(*_MESSAGE_COLUMNS).where(s.messages.c.id == message_id)
        )[0]


def conversation_owner(conversation_id: str) -> str | None:
    """The username owning the conversation, or ``None`` when it does not exist."""
    rows = store().query_read(
        select(s.conversations.c.user_id).where(s.conversations.c.id == conversation_id)
    )
    return rows[0]["user_id"] if rows else None


__all__ = [
    "ConversationAccessError",
    "ConversationTurn",
    "PreparedConversation",
    "add_message",
    "conversation_owner",
    "create_conversation",
    "create_stateless_analytics",
    "delete_conversation",
    "get_conversation",
    "list_conversations",
    "persist_analytics_result",
    "persist_assistant_result",
    "persist_result_message",
    "prepare_conversation",
    "rename_conversation",
]
