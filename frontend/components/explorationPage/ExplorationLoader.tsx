// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

type ExplorationLoaderProps = {
	overlay?: boolean;
};

export const ExplorationLoader = ({ overlay = false }: ExplorationLoaderProps) => (
	<div
		className={`flex h-full w-full items-center justify-center bg-zinc-50 dark:bg-zinc-950${
			overlay ? ' absolute inset-0 z-10' : ''
		}`}
		role="status"
		aria-label="Loading exploration"
	>
		<img
			src={`${import.meta.env.BASE_URL}exploration-loader.svg`}
			alt=""
			width={720}
			height={430}
			className="h-auto w-full max-w-[720px]"
		/>
	</div>
);
