# SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Env-derived connection config for the store: RonDB through the MySQL protocol.

A Hopsworks app gets ``MYSQL_HOST``, ``MYSQL_PORT``, ``MYSQL_USER``,
``MYSQL_DB`` and ``MYSQL_PASSWORD_SECRET_NAME`` from the platform; its password
is the starter's private secret of that name. A job gets the same variables
from :mod:`auto_ontology.hopsworks.launch`, which reads them off the member's
online storage connector. Tests and local runs set ``MYSQL_PASSWORD`` directly.
"""

from __future__ import annotations

import os
from functools import cache

from sqlalchemy.engine import URL


@cache
def _password() -> str:
    password = os.environ.get("MYSQL_PASSWORD")
    if password is not None:
        return password
    secret_name = os.environ.get("MYSQL_PASSWORD_SECRET_NAME")
    if not secret_name:
        raise RuntimeError(
            "Neither MYSQL_PASSWORD nor MYSQL_PASSWORD_SECRET_NAME is set"
        )
    from auto_ontology.hopsworks.secrets import read_secret

    return read_secret(secret_name)


def mysql_url(database: str | None = None) -> URL:
    """The store URL, on the PyMySQL driver.

    ``database`` overrides ``MYSQL_DB`` when given. Raises ``RuntimeError`` when
    no password source is configured.
    """
    return URL.create(
        "mysql+pymysql",
        username=os.environ["MYSQL_USER"],
        password=_password(),
        host=os.environ.get("MYSQL_HOST", "localhost"),
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        database=database or os.environ["MYSQL_DB"],
        query={"charset": "utf8mb4"},
    )


def store_configured() -> bool:
    """Whether the environment names a store at all, for code that can run without one."""
    return bool(os.environ.get("MYSQL_USER") and os.environ.get("MYSQL_DB"))
