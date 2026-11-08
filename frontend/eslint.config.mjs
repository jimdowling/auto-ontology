// SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import js from '@eslint/js';
import reactHooks from 'eslint-plugin-react-hooks';
import { defineConfig, globalIgnores } from 'eslint/config';
import globals from 'globals';
import tseslint from 'typescript-eslint';

export default defineConfig([
	globalIgnores(['node_modules/**', 'coverage/**', '.cache/**']),
	js.configs.recommended,
	...tseslint.configs.recommended,
	reactHooks.configs.flat.recommended,
	{
		languageOptions: {
			ecmaVersion: 2022,
			globals: { ...globals.browser },
		},
	},
	{
		files: ['vite.config.ts', 'eslint.config.mjs'],
		languageOptions: { globals: { ...globals.node } },
	},
]);
