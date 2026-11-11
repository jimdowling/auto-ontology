# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Conversation persistence and ownership, on the test store."""

from __future__ import annotations

import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("MYSQL_USER"), reason="MYSQL_* not set"
)


def test_a_turn_creates_the_conversation_and_loads_its_history() -> None:
    from auto_ontology.server.chat import conversation_dal as dal

    conversation_id = uuid.uuid4()
    first = dal.prepare_conversation(
        conversation_id=conversation_id,
        user_id="alice",
        question="How many orders?",
        source="app",
    )
    assert first.history == []
    dal.persist_assistant_result(
        conversation_id=conversation_id,
        user_id="alice",
        analytics_id=first.analytics_id,
        response="12",
        sql_code="SELECT COUNT(*) FROM orders",
    )
    second = dal.prepare_conversation(
        conversation_id=conversation_id,
        user_id="alice",
        question="And last week?",
        source="app",
    )
    assert [turn.response for turn in second.history] == ["12"]


def test_another_user_cannot_use_or_see_the_conversation() -> None:
    from auto_ontology.server.chat import conversation_dal as dal

    conversation_id = uuid.uuid4()
    dal.prepare_conversation(
        conversation_id=conversation_id, user_id="alice", question="q", source="app"
    )
    with pytest.raises(dal.ConversationAccessError):
        dal.prepare_conversation(
            conversation_id=conversation_id, user_id="bob", question="q", source="app"
        )
    assert dal.get_conversation(str(conversation_id), "bob") is None
    assert dal.rename_conversation(str(conversation_id), "bob", "mine now") is None
    assert not dal.delete_conversation(str(conversation_id), "bob")


def test_deleting_a_conversation_deletes_its_messages() -> None:
    from sqlalchemy import func, select

    from auto_ontology.dal import schema as s
    from auto_ontology.dal.session import store
    from auto_ontology.server.chat import conversation_dal as dal

    created = dal.create_conversation("carol", "Revenue")
    assert dal.add_message(
        created["id"], "carol", role="user", content="Revenue in June?"
    )
    assert (
        dal.get_conversation(created["id"], "carol")["messages"][0]["content"]
        == "Revenue in June?"
    )
    assert dal.delete_conversation(created["id"], "carol")
    remaining = store().query_read(
        select(func.count().label("n"))
        .select_from(s.messages)
        .where(s.messages.c.conversation_id == created["id"])
    )
    assert remaining[0]["n"] == 0
