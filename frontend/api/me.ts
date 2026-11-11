// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { requests } from './requests';
import type { Me } from '@/types/auth';

export const meApi = {
	get: () => requests.get<Me>('me'),
};
