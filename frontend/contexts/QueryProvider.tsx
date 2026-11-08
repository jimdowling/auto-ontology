// SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';

const queryClient = new QueryClient({
	defaultOptions: {
		queries: {
			/**
			 * A minute covers opening a page and the navigations that follow
			 * it; a write doesn't wait it out, since it invalidates its own key.
			 */
			staleTime: 60_000,
			/**
			 * Every read behind a query is permission-gated, and a refused one
			 * is refused the same way three times. One retry covers a dropped
			 * connection without turning a 403 into four requests.
			 */
			retry: 1,
		},
	},
});

/**
 * The cache every `useQuery` in the app reads from. Mounted at the root so a
 * list read on one page is not read again on the next.
 */
export const QueryProvider = ({ children }: { children: ReactNode }) => (
	<QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
);
