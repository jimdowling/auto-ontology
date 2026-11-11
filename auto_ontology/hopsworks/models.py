# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Model endpoints for this process, from ``ontology.yaml``.

Auto Ontology reads its models from ``<ROLE>_ENDPOINT``/``_API_KEY``/``_MODEL``
environment triplets (:mod:`auto_ontology.utils.model_config`), at import time.
:func:`configure` sets them before anything imports the model clients:

* local mode: the project's vLLM deployments, addressed by deployment name,
  authenticated with the process's Hopsworks serving token as both the bearer
  key and an ``ApiKey`` header, over TLS signed by the cluster CA;
* external mode: the endpoint in the member's account variables
  (``LLM_URL``/``LLM_MODEL``/``LLM_API_KEY``, ``EMBEDDING_URL``/...).

Thinking stays on for SQL generation (``REASONING``) and is switched off for
the agent's lighter steps (``NON_REASONING``).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from auto_ontology.hopsworks.config import ModelConfig, OntologyConfig

LLM_ROLES = ("REASONING", "NON_REASONING")


class ModelConfigError(RuntimeError):
    """A model endpoint ``ontology.yaml`` asks for is not available."""


def _deployment_endpoint(name: str) -> tuple[str, str]:
    from auto_ontology.hopsworks.client import login

    deployment = login().get_model_serving().get_deployment(name)
    if deployment is None:
        raise ModelConfigError(f"deployment {name!r} does not exist in this project")
    client = deployment.get_openai_client()
    return str(client.base_url), client.api_key


def _ca_bundle() -> str | None:
    """A CA bundle of the public roots plus the cluster CA, for in-cluster TLS.

    ``SSL_CERT_FILE`` replaces the default trust store, so the cluster CA alone
    would break every external call the process makes.
    """
    from hopsworks_common import client

    verify = getattr(client._get_instance(), "_verify", True)
    if not isinstance(verify, str) or not Path(verify).is_file():
        return None
    import certifi

    bundle = Path(os.environ.get("TMPDIR", "/tmp")) / "ontology-ca-bundle.pem"
    bundle.write_text(
        Path(certifi.where()).read_text() + "\n" + Path(verify).read_text()
    )
    return str(bundle)


def _set(
    role: str, *, endpoint: str, api_key: str, model: str, headers: dict[str, str]
) -> None:
    os.environ[f"{role}_ENDPOINT"] = endpoint
    os.environ[f"{role}_API_KEY"] = api_key
    os.environ[f"{role}_MODEL"] = model
    os.environ[f"{role}_PROVIDER"] = "openai"
    os.environ[f"{role}_HEADERS"] = json.dumps(headers)


def _resolve(config: ModelConfig, prefix: str) -> tuple[str, str, str, dict[str, str]]:
    if config.mode == "local":
        if not config.deployment:
            raise ModelConfigError(
                f"{prefix.lower()} mode is local but no deployment is named"
            )
        endpoint, token = _deployment_endpoint(config.deployment)
        return endpoint, token, config.deployment, {"Authorization": f"ApiKey {token}"}
    endpoint = os.environ.get(f"{prefix}_URL")
    api_key = os.environ.get(f"{prefix}_API_KEY")
    model = os.environ.get(f"{prefix}_MODEL") or config.model
    if not endpoint or not model:
        raise ModelConfigError(
            f"{prefix.lower()} mode is external but {prefix}_URL or {prefix}_MODEL is not set"
        )
    return endpoint, api_key or "", model, {}


def configure(config: OntologyConfig) -> dict[str, Any]:
    """Set the model environment for this process; returns what was chosen, minus keys.

    Raises :class:`ModelConfigError` when a configured deployment is missing or
    an external endpoint is not set.
    """
    endpoint, api_key, model, headers = _resolve(config.llm, "LLM")
    for role in LLM_ROLES:
        _set(role, endpoint=endpoint, api_key=api_key, model=model, headers=headers)
    os.environ["NON_REASONING_THINKING"] = "false"

    embed_endpoint, embed_key, embed_model, embed_headers = _resolve(
        config.embedding, "EMBEDDING"
    )
    _set(
        "EMBED",
        endpoint=embed_endpoint,
        api_key=embed_key,
        model=embed_model,
        headers=embed_headers,
    )
    os.environ["EMBED_TEXT_PREFIX"] = (
        "true" if config.embedding.request == "v1-prefix" else "false"
    )

    if "local" in (config.llm.mode, config.embedding.mode):
        bundle = _ca_bundle()
        if bundle:
            os.environ["SSL_CERT_FILE"] = bundle
            os.environ["REQUESTS_CA_BUNDLE"] = bundle
    return {
        "llm": {"mode": config.llm.mode, "endpoint": endpoint, "model": model},
        "embedding": {
            "mode": config.embedding.mode,
            "endpoint": embed_endpoint,
            "model": embed_model,
        },
    }
