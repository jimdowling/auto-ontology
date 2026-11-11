# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Settings, acronyms, custom prompts and analytics.

Upstream these routes lived in the Next.js gateway over Prisma; the paths and
response shapes are the same, so the UI is unchanged. Permissions come from
``route_permissions.json`` (see :mod:`auto_ontology.server.authz`).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field, StrictBool

from auto_ontology.dal import settings as dal
from auto_ontology.dal.types import utcnow
from auto_ontology.ingestion_service.config import SEMANTIC_COMPILATION_ENABLED_KEY
from auto_ontology.infra.feature_flags import (
    DISTINCT_VALUE_PROBING_ENABLED_KEY,
    MAX_SQL_QUERY_TIMEOUT_SECONDS,
    MIN_SQL_QUERY_TIMEOUT_SECONDS,
    PII_DETECTION_ENABLED_KEY,
    SQL_QUERY_TIMEOUT_SECONDS_KEY,
    get_sql_query_timeout_seconds,
    is_distinct_value_probing_enabled,
    is_pii_detection_enabled,
    read_configuration_flag,
)

router = APIRouter()

VISUALIZATION_ENABLED_KEY = "visualization_enabled"
ANALYTICS_DAYS = 30


class Toggle(BaseModel):
    enabled: StrictBool


class Timeout(BaseModel):
    seconds: int = Field(
        ge=MIN_SQL_QUERY_TIMEOUT_SECONDS, le=MAX_SQL_QUERY_TIMEOUT_SECONDS
    )


class AcronymCreate(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""


class AcronymUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class PromptBody(BaseModel):
    content: str = ""


def _flag(key: str, enabled: bool) -> dict[str, bool]:
    dal.set_configuration(key, "true" if enabled else "false")
    return {"enabled": enabled}


@router.get("/configurations/visualization")
def get_visualization() -> dict[str, bool]:
    """Whether charts are generated for chat answers; on unless switched off."""
    return {"enabled": read_configuration_flag(VISUALIZATION_ENABLED_KEY, default=True)}


@router.put("/configurations/visualization")
def put_visualization(body: Toggle) -> dict[str, bool]:
    return _flag(VISUALIZATION_ENABLED_KEY, body.enabled)


@router.get("/configurations/pii-detection")
def get_pii_detection() -> dict[str, bool]:
    """Whether ingest classifies columns as PII; off unless switched on."""
    return {"enabled": is_pii_detection_enabled()}


@router.put("/configurations/pii-detection")
def put_pii_detection(body: Toggle) -> dict[str, bool]:
    return _flag(PII_DETECTION_ENABLED_KEY, body.enabled)


@router.get("/configurations/distinct-value-probing")
def get_distinct_value_probing() -> dict[str, bool]:
    """Whether compilation may run DISTINCT probes on source columns; on unless switched off."""
    return {"enabled": is_distinct_value_probing_enabled()}


@router.put("/configurations/distinct-value-probing")
def put_distinct_value_probing(body: Toggle) -> dict[str, bool]:
    return _flag(DISTINCT_VALUE_PROBING_ENABLED_KEY, body.enabled)


@router.get("/configurations/semantic-compilation")
def get_semantic_compilation() -> dict[str, bool]:
    """Whether the scheduled compile job compiles; off until switched on."""
    return {
        "enabled": dal.get_configuration(SEMANTIC_COMPILATION_ENABLED_KEY) == "true"
    }


@router.put("/configurations/semantic-compilation")
def put_semantic_compilation(body: Toggle) -> dict[str, bool]:
    """Switch compilation on or off; switching it on starts a compile run now."""
    result = _flag(SEMANTIC_COMPILATION_ENABLED_KEY, body.enabled)
    if body.enabled:
        from auto_ontology.hopsworks.jobs import start_pipeline_job

        start_pipeline_job("compile")
    return result


@router.get("/configurations/sql-query-timeout")
def get_sql_query_timeout() -> dict[str, int]:
    """Seconds one agent-issued SQL statement may run."""
    return {"seconds": get_sql_query_timeout_seconds()}


@router.put("/configurations/sql-query-timeout")
def put_sql_query_timeout(body: Timeout) -> dict[str, int]:
    dal.set_configuration(SQL_QUERY_TIMEOUT_SECONDS_KEY, str(body.seconds))
    return {"seconds": body.seconds}


@router.get("/acronyms")
def list_acronyms(name: str | None = None) -> Any:
    """Every acronym, newest first; with ``name``, whether that acronym exists."""
    if name and name.strip():
        return {"exists": dal.find_acronym(name.strip()) is not None}
    return dal.list_acronyms(newest_first=True)


@router.post("/acronyms", status_code=201)
def create_acronym(body: AcronymCreate) -> dict[str, Any]:
    if dal.find_acronym(body.name) is not None:
        raise HTTPException(
            status_code=409, detail=f"Acronym {body.name!r} already exists"
        )
    return dal.create_acronym(body.name, body.description)


@router.patch("/acronyms/{acronym_id}")
def update_acronym(acronym_id: str, body: AcronymUpdate) -> dict[str, Any]:
    values = body.model_dump(exclude_none=True)
    acronym = dal.update_acronym(acronym_id, **values) if values else None
    if acronym is None:
        raise HTTPException(status_code=404, detail="Acronym not found")
    return acronym


@router.delete("/acronyms/{acronym_id}", status_code=204)
def delete_acronym(acronym_id: str) -> Response:
    if not dal.delete_acronym(acronym_id):
        raise HTTPException(status_code=404, detail="Acronym not found")
    return Response(status_code=204)


@router.get("/custom-prompts")
def list_prompts() -> list[dict[str, Any]]:
    return dal.list_prompts()


@router.post("/custom-prompts", status_code=201)
def create_prompt(body: PromptBody) -> dict[str, Any]:
    return dal.create_prompt(body.content)


@router.get("/custom-prompts/{prompt_id}")
def get_prompt(prompt_id: str) -> dict[str, Any]:
    prompt = dal.get_prompt(prompt_id)
    if prompt is None:
        raise HTTPException(status_code=404, detail="Custom prompt not found")
    return prompt


@router.patch("/custom-prompts/{prompt_id}")
def update_prompt(prompt_id: str, body: PromptBody) -> dict[str, Any]:
    prompt = dal.update_prompt(prompt_id, body.content)
    if prompt is None:
        raise HTTPException(status_code=404, detail="Custom prompt not found")
    return prompt


@router.delete("/custom-prompts/{prompt_id}", status_code=204)
def delete_prompt(prompt_id: str) -> Response:
    if not dal.delete_prompt(prompt_id):
        raise HTTPException(status_code=404, detail="Custom prompt not found")
    return Response(status_code=204)


@router.get("/analytics")
def analytics(
    skip: int = Query(0, ge=0), limit: int | None = Query(None, ge=0)
) -> dict[str, Any]:
    """Questions asked in the last 30 days, newest first, with who asked them."""
    rows, total = dal.list_analytics(
        utcnow() - timedelta(days=ANALYTICS_DAYS), skip, limit
    )
    return {
        "data": [{**row, "username": row["user_id"]} for row in rows],
        "total": total,
    }
