<!--
SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Auto-Ontology

Hopsworks fork of NVIDIA Auto-Ontology: a Vite SPA (`/frontend`) served by the
FastAPI app (`/auto_ontology`), which runs as a Hopsworks Python app, with the
pipeline steps as Hopsworks jobs (`auto_ontology/jobs`). The store is RonDB.

This file is for **Auto-Ontology maintainers**. User/partner agent skills live in
`skills/` — start at [`AGENTS.md`](./AGENTS.md).

## Dev Commands

Backend commands run from the repo root:

| Command | Description |
|---|---|
| `uv run uvicorn auto_ontology.server.__main__:create_app --factory --reload --host 127.0.0.1 --port 3001` | Start FastAPI on :3001 with hot reload |
| `uv run python -m auto_ontology.server` | Start FastAPI on :3001 without reload (what the container runs) |
| `make ndb-up` | Start the local MySQL NDB Cluster the DAL tests run on (port 33306) |
| `make test` | The Python suite against it |

The app factory is `create_app()` in `auto_ontology/server/__main__.py` — there is no
`auto_ontology/server/main.py`.

## Frontend Rules

In [`frontend/CLAUDE.md`](./frontend/CLAUDE.md), loaded when working under `frontend/`.

## Backend Rules

- **The store is RonDB (MySQL NDB Cluster).** `auto_ontology/dal/` queries it with SQLAlchemy Core (no ORM); `auto_ontology/dal/schema.py` is the single source of truth for the schema and `auto_ontology/dal/session.py` owns the pooled engine. On Hopsworks the app creates its tables through the app-tables API (`app.create_table`/`alter_table`), driven by the ordered steps in `auto_ontology/dal/migrations.py`: a schema change is a new step appended there, never an edit to an applied one. NDB refuses TEXT/BLOB on cascade children, caps a row near 14 KB and a transaction at 32,768 rows, and runs READ COMMITTED; read the comments in `schema.py` and use the helpers in `dal/ops.py` (`insert_returning`, `upsert`, `chunks`) before changing a table or a write path.
- **Identity.** Every request carries the Hopsworks proxy's HMAC-signed `X-Hopsworks-User` headers; `server/authz.py` verifies them and maps the member's project role to `admin`/`editor`/`reader`. Route permissions live in `server/route_permissions.json` (regenerate with `uv run python -m dev_tools.generate_route_permissions`); an unlisted route is admin-only.
- **Formatting/Linting**: Run `uv run ruff check auto_ontology/` and `uv run ruff format auto_ontology/` from repo root before committing.
- **Dependencies**: Managed with `uv`. Add dependencies via `uv add`, not pip. Do not edit `pyproject.toml` manually for deps.
- **API prefix**: All routes under `/api/`, one router per package under `auto_ontology/server/`.
- **Type hints**: Required on all function signatures.
- **Exception handlers**: Use plain `def` (not `async def`) for `@app.exception_handler` functions. They perform no async I/O, so synchronous handlers are preferred.

## Git

- Work happens on a branch named after the Hopsworks JIRA ticket, following the Hopsworks workspace commit convention.

### Opening a PR

**A PR is not done until every GitHub Actions workflow passes.** After opening
one, poll `gh pr checks <number>` until no check is pending, then fix whatever
failed and push again — repeat until the run is green. Report the final state
honestly; do not hand back a PR with unexamined or failing checks.

Run these locally first — they are the same gates CI applies, and catching a
failure here costs seconds instead of a CI round-trip:

| Check | Command | Catches |
|---|---|---|
| Ruff | `uv run ruff check auto_ontology/ && uv run ruff format --check auto_ontology/` | Backend lint/format |
| Pytest | `make ndb-up && make test` | Backend tests |
| OpenAPI | `uv run python -m dev_tools.generate_backend_openapi` | **Stale `docs/openapi/*.json`** |
| Frontend | `cd frontend && npx prettier --check . && pnpm lint && pnpm build` | Format, lint, build |

The OpenAPI one is the easy one to miss: `docs/openapi/backend.json` is
committed, and the spec embeds each route's **docstring**.
Editing a docstring on any `@router` handler — not just changing a signature or
model — makes the committed spec stale and fails "Backend spec is up to date".
Regenerate and commit the result whenever a route's code or docs change.
