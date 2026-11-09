# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# The image is built by Hopsworks docker-images (base-image/ontology-pipeline);
# these targets cover local development only.

NDB := docker compose -f dev_tools/ndb/docker-compose.yml
TEST_ENV := MYSQL_HOST=127.0.0.1 MYSQL_PORT=33306 MYSQL_USER=root MYSQL_PASSWORD=ndbtest MYSQL_DB=ontology AUTO_ONTOLOGY_VDB=memory

.DEFAULT_GOAL := help

help:
	@echo "make ndb-up     Start the local NDB cluster the DAL tests run on"
	@echo "make ndb-down   Stop it and delete its data"
	@echo "make lint       Ruff check and format check"
	@echo "make test       The whole Python suite against the local NDB cluster"
	@echo "make openapi    Regenerate docs/openapi/backend.json"

ndb-up:
	$(NDB) up -d --wait

ndb-down:
	$(NDB) down -v

lint:
	uv run ruff check auto_ontology dev_tools
	uv run ruff format --check auto_ontology dev_tools

test:
	$(TEST_ENV) uv run pytest auto_ontology dev_tools -q

openapi:
	uv run python -m dev_tools.generate_backend_openapi

.PHONY: help ndb-up ndb-down lint test openapi
