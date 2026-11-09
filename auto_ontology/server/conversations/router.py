# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The caller's own chat conversations.

Upstream served these from the Next.js gateway; the paths and shapes are the
same. A conversation is visible only to the member who owns it, and one owned
by somebody else answers 404, as if it did not exist.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from auto_ontology.hopsworks.identity import Caller
from auto_ontology.server.authz import current_caller
from auto_ontology.server.chat import conversation_dal as dal

router = APIRouter()


class ConversationCreate(BaseModel):
    title: str | None = None


class ConversationUpdate(BaseModel):
    title: str


class MessageCreate(BaseModel):
    role: str
    content: str | None = None
    sql_code: str | None = None
    sql_response: str | None = None


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Conversation not found")


@router.get("/conversations")
def list_conversations(
    caller: Caller = Depends(current_caller),
) -> list[dict[str, Any]]:
    return dal.list_conversations(caller.username)


@router.post("/conversations", status_code=201)
def create_conversation(
    body: ConversationCreate, caller: Caller = Depends(current_caller)
) -> dict[str, Any]:
    return dal.create_conversation(caller.username, body.title or "")


@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: str, caller: Caller = Depends(current_caller)
) -> dict[str, Any]:
    conversation = dal.get_conversation(conversation_id, caller.username)
    if conversation is None:
        raise _not_found()
    return conversation


@router.patch("/conversations/{conversation_id}")
def rename_conversation(
    conversation_id: str,
    body: ConversationUpdate,
    caller: Caller = Depends(current_caller),
) -> dict[str, Any]:
    conversation = dal.rename_conversation(conversation_id, caller.username, body.title)
    if conversation is None:
        raise _not_found()
    return conversation


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: str, caller: Caller = Depends(current_caller)
) -> Response:
    if not dal.delete_conversation(conversation_id, caller.username):
        raise _not_found()
    return Response(status_code=204)


@router.post("/conversations/{conversation_id}/messages", status_code=201)
def add_message(
    conversation_id: str, body: MessageCreate, caller: Caller = Depends(current_caller)
) -> dict[str, Any]:
    message = dal.add_message(
        conversation_id,
        caller.username,
        role=body.role,
        content=body.content or "",
        sql_code=body.sql_code,
        sql_response=body.sql_response,
    )
    if message is None:
        raise _not_found()
    return message
