<!--
SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Ontology web UI

A Vite + React single-page app. `pnpm build` writes it to `../auto_ontology/server/static/`, which the FastAPI app serves at `/`. In Hopsworks the app runs behind the app proxy at `/hopsworks-api/pythonapp/<project>/<app>/` and is shown in an iframe, which fixes three rules:

- **Routing** is `react-router` with a hash router (`routes.tsx`). The proxy only forwards to the app, so there are no server routes to deep-link to.
- **HTTP calls** go to relative `api/...` URLs, never `/api/...`: the proxy does not rewrite URLs inside JavaScript. `api/requests.ts` sets `baseURL: 'api'`.
- **Assets** are relative (`base: './'` in `vite.config.ts`). Reference files in `public/` through `import.meta.env.BASE_URL`.

There is no login. Hopsworks signs the caller's identity into every request, and `GET api/me` returns `{username, role, permissions}`. `hooks/useMe.ts` reads it; gate UI with `useMe().can(Permission.X)` or `isAdmin`. The backend enforces every check again.
