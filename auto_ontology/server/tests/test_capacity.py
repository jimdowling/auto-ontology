# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The per-pod cap on concurrent agent runs."""

from __future__ import annotations

import threading

import pytest
from fastapi import HTTPException

from auto_ontology.server import capacity


def test_a_run_beyond_the_cap_gets_429_until_one_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(capacity, "_runs", threading.BoundedSemaphore(2))
    capacity.acquire()
    capacity.acquire()
    with pytest.raises(HTTPException) as exc_info:
        capacity.acquire()
    assert exc_info.value.status_code == 429
    assert exc_info.value.headers["Retry-After"]
    capacity.release()
    with capacity.run_slot():
        pass
    capacity.release()


def test_a_failed_run_gives_its_slot_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(capacity, "_runs", threading.BoundedSemaphore(1))
    with pytest.raises(RuntimeError), capacity.run_slot():
        raise RuntimeError("model serving down")
    with capacity.run_slot():
        pass
