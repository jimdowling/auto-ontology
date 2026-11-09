# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The caller's name, for routers that record who did something.

The name is the Hopsworks username that :class:`auto_ontology.server.authz.IdentityMiddleware`
verified from the app proxy's signature.
"""

from __future__ import annotations

from fastapi import HTTPException, Request


def resolve_internal_user(request: Request, *, required: bool) -> str | None:
    """The verified caller's username.

    ``None`` when the request carries no verified caller and ``required`` is
    False; raises 401 when ``required`` is True.
    """
    caller = getattr(request.state, "caller", None)
    if caller is not None:
        return caller.username
    if required:
        raise HTTPException(
            status_code=401, detail="Authenticated conversation required"
        )
    return None


__all__ = ["resolve_internal_user"]
