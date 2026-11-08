// SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { Outlet } from 'react-router';
import { BackPanelLayout } from '@/common/BackPanelLayout';
import { SettingsNav } from '@/components/settings/SettingsNav';

export const SettingsPanelLayout = () => (
	<BackPanelLayout
		panelAriaLabel="Settings sections"
		expandAriaLabel="Expand settings menu"
		collapseAriaLabel="Collapse settings menu"
		panel={<SettingsNav />}
	>
		<Outlet />
	</BackPanelLayout>
);
