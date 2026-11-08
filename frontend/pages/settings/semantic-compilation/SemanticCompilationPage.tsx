// SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { useQuery } from '@tanstack/react-query';

import { sourcesApi } from '@/api/sources';
import { distinctValueProbingApi, semanticCompilationApi } from '@/api/settings';
import { SettingsLoading } from '@/components/settings/SettingsLoading';
import { SemanticCompilationForm } from './SemanticCompilationForm';

const readSettings = async () => {
	const [compilation, probing, sources] = await Promise.all([
		semanticCompilationApi.get(),
		distinctValueProbingApi.get(),
		sourcesApi.list(),
	]);
	return {
		enabled: compilation.enabled,
		probingEnabled: probing.enabled,
		hasDatabases: !sources.error && sources.length > 0,
	};
};

export const SemanticCompilationPage = () => {
	const { data, error } = useQuery({
		queryKey: ['configurations', 'semantic-compilation'],
		queryFn: readSettings,
		staleTime: 0,
	});
	if (data == null) return <SettingsLoading error={error} />;
	return (
		<SemanticCompilationForm
			initialEnabled={data.enabled}
			initialProbingEnabled={data.probingEnabled}
			hasDatabases={data.hasDatabases}
		/>
	);
};
