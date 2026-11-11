# SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""FastAPI application entry-point — middleware, routers, lifespan."""

from __future__ import annotations

from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles
import uvicorn
from auto_ontology.env import load_env

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

load_env()

logger = logging.getLogger(__name__)

from auto_ontology.version import get_app_version  # noqa: E402
from auto_ontology.dal import close_store  # noqa: E402
from auto_ontology.dal.schema_version import require_current_schema  # noqa: E402
from auto_ontology.server.chat.router import router as chat_router  # noqa: E402
from auto_ontology.server.chat.worker import get_pool, shutdown_pool  # noqa: E402
from auto_ontology.server.authz import IdentityMiddleware, authorize  # noqa: E402
from auto_ontology.server.conversations.router import router as conversations_router  # noqa: E402
from auto_ontology.server.settings.router import router as settings_router  # noqa: E402
from auto_ontology.server.datasources.router import router as datasources_router  # noqa: E402
from auto_ontology.server.exploration.router import router as exploration_router  # noqa: E402
from auto_ontology.server.health.router import router as health_router  # noqa: E402
from auto_ontology.server.metadata.router import router as metadata_router  # noqa: E402
from auto_ontology.server.rules.router import router as rules_router  # noqa: E402
from auto_ontology.server.semantic_compilation.router import (  # noqa: E402
    router as semantic_compilation_router,
)
from auto_ontology.server.sql_attributes.router import router as sql_attributes_router  # noqa: E402
from auto_ontology.server.users.router import router as users_router  # noqa: E402
from auto_ontology.server.tags.router import router as tags_router  # noqa: E402
from auto_ontology.server.terms.router import router as terms_router  # noqa: E402
from auto_ontology.server.model_interchange.router import (  # noqa: E402
    router as model_interchange_router,
)
from auto_ontology.server.search.router import router as search_router  # noqa: E402
from auto_ontology.server.sources.router import router as sources_router  # noqa: E402


STATIC_DIR = Path(__file__).resolve().parent / "static"


def _prepare_store_on_hopsworks() -> None:
    """When launched as a Hopsworks app: apply pending schema steps through the
    app-tables API (the app is the store's one migrator, see dal.migrations),
    then store ``ontology.yaml``'s switches that Settings has never set."""
    from auto_ontology.hopsworks.launch import app_handle

    handle = app_handle()
    if handle is None:
        require_current_schema()
        return
    from auto_ontology.dal.migrations import AppTablesDDL, migrate
    from auto_ontology.hopsworks.config import load
    from auto_ontology.infra.feature_flags import seed_from_config

    applied = migrate(AppTablesDDL(handle))
    if applied:
        logger.info("Applied %d schema step(s): %s", len(applied), ", ".join(applied))
    require_current_schema()
    seeded = seed_from_config(load())
    if seeded:
        logger.info("Settings from ontology.yaml: %s", ", ".join(seeded))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Here rather than in `create_app`: the OpenAPI spec generator builds the
    # app with no database at all, and the lifespan runs only when it is served.
    _prepare_store_on_hopsworks()

    # Kick off the chat worker pool's initial warm spawn at boot. The pool
    # itself is lazy on first use, but eagerly initialising here means the
    # very first chat request doesn't pay a cold start.
    get_pool()
    try:
        yield
    finally:
        # Tear down warm subprocesses before exiting so we don't leak them.
        shutdown_pool()
        close_store()


def create_app() -> FastAPI:
    """Build the API app without serving it.

    Kept separate from ``main`` so tooling — the OpenAPI spec generator,
    tests — can construct the app and read ``app.openapi()`` without
    starting uvicorn.
    """
    app = FastAPI(
        title="Auto Ontology API",
        lifespan=lifespan,
        dependencies=[Depends(authorize)],
    )
    app.add_middleware(IdentityMiddleware)

    @app.get("/health", include_in_schema=False)
    def readiness() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(
        datasources_router, prefix="/api", tags=["datasources", "connectors"]
    )
    app.include_router(exploration_router, prefix="/api", tags=["exploration"])
    app.include_router(chat_router, prefix="/api", tags=["chat"])
    app.include_router(conversations_router, prefix="/api", tags=["conversations"])
    app.include_router(metadata_router, prefix="/api", tags=["metadata"])
    app.include_router(health_router, prefix="/api", tags=["health"])
    app.include_router(sql_attributes_router, prefix="/api", tags=["sql-attributes"])
    app.include_router(
        semantic_compilation_router, prefix="/api", tags=["semantic-compilation"]
    )
    app.include_router(settings_router, prefix="/api", tags=["settings"])
    app.include_router(users_router, prefix="/api", tags=["users"])
    app.include_router(tags_router, prefix="/api", tags=["tags"])
    app.include_router(rules_router, prefix="/api", tags=["rules"])
    app.include_router(terms_router, prefix="/api", tags=["terms"])
    app.include_router(
        model_interchange_router, prefix="/api", tags=["model-interchange"]
    )
    app.include_router(search_router, prefix="/api", tags=["search"])
    app.include_router(sources_router, prefix="/api", tags=["sources"])

    # Last, so every API route matches before the UI's catch-all mount. The
    # directory exists in the image (the Vite build writes it), not in a
    # source checkout that never built the UI.
    if STATIC_DIR.is_dir():
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="ui")

    return app


def main(port: int = 3001) -> None:
    logger.info("Starting Auto Ontology API server — app version %s", get_app_version())

    app = create_app()

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_config=None,
    )


if __name__ == "__main__":
    main()
