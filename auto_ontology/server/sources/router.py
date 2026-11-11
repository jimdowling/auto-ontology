# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The ontology's sources: Hopsworks data sources with SHARED credentials.

Adding a source connects to it once and starts the ingest job for it; removing
one starts the reset job that deletes its catalog, semantic layer and vectors.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from auto_ontology.connectors import sources
from auto_ontology.server.ingestion import proxy

router = APIRouter()


class SourceBody(BaseModel):
    name: str = Field(min_length=1, description="The project data source's name")
    schemas: list[str] | None = None
    table_regex: str | None = None


@router.get("/sources")
def list_sources() -> list[dict[str, Any]]:
    """Every source, with the catalog database name its tables are filed under."""
    return sources.list_sources()


@router.post("/sources", status_code=201)
def add_source(body: SourceBody) -> dict[str, Any]:
    """Add a data source, or change its filters, and start ingesting it.

    Returns 422 when the data source is unsupported, uses per-user credentials,
    or reads a database another source already reads, and 502 when it cannot
    be reached.
    """
    try:
        source = sources.add_source(body.name, body.schemas, body.table_regex)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Could not connect to {body.name!r}: {exc}"
        ) from exc
    proxy.trigger_ingest({"data_source": source["name"]})
    return source


@router.delete("/sources/{name}", status_code=204)
def remove_source(name: str) -> Response:
    """Stop reading a data source and delete what was ingested from it."""
    database_name = sources.remove_source(name)
    if database_name is None:
        raise HTTPException(status_code=404, detail="Source not found")
    proxy.trigger_reset(database_name)
    return Response(status_code=204)
