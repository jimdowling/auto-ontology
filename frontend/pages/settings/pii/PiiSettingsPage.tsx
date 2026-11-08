// SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { useQuery } from '@tanstack/react-query';

import { piiDetectionApi } from '@/api/settings';
import { SettingsLoading } from '@/components/settings/SettingsLoading';
import { PiiSettingsForm } from './PiiSettingsForm';

export const PiiSettingsPage = () => {
	const { data, error } = useQuery({
		queryKey: ['configurations', 'pii-detection'],
		queryFn: piiDetectionApi.get,
		staleTime: 0,
	});
	if (data == null) return <SettingsLoading error={error} />;
	return <PiiSettingsForm initialEnabled={data.enabled} />;
};
