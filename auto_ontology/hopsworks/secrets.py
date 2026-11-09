# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Hopsworks secrets, read as the process's own Hopsworks identity."""

from __future__ import annotations

from auto_ontology.hopsworks.client import login


def read_secret(name: str) -> str:
    """The value of the caller's private secret ``name``.

    Raises whatever the hopsworks client raises when the secret does not exist
    or the identity cannot read it.
    """
    login()
    import hopsworks

    return hopsworks.get_secrets_api().get(name)
