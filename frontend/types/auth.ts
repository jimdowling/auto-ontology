// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { Role } from '@/enums/auth';

/** The signed-in Hopsworks user, from `GET api/me`. */
export type Me = {
	username: string;
	role: Role;
	/** `resource:action` strings the role grants. */
	permissions: string[];
};
