// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { fileURLToPath } from 'node:url';
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import svgr from 'vite-plugin-svgr';
import { defineConfig } from 'vitest/config';

const root = fileURLToPath(new URL('.', import.meta.url));

export default defineConfig({
	// Relative asset URLs: the app is served under the Hopsworks app proxy at
	// /hopsworks-api/pythonapp/<project>/<app>/, a prefix only known at runtime.
	base: './',
	plugins: [
		react(),
		tailwindcss(),
		svgr({ include: '**/*.svg', svgrOptions: { exportType: 'default' } }),
	],
	resolve: {
		alias: { '@': root },
	},
	build: {
		outDir: fileURLToPath(new URL('../auto_ontology/server/static', import.meta.url)),
		emptyOutDir: true,
	},
	server: {
		port: 3000,
		proxy: {
			'/api': 'http://127.0.0.1:3001',
		},
	},
	test: {
		environment: 'jsdom',
		include: ['**/*.test.{ts,tsx}'],
		exclude: ['node_modules/**'],
	},
});
