// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';

import { Permission } from '@/enums/auth';
import { ADMIN, EDITOR, READER } from '@/test/renderWithMe';
import { hasPermission } from './useMe';

describe('hasPermission', () => {
	it('grants an admin everything, whatever the list says', () => {
		expect(hasPermission(ADMIN, Permission.ConversationDelete)).toBe(true);
	});

	it('follows the permission list for other roles', () => {
		expect(hasPermission(EDITOR, Permission.CatalogEdit)).toBe(true);
		expect(hasPermission(EDITOR, Permission.ConversationDelete)).toBe(false);
		expect(hasPermission(READER, Permission.ChatUse)).toBe(false);
		expect(hasPermission(READER, Permission.CatalogEdit)).toBe(false);
	});

	it('denies before the role has loaded', () => {
		expect(hasPermission(undefined, Permission.ChatUse)).toBe(false);
	});
});
