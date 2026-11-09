// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { sourcesApi } from '@/api/sources';
import { Button } from '@/common/Button';
import { EmptyState } from '@/common/EmptyState';
import { ConfirmModal, ModalCreateNewItem } from '@/common/modal';
import { SkeletonRows } from '@/common/Skeleton';
import { Table } from '@/common/Table';
import { ButtonTheme, Size } from '@/enums/button';
import { EmptyStateVariant } from '@/enums/emptyState';
import { useMe } from '@/hooks/useMe';
import type { Source } from '@/types/sources';
import type { TableColumn } from '@/types/table';

const SOURCES_KEY = ['sources'] as const;

const INPUT_CLASS =
	'w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-body outline-none transition-colors placeholder:text-secondary focus:border-accent focus:ring-2 focus:ring-accent/30 dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-300 dark:placeholder:text-zinc-500';

const LABEL_CLASS = 'block text-xs font-semibold text-secondary dark:text-zinc-400';

/** Splits a comma-separated schema list; an empty list means every schema. */
export const parseSchemas = (value: string): string[] | null => {
	const schemas = value
		.split(',')
		.map((schema) => schema.trim())
		.filter((schema) => schema !== '');
	return schemas.length === 0 ? null : schemas;
};

const readSources = async (): Promise<Source[]> => {
	const res = await sourcesApi.list();
	if (res.error) throw new Error(res.message ?? 'Failed to load sources.');
	return res;
};

type Draft = { name: string; schemas: string; tableRegex: string };

const EMPTY_DRAFT: Draft = { name: '', schemas: '', tableRegex: '' };

export const SourcesSettingsPage = () => {
	const queryClient = useQueryClient();
	const { isAdmin } = useMe();
	const {
		data: sources,
		error,
		isPending,
	} = useQuery({
		queryKey: SOURCES_KEY,
		queryFn: readSources,
	});

	const [draft, setDraft] = useState<Draft | null>(null);
	const [saving, setSaving] = useState(false);
	const [addError, setAddError] = useState<string | null>(null);
	const [removing, setRemoving] = useState<Source | null>(null);
	const [removeBusy, setRemoveBusy] = useState(false);
	const [removeError, setRemoveError] = useState<string | null>(null);

	const closeAdd = () => {
		setDraft(null);
		setAddError(null);
	};

	const submitAdd = async () => {
		if (draft == null) return;
		setSaving(true);
		setAddError(null);
		const res = await sourcesApi.add({
			name: draft.name.trim(),
			schemas: parseSchemas(draft.schemas),
			table_regex: draft.tableRegex.trim() || null,
		});
		setSaving(false);
		if (res.error) {
			setAddError(res.message ?? 'Failed to add the source.');
			return;
		}
		closeAdd();
		await queryClient.invalidateQueries({ queryKey: SOURCES_KEY });
	};

	const closeRemove = () => {
		setRemoving(null);
		setRemoveError(null);
	};

	const confirmRemove = async () => {
		if (removing == null) return;
		setRemoveBusy(true);
		setRemoveError(null);
		const res = await sourcesApi.remove(removing.name);
		setRemoveBusy(false);
		if (res.error) {
			setRemoveError(res.message ?? 'Failed to remove the source.');
			return;
		}
		closeRemove();
		await queryClient.invalidateQueries({ queryKey: SOURCES_KEY });
	};

	const columns: TableColumn<Source>[] = [
		{
			key: 'name',
			header: 'Data source',
			truncate: true,
			cell: (source) => source.name,
			title: (source) => source.name,
		},
		{
			key: 'schemas',
			header: 'Schemas',
			truncate: true,
			cell: (source) => (source.schemas?.length ? source.schemas.join(', ') : 'All schemas'),
			title: (source) => source.schemas?.join(', ') ?? '',
		},
		{
			key: 'table_regex',
			header: 'Table filter',
			truncate: true,
			className: 'font-mono text-xs',
			cell: (source) => source.table_regex ?? 'All tables',
			title: (source) => source.table_regex ?? '',
		},
		...(isAdmin
			? [
					{
						key: 'actions',
						header: '',
						width: 'w-28',
						className: 'text-right',
						cell: (source: Source) => (
							<Button
								theme={ButtonTheme.Outline}
								size={Size.SMALL}
								onClick={() => setRemoving(source)}
							>
								Remove
							</Button>
						),
					},
				]
			: []),
	];

	return (
		<main className="min-h-0 min-w-0 flex-1 overflow-y-auto px-7 py-6 sm:px-10 sm:py-7">
			<div className="mx-auto w-full max-w-4xl space-y-4">
				<div className="flex items-start justify-between gap-4">
					<div>
						<h1 className="text-lg font-semibold text-heading dark:text-zinc-100">
							Sources
						</h1>
						<p className="mt-1 text-xs text-secondary">
							Hopsworks data sources this ontology ingests. Each must use shared
							credentials. Changes apply from the next ingest.
						</p>
					</div>
					{isAdmin && (
						<Button
							theme={ButtonTheme.Primary}
							size={Size.REGULAR}
							onClick={() => setDraft(EMPTY_DRAFT)}
						>
							Add Source
						</Button>
					)}
				</div>

				{isPending ? (
					<SkeletonRows rows={4} />
				) : error != null ? (
					<EmptyState
						variant={EmptyStateVariant.Inline}
						title="Could not load sources"
						description={error.message}
					/>
				) : (
					<Table
						columns={columns}
						rows={sources ?? []}
						rowKey={(source) => source.name}
						emptyMessage="No sources yet"
					/>
				)}
			</div>

			<ModalCreateNewItem
				open={draft != null}
				onClose={closeAdd}
				title="Add Source"
				submitLabel={saving ? 'Adding…' : 'Add Source'}
				onSubmit={submitAdd}
				canSubmit={!saving && draft != null && draft.name.trim() !== ''}
				className="w-[560px] max-w-full"
			>
				{draft != null && (
					<>
						<label className="block space-y-1">
							<span className={LABEL_CLASS}>Data source name</span>
							<input
								type="text"
								value={draft.name}
								onChange={(e) => setDraft({ ...draft, name: e.target.value })}
								placeholder="sales_mysql"
								className={INPUT_CLASS}
							/>
						</label>
						<label className="block space-y-1">
							<span className={LABEL_CLASS}>Schemas (comma-separated, optional)</span>
							<input
								type="text"
								value={draft.schemas}
								onChange={(e) => setDraft({ ...draft, schemas: e.target.value })}
								placeholder="All schemas"
								className={INPUT_CLASS}
							/>
						</label>
						<label className="block space-y-1">
							<span className={LABEL_CLASS}>
								Table filter (regular expression, optional)
							</span>
							<input
								type="text"
								value={draft.tableRegex}
								onChange={(e) => setDraft({ ...draft, tableRegex: e.target.value })}
								placeholder="All tables"
								className={`${INPUT_CLASS} font-mono`}
							/>
						</label>
						{addError != null && (
							<p className="text-sm text-red-600 dark:text-red-300">{addError}</p>
						)}
					</>
				)}
			</ModalCreateNewItem>

			<ConfirmModal
				open={removing != null}
				title="Remove Source"
				message={
					<>
						Stop ingesting <strong>{removing?.name}</strong>? The reset job then deletes
						its catalog, semantic layer and vectors.
					</>
				}
				confirmLabel="Remove"
				onConfirm={confirmRemove}
				onCancel={closeRemove}
				confirming={removeBusy}
				error={removeError}
			/>
		</main>
	);
};
