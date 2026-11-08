// SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { SelectButton } from '@/common/Button';
import { Popover } from '@/common/Popover';
import { Text } from '@/common/Text';
import { SelectButtonTheme } from '@/enums/button';
import { Role } from '@/enums/auth';
import { TextVariant } from '@/enums/text';
import { useMe } from '@/hooks/useMe';

const ROLE_LABEL: Record<Role, string> = {
	[Role.Admin]: 'Data owner',
	[Role.Editor]: 'Data scientist',
	[Role.Reader]: 'Read only',
};

/** Who Hopsworks says is signed in. Signing in and out happens in Hopsworks. */
export const UserMenu = () => {
	const { me } = useMe();
	if (me == null) return null;

	return (
		<Popover
			trigger={({ open, toggle }) => (
				<SelectButton
					theme={SelectButtonTheme.Avatar}
					onClick={toggle}
					aria-haspopup="dialog"
					aria-expanded={open}
					aria-label="Signed-in user"
				>
					{me.username.charAt(0).toUpperCase()}
				</SelectButton>
			)}
			panelClassName="w-56 px-3 py-2 text-xs text-secondary dark:text-zinc-500"
		>
			{() => (
				<>
					<Text text={me.username} variant={TextVariant.Strong} />
					<p className="text-[10px]">{ROLE_LABEL[me.role] ?? me.role}</p>
				</>
			)}
		</Popover>
	);
};
