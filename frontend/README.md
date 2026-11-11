<!--
SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Ontology web UI

A Vite + React single-page app served by the FastAPI app in `auto_ontology/server/`.

## Develop

Start the backend on port 3001 from the repo root (see the root `CLAUDE.md`), then:

```bash
pnpm install
pnpm dev
```

Open http://localhost:3000. The dev server proxies `/api` to http://127.0.0.1:3001.

## Build

```bash
pnpm build
```

The output goes to `../auto_ontology/server/static/`, which is git-ignored and packaged with the Python wheel.

## Check

```bash
pnpm typecheck
pnpm lint
pnpm test
pnpm format:check
```
