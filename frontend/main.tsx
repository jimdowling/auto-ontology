// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { RouterProvider } from 'react-router';

import { QueryProvider } from '@/contexts/QueryProvider';
import { router } from '@/routes';
import '@/styles/globals.css';

createRoot(document.getElementById('root')!).render(
	<StrictMode>
		<QueryProvider>
			<RouterProvider router={router} />
		</QueryProvider>
	</StrictMode>,
);
