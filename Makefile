# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Hopsworks installs this package from git into a clone of the
# python-feature-pipeline environment; these targets cover local development only.

NDB := docker compose -f dev_tools/ndb/docker-compose.yml
PG := postgresql://auto_ontology:auto_ontology@127.0.0.1:55432
TEST_ENV := MYSQL_HOST=127.0.0.1 MYSQL_PORT=33306 MYSQL_USER=root MYSQL_PASSWORD=ndbtest MYSQL_DB=ontology AUTO_ONTOLOGY_VDB=memory \
	POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=55432 POSTGRES_USER=auto_ontology POSTGRES_PASSWORD=auto_ontology POSTGRES_DATABASE=auto_ontology \
	CONNECTION_STRINGS=$(PG)/pagila,sqlite:///$(CURDIR)/dev_tools/fixtures/sql/chinook.sqlite

.DEFAULT_GOAL := help

help:
	@echo "make ndb-up     Start the local NDB cluster the DAL tests run on, and the pagila source"
	@echo "make ndb-down   Stop both and delete their data"
	@echo "make lint       Ruff check and format check"
	@echo "make test       The whole Python suite against the local NDB cluster"
	@echo "make openapi    Regenerate docs/openapi/backend.json"

ndb-up:
	$(NDB) up -d --wait
	docker run -d --name ao-pagila -e POSTGRES_USER=auto_ontology -e POSTGRES_PASSWORD=auto_ontology \
		-e POSTGRES_DB=auto_ontology -p 55432:5432 postgres:17 || docker start ao-pagila
	until docker exec ao-pagila pg_isready -U auto_ontology -d auto_ontology; do sleep 1; done
	$(TEST_ENV) uv run python -m dev_tools.fixtures.seed_fixtures

ndb-down:
	$(NDB) down -v
	docker rm -f ao-pagila

lint:
	uv run ruff check auto_ontology dev_tools
	uv run ruff format --check auto_ontology dev_tools

test:
	$(TEST_ENV) uv run pytest auto_ontology dev_tools -q

openapi:
	uv run python -m dev_tools.generate_backend_openapi

.PHONY: help ndb-up ndb-down lint test openapi
