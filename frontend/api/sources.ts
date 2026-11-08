// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { requests } from './requests';
import type { Source } from '@/types/sources';

export const sourcesApi = {
	list: () => requests.get<Source[]>('sources'),

	add: (source: Source) => requests.post<Source>('sources', source),

	remove: (name: string) => requests.delete<unknown>(`sources/${encodeURIComponent(name)}`),
};
