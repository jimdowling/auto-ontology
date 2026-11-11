<!--
SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

@AGENTS.md

## Frontend Rules

- **Formatting**: Prettier. **After editing ANY frontend file, ALWAYS run `pnpm format` (or `cd frontend && npx prettier --write <file>`) to auto-format it.** Never rely on manual formatting: let Prettier handle it. CI will reject unformatted code.
- **Linting**: ESLint. Fix all lint errors; do not disable rules without a comment explaining why.
- **Checks**: `pnpm typecheck`, `pnpm lint`, `pnpm test` and `pnpm build` must pass.
- **Components**: Arrow function components. No class components.
- **Styling**: Tailwind CSS 4. Do not write inline styles or separate CSS files for component styling. The accent color is the `accent` theme token in `styles/globals.css`.
- **Types**: TypeScript strict mode. No `any` without a comment. Types go in `/frontend/types`, enums in `/frontend/enums`.
- **API layer**: Use the `requests` wrapper from `frontend/api/requests.ts`; do not call axios directly. Base URL and error handling are already centralised there.
