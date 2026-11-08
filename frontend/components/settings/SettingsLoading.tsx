// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { SkeletonRows } from '@/common/Skeleton';

/** Placeholder for a settings form whose stored values have not arrived. */
export const SettingsLoading = ({ error }: { error: Error | null }) => (
	<div className="h-full overflow-auto p-6">
		<div className="mx-auto max-w-xl">
			{error == null ? (
				<SkeletonRows rows={3} />
			) : (
				<p className="text-sm text-red-600 dark:text-red-300">
					Failed to load settings: {error.message}
				</p>
			)}
		</div>
	</div>
);
