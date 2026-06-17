<script lang="ts">
	import { activeWorkspace, openFileTab } from '$lib/stores';
	import {
		getGitLog,
		getGitDiff,
		getGitShow,
		getGitBranches,
		getGitStatusFresh,
		getGitStashes,
		stageFiles,
		unstageFiles,
		discardChanges,
		gitCommit,
		gitFetch,
		gitPull,
		gitPush,
		gitUncommit,
		gitStash,
		gitUnstash,
		checkoutBranch,
		createGitBranch
	} from '$lib/apis/git';
	import { gitStatusStore } from '$lib/stores/gitStatus.svelte';
	import Icon from './Icon.svelte';
	import DropdownMenu from './DropdownMenu.svelte';
	import Modal from './Modal.svelte';
	import { tooltip } from '$lib/tooltip';
	import { t } from '$lib/i18n';
	import Spinner from '$lib/components/common/Spinner.svelte';

	type GitFile = {
		path: string;
		status: string;
		staged: boolean;
		unstaged?: boolean;
		staged_status?: string;
		unstaged_status?: string;
	};
	type DiffHunk = { header: string; lines: { type: string; content: string }[] };
	type DiffFile = { path: string; hunks: DiffHunk[] };
	type Commit = { hash: string; short_hash: string; author: string; date: string; message: string };

	let expanded = $state(false);
	let view = $state<'changes' | 'history'>('changes');
	let showDiff = $state(false);
	let showBranches = $state(false);
	let branchBtnEl = $state<HTMLButtonElement | undefined>();
	let branchSearchInputEl = $state<HTMLInputElement | undefined>();
	let newBranchInputEl = $state<HTMLInputElement | undefined>();
	let commits = $state<Commit[]>([]);
	let branchData = $state<{
		current: string;
		local: string[];
		remote: string[];
		all?: { name: string; is_current?: boolean; is_local?: boolean; upstream?: string | null }[];
	} | null>(null);
	let branchSearch = $state('');
	let newBranchName = $state('');
	let creatingBranch = $state(false);
	let pendingCheckoutBranch = $state<string | null>(null);
	let selectedFile = $state<string | null>(null);
	let selectedCommit = $state<Commit | null>(null);
	let fileDiff = $state<DiffFile[]>([]);
	let commitSummary = $state('');
	let commitDescription = $state('');
	let actionMsg = $state('');
	let loading = $state(false);
	let panelHeight = $state(280);
	let prevHeight = $state(280);
	let isMaximized = $state(false);
	let resizing = $state(false);
	let containerEl = $state<HTMLElement | null>(null);

	const workspacePath = $derived($activeWorkspace?.path ?? '');
	const stagedFiles = $derived((gitStatus?.files ?? []).filter((f) => f.staged));
	const unstagedFiles = $derived((gitStatus?.files ?? []).filter((f) => !f.staged));
	const totalChanges = $derived((gitStatus?.files ?? []).length);
	const allStaged = $derived(totalChanges > 0 && unstagedFiles.length === 0);
	const someStaged = $derived(stagedFiles.length > 0 && unstagedFiles.length > 0);

	let gitStatus = $derived(
		gitStatusStore.status as {
			is_repo: boolean;
			branch: string;
			upstream: string;
			remote_url: string;
			ahead: number;
			behind: number;
			files: GitFile[];
		} | null
	);

	// Branch has never been pushed to remote
	const needsPublish = $derived(!gitStatus?.upstream);
	const unpushedCount = $derived(needsPublish ? (commits?.length ?? 0) : (gitStatus?.ahead ?? 0));
	const filteredBranches = $derived.by(() => {
		const branches = branchData?.all ?? [];
		const query = branchSearch.trim().toLowerCase();
		if (!query) return branches;
		return branches.filter((branch) => branch.name.toLowerCase().includes(query));
	});
	const branchMenuItems = $derived(
		filteredBranches.map((branch) => ({
			label: branch.name,
			icon: 'git-branch',
			active: Boolean(branch.is_current),
			check: true,
			onclick: () => switchBranch(branch.name)
		}))
	);

	// Convert git remote URL to browser URL
	const remoteWebUrl = $derived.by(() => {
		const url = gitStatus?.remote_url;
		if (!url) return '';
		// SSH: git@github.com:user/repo.git
		const sshMatch = url.match(/^git@([^:]+):(.+?)(\.git)?$/);
		if (sshMatch) return `https://${sshMatch[1]}/${sshMatch[2]}`;
		// HTTPS: https://github.com/user/repo.git
		return url.replace(/\.git$/, '');
	});

	const remotePlatform = $derived.by(() => {
		if (!remoteWebUrl) return '';
		if (remoteWebUrl.includes('github.com')) return 'GitHub';
		if (remoteWebUrl.includes('gitlab.com') || remoteWebUrl.includes('gitlab')) return 'GitLab';
		if (remoteWebUrl.includes('bitbucket')) return 'Bitbucket';
		try {
			return new URL(remoteWebUrl).hostname;
		} catch {
			return 'Remote';
		}
	});

	// Clear stale selection when file is no longer in the changed list
	$effect(() => {
		if (view === 'changes' && selectedFile) {
			const stillExists = (gitStatus?.files ?? []).some((f) => f.path === selectedFile);
			if (!stillExists) {
				selectedFile = null;
				fileDiff = [];
				showDiff = false;
			}
		}
	});

	// Auto-select first file
	$effect(() => {
		if (
			expanded &&
			view === 'changes' &&
			totalChanges > 0 &&
			!selectedFile &&
			window.innerWidth >= 768
		) {
			const f = [...stagedFiles, ...unstagedFiles][0];
			if (f) selectFile(f.path, f.staged, f.status === 'untracked');
		}
	});

	async function refresh({ force = false }: { force?: boolean } = {}) {
		await gitStatusStore.refresh({ force });
	}

	async function selectFile(path: string, staged: boolean, untracked: boolean = false) {
		selectedFile = path;
		selectedCommit = null;
		showDiff = true;
		try {
			const params = new URLSearchParams({
				root: workspacePath,
				file: path,
				staged: String(staged)
			});
			if (untracked) params.set('untracked', 'true');
			const d = await getGitDiff(params.toString());
			fileDiff = d.files ?? [];
		} catch {
			fileDiff = [];
		}
	}

	async function selectCommit(c: Commit) {
		selectedCommit = c;
		selectedFile = null;
		showDiff = true;
		try {
			const d = await getGitShow(workspacePath, c.hash);
			fileDiff = d.diff?.files ?? [];
		} catch {
			fileDiff = [];
		}
	}

	function backToList() {
		showDiff = false;
	}

	async function loadHistory() {
		try {
			commits = await getGitLog(workspacePath, 50);
		} catch {
			commits = [];
		}
	}

	async function loadBranches() {
		try {
			branchData = await getGitBranches(workspacePath);
		} catch {
			branchData = null;
		}
	}

	async function toggleBranches(e: MouseEvent) {
		e.stopPropagation();
		if (showBranches) {
			showBranches = false;
			return;
		}
		showBranches = true;
		branchSearch = '';
		creatingBranch = false;
		newBranchName = '';
		await loadBranches();
		setTimeout(() => branchSearchInputEl?.focus(), 0);
	}

	function switchView(v: 'changes' | 'history') {
		view = v;
		showDiff = false;
		selectedFile = null;
		selectedCommit = null;
		fileDiff = [];
		if (v === 'history') loadHistory();
	}

	async function toggleStage(e: Event, file: GitFile) {
		e.stopPropagation();
		if (file.staged) {
			await unstageFiles(workspacePath, [file.path]);
		} else {
			await stageFiles(workspacePath, [file.path]);
		}
		await refresh();
	}

	async function toggleAll() {
		if (allStaged) {
			await unstageFiles(
				workspacePath,
				stagedFiles.map((f) => f.path)
			);
		} else {
			await stageFiles(
				workspacePath,
				unstagedFiles.map((f) => f.path)
			);
		}
		await refresh();
	}

	async function doCommit() {
		if (!commitSummary.trim() || !stagedFiles.length) return;
		loading = true;
		await stageFiles(
			workspacePath,
			stagedFiles.map((f) => f.path)
		);
		const msg = commitDescription.trim()
			? `${commitSummary.trim()}\n\n${commitDescription.trim()}`
			: commitSummary.trim();
		await gitCommit(workspacePath, msg);
		commitSummary = '';
		commitDescription = '';
		flash($t('git.committed'));
		selectedFile = null;
		fileDiff = [];
		loading = false;
		await refresh();
	}

	async function doUncommit() {
		loading = true;
		try {
			const d = await gitUncommit(workspacePath);
			flash($t('git.uncommitted'));
			switchView('changes');
		} catch (e) {
			flash(e instanceof Error ? e.message : 'Failed to undo commit');
		}
		loading = false;
		await refresh();
	}

	async function doPull() {
		loading = true;
		const d = await gitPull(workspacePath);
		flash(d.ok ? $t('git.pulled') : d.message);
		loading = false;
		await refresh({ force: true });
	}

	async function doFetch() {
		loading = true;
		try {
			const d = (await gitFetch(workspacePath)) as { ok?: boolean; message?: string };
			flash(d.ok ? d.message || $t('git.fetch') : d.message || 'Fetch failed');
		} catch (e) {
			flash(e instanceof Error ? e.message : 'Fetch failed');
		} finally {
			loading = false;
			await refresh({ force: true });
			if (showBranches) await loadBranches();
			if (view === 'history') await loadHistory();
		}
	}

	async function doPush() {
		loading = true;
		const d = await gitPush(workspacePath, {
			set_upstream: needsPublish,
			branch: needsPublish ? gitStatus?.branch : undefined
		});
		flash(d.ok ? $t('git.pushed') : d.message);
		loading = false;
		await refresh({ force: true });
	}

	async function switchBranch(branch: string) {
		if (branch === gitStatus?.branch) {
			showBranches = false;
			return;
		}
		if (totalChanges > 0) {
			pendingCheckoutBranch = branch;
			showBranches = false;
			return;
		}
		await performBranchCheckout(branch, 'bring');
	}

	async function restoreStashedChangesForBranch(branch: string) {
		const stashes = (await getGitStashes(workspacePath)) as { message?: string }[];
		const index = stashes.findIndex((stash) => {
			const message = stash.message ?? '';
			return (
				message.includes(`cptr-branch-switch:${branch}`) ||
				message.includes(`Changes on ${branch} before checking out`)
			);
		});
		if (index < 0) return;

		const freshStatus = (await getGitStatusFresh(workspacePath)) as { files?: GitFile[] };
		if ((freshStatus.files ?? []).length > 0) return;

		const result = (await gitUnstash(workspacePath, index)) as { ok?: boolean; message?: string };
		if (result.ok) {
			flash(`Restored changes for ${branch}`);
		} else {
			flash(result.message || `Could not restore changes for ${branch}`);
		}
	}

	async function performBranchCheckout(branch: string, changeMode: 'bring' | 'leave') {
		loading = true;
		try {
			if (changeMode === 'leave') {
				const currentBranch = gitStatus?.branch || 'current branch';
				const message = `cptr-branch-switch:${currentBranch}`;
				const stashResult = (await gitStash(workspacePath, message)) as {
					ok?: boolean;
					message?: string;
				};
				if (!stashResult.ok) {
					flash(stashResult.message || 'No changes stashed');
					return;
				}
			}
			await checkoutBranch(workspacePath, branch);
			pendingCheckoutBranch = null;
			await restoreStashedChangesForBranch(branch);
		} catch (e) {
			flash(e instanceof Error ? e.message : 'Failed to switch branch');
		} finally {
			loading = false;
			await refresh();
		}
	}

	async function createBranch() {
		if (!newBranchName.trim()) return;
		loading = true;
		await createGitBranch(workspacePath, newBranchName.trim());
		newBranchName = '';
		creatingBranch = false;
		showBranches = false;
		loading = false;
		await refresh();
	}

	function flash(m: string) {
		actionMsg = m;
		setTimeout(() => {
			actionMsg = '';
		}, 3000);
	}

	// Context menu
	let contextMenu = $state<{ file: GitFile; anchor: HTMLElement } | null>(null);
	let commitMenu = $state<{ commit: Commit; isLatest: boolean; anchor: HTMLElement } | null>(null);

	function openFileMenu(e: MouseEvent, file: GitFile) {
		e.stopPropagation();
		contextMenu = { file, anchor: e.currentTarget as HTMLElement };
	}

	function closeContextMenu() {
		contextMenu = null;
	}

	function openCommitMenu(e: MouseEvent, commit: Commit, isLatest: boolean) {
		e.stopPropagation();
		commitMenu = { commit, isLatest, anchor: e.currentTarget as HTMLElement };
	}

	function closeCommitMenu() {
		commitMenu = null;
	}

	async function discardFile(path: string) {
		await discardChanges(workspacePath, [path]);
		if (selectedFile === path) {
			selectedFile = null;
			fileDiff = [];
		}
		flash($t('git.discarded'));
		await refresh();
	}

	function copyFilePath(path: string) {
		const full = workspacePath.endsWith('/') ? workspacePath + path : workspacePath + '/' + path;
		navigator.clipboard.writeText(full);
		flash($t('git.copiedPath'));
	}

	function copyRelativePath(path: string) {
		navigator.clipboard.writeText(path);
		flash($t('git.copiedRelativePath'));
	}

	// Path prefix in muted, filename in normal weight
	function fPath(p: string): { dir: string; name: string } {
		const i = p.lastIndexOf('/');
		return i >= 0 ? { dir: p.slice(0, i + 1), name: p.slice(i + 1) } : { dir: '', name: p };
	}

	function relTime(d: string) {
		const s = Math.floor((Date.now() - new Date(d).getTime()) / 1000);
		if (s < 60) return 'now';
		if (s < 3600) return `${Math.floor(s / 60)}m`;
		if (s < 86400) return `${Math.floor(s / 3600)}h`;
		return `${Math.floor(s / 86400)}d`;
	}

	function statusChar(s: string): { char: string; color: string } {
		switch (s) {
			case 'added':
				return { char: 'A', color: 'text-green-500' };
			case 'untracked':
				return { char: 'U', color: 'text-green-500' };
			case 'modified':
				return { char: 'M', color: 'text-amber-500' };
			case 'deleted':
				return { char: 'D', color: 'text-red-400' };
			case 'renamed':
				return { char: 'R', color: 'text-blue-400' };
			case 'conflict':
				return { char: '!', color: 'text-orange-500' };
			default:
				return { char: '?', color: 'text-gray-400' };
		}
	}

	const syncAction = $derived.by(() => {
		if (!gitStatus) return { label: $t('git.fetch'), icon: 'refresh', action: doFetch };
		if (gitStatus.behind > 0)
			return {
				label: $t('git.pullCount', { count: gitStatus.behind }),
				icon: 'download',
				action: doPull
			};
		if (gitStatus.ahead > 0)
			return {
				label: $t('git.pushCount', { count: gitStatus.ahead }),
				icon: 'upload',
				action: doPush
			};
		if (!gitStatus.upstream) return { label: $t('git.publish'), icon: 'upload', action: doPush };
		return { label: $t('git.fetch'), icon: 'refresh', action: doFetch };
	});

	function onResizeStart(e: PointerEvent) {
		resizing = true;
		isMaximized = false;
		const startY = e.clientY;
		const startH = panelHeight;
		const maxH = getMaxHeight();
		function onMove(ev: PointerEvent) {
			panelHeight = Math.max(140, Math.min(maxH, startH - (ev.clientY - startY)));
		}
		function onUp() {
			resizing = false;
			window.removeEventListener('pointermove', onMove);
			window.removeEventListener('pointerup', onUp);
		}
		window.addEventListener('pointermove', onMove);
		window.addEventListener('pointerup', onUp);
	}

	function getMaxHeight() {
		return (containerEl?.parentElement?.clientHeight ?? window.innerHeight) - 100;
	}

	function toggleMaximize() {
		if (isMaximized) {
			panelHeight = prevHeight;
			isMaximized = false;
		} else {
			prevHeight = panelHeight;
			panelHeight = getMaxHeight();
			isMaximized = true;
		}
	}

	type LineGroup = { type: string; lines: { type: string; content: string }[] };

	function groupLines(lines: { type: string; content: string }[]): LineGroup[] {
		const groups: LineGroup[] = [];
		for (const line of lines) {
			const last = groups[groups.length - 1];
			if (last && last.type === line.type) {
				last.lines.push(line);
			} else {
				groups.push({ type: line.type, lines: [line] });
			}
		}
		return groups;
	}

	function blockClass(type: string): string {
		switch (type) {
			case 'added':
				return 'bg-green-100 border-l-[3px] border-l-green-500 dark:bg-green-500/15 dark:border-l-green-400';
			case 'removed':
				return 'bg-red-100 diff-gutter-removed dark:bg-red-500/15';
			default:
				return '';
		}
	}

	$effect(() => {
		if (!expanded) return;
		function onKeydown(e: KeyboardEvent) {
			if (!gitStatus?.is_repo) return;
			if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'p' && !e.shiftKey && !e.altKey) {
				e.preventDefault();
				doPush();
			}
		}
		window.addEventListener('keydown', onKeydown);
		return () => window.removeEventListener('keydown', onKeydown);
	});
</script>

{#if gitStatus?.is_repo}
	<div
		class="shrink-0 border-t border-gray-200 dark:border-white/6 relative"
		bind:this={containerEl}
	>
		<!-- Resize handle (top edge, styled like sidebar) -->
		{#if expanded}
			<!-- svelte-ignore a11y_no_static_element_interactions -->
			<div class="git-resize-handle" class:active={resizing} onpointerdown={onResizeStart}></div>
		{/if}

		<!-- Collapsed bar (entire bar is clickable to expand) -->
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div
			class="flex items-center h-7 px-3 cursor-pointer hover:bg-gray-50 dark:hover:bg-white/3 transition-colors duration-75"
			onclick={() => {
				expanded = !expanded;
				if (expanded) {
					refresh();
					if (view === 'history') loadHistory();
				}
			}}
		>
			<!-- Branch button (opens branch picker, stops expand) -->
			<button
				bind:this={branchBtnEl}
				class="flex items-center gap-1.5 h-6 px-1.5 -ml-1.5 rounded-md hover:bg-gray-100 dark:hover:bg-white/6 transition-colors duration-75"
				onclick={toggleBranches}
			>
				<Icon name="git-branch" size={12} class="text-gray-400 dark:text-gray-600 shrink-0" />
				<span class="text-[11px] text-gray-600 dark:text-gray-400 font-mono"
					>{gitStatus.branch}</span
				>
				<Icon name="chevron-down" size={9} class="text-gray-400 dark:text-gray-600" />
			</button>

			{#if gitStatus.ahead > 0}<span
					class="text-[10px] font-mono text-gray-400 dark:text-gray-600 ml-1.5"
					>↑{gitStatus.ahead}</span
				>{/if}
			{#if gitStatus.behind > 0}<span
					class="text-[10px] font-mono text-gray-400 dark:text-gray-600 ml-1"
					>↓{gitStatus.behind}</span
				>{/if}
			{#if totalChanges > 0}<span
					class="text-[10px] font-mono text-gray-400 dark:text-gray-600 ml-1.5"
					>{$t('git.changedCount', { count: totalChanges })}</span
				>{/if}
			{#if actionMsg}<span class="text-[10px] font-mono text-gray-400 dark:text-gray-600 ml-auto"
					>{actionMsg}</span
				>{/if}

			<div class="flex-1"></div>

			<!-- Sync button (stops expand) -->
			<button
				class="flex items-center gap-1 h-6 px-2 rounded-md text-[11px] text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-white/6 transition-colors duration-75"
				onclick={(e) => {
					e.stopPropagation();
					syncAction.action();
				}}
				disabled={loading}
			>
				<Icon name={syncAction.icon} size={12} />
				<span>{syncAction.label}</span>
			</button>

			<!-- Chevron indicator -->
			<span
				class="text-gray-300 dark:text-gray-700 shrink-0 transition-transform duration-100 ml-0.5"
				style="transform: rotate({expanded ? '180deg' : '0deg'})"
			>
				<Icon name="chevron-up" size={10} />
			</span>
		</div>

		<!-- Branch picker dropdown -->
		{#if showBranches && branchBtnEl}
			<DropdownMenu
				items={branchMenuItems}
				anchor={branchBtnEl}
				onclose={() => {
					showBranches = false;
					creatingBranch = false;
					newBranchName = '';
				}}
				preferAbove
				forceAbove
				maxHeight="15rem"
				className="w-56"
				align="start"
				headerDivider={false}
				footerDivider={false}
			>
				{#snippet header()}
					<div class="px-2 pb-0.5">
						<div class="flex items-center gap-1.5 h-6 mt-0.5">
							<Icon name="search" size={13} class="shrink-0 text-gray-300 dark:text-gray-600" />
							<input
								bind:this={branchSearchInputEl}
								bind:value={branchSearch}
								placeholder="Search branches"
								class="w-full bg-transparent text-[11px] text-gray-500 dark:text-gray-400 placeholder:text-gray-300 dark:placeholder:text-gray-600 outline-none"
								onkeydown={(e) => {
									if (e.key === 'Escape') showBranches = false;
								}}
							/>
						</div>
						{#if !branchData}
							<div class="flex items-center justify-center h-10">
								<Spinner size={14} />
							</div>
						{/if}
					</div>
				{/snippet}
				{#snippet empty()}
					{#if branchData}
						<div class="px-3 py-2 text-[11px] text-gray-400 dark:text-gray-500 text-center">
							No branches found
						</div>
					{/if}
				{/snippet}
				{#snippet footer()}
					{#if creatingBranch}
						<div class="flex items-center gap-2 h-7 px-2">
							<Icon name="git-branch" size={14} class="text-gray-400 shrink-0" />
							<input
								bind:this={newBranchInputEl}
								type="text"
								class="flex-1 border-none outline-none bg-transparent text-xs text-gray-900 dark:text-white placeholder:text-gray-400"
								placeholder={$t('git.branchName')}
								bind:value={newBranchName}
								onkeydown={(e) => {
									if (e.key === 'Enter') createBranch();
									if (e.key === 'Escape') {
										creatingBranch = false;
										newBranchName = '';
									}
								}}
							/>
							<button
								class="flex items-center justify-center w-5 h-5 rounded text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-white/6 transition-colors duration-75"
								onclick={() => {
									creatingBranch = false;
									newBranchName = '';
								}}
							>
								<Icon name="xmark" size={12} />
							</button>
							<button
								class="flex items-center justify-center w-5 h-5 rounded text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-white/6 transition-colors duration-75"
								onclick={createBranch}
							>
								<Icon name="check" size={12} />
							</button>
						</div>
					{:else}
						<button
							class="flex items-center gap-2 w-full h-7 px-2 rounded-xl text-xs text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-white/5 hover:text-gray-900 dark:hover:text-white transition-colors"
							onclick={() => {
								creatingBranch = true;
								setTimeout(() => newBranchInputEl?.focus(), 0);
							}}
						>
							<Icon name="plus" size={14} />
							<span class="truncate">New branch</span>
						</button>
					{/if}
				{/snippet}
			</DropdownMenu>
		{/if}

		{#if expanded}
			<div class="border-t border-gray-100 dark:border-white/4">
				<!-- Header tabs -->
				<div
					class="flex items-center gap-0.5 h-8 px-2 border-b border-gray-100 dark:border-white/4"
				>
					<!-- Mobile back button when viewing diff -->
					{#if showDiff}
						<button
							class="flex md:hidden items-center gap-1 h-6 px-1.5 rounded-md text-[11px] text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 transition-colors"
							onclick={backToList}
						>
							<Icon name="chevron-left" size={12} />
						</button>
					{/if}

					<!-- Tabs (always visible) -->
					<button
						class="px-2.5 h-6 rounded-md text-[11px] font-medium transition-colors duration-75
							{view === 'changes'
							? 'bg-gray-200/50 dark:bg-white/8 text-gray-900 dark:text-white'
							: 'text-gray-400 hover:text-gray-600 dark:hover:text-gray-300'}"
						onclick={() => switchView('changes')}
						>Changes{#if totalChanges > 0}<span class="ml-1 text-gray-400 dark:text-gray-500"
								>{totalChanges}</span
							>{/if}</button
					>
					<button
						class="px-2.5 h-6 rounded-md text-[11px] font-medium transition-colors duration-75
							{view === 'history'
							? 'bg-gray-200/50 dark:bg-white/8 text-gray-900 dark:text-white'
							: 'text-gray-400 hover:text-gray-600 dark:hover:text-gray-300'}"
						onclick={() => switchView('history')}>{$t('git.history')}</button
					>

					<div class="flex-1"></div>

					<!-- View on remote -->
					{#if remoteWebUrl}
						<a
							href={remoteWebUrl}
							target="_blank"
							rel="noopener noreferrer"
							class="flex items-center justify-center w-6 h-6 rounded-md text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-white/6 transition-colors duration-75"
							use:tooltip={'View on ' + remotePlatform}
						>
							<Icon name="external-link" size={12} />
						</a>
					{/if}

					<!-- Maximize toggle -->
					<button
						class="flex items-center justify-center w-6 h-6 rounded-md text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-white/6 transition-colors duration-75"
						onclick={toggleMaximize}
						use:tooltip={isMaximized ? $t('git.restore') : $t('git.maximize')}
					>
						<Icon name={isMaximized ? 'collapse' : 'expand'} size={12} />
					</button>
				</div>

				<!-- Content -->
				<div class="flex min-h-36" style="height: {panelHeight}px;">
					<!-- Left pane: file list or commit list -->
					<div
						class="w-full md:w-60 lg:w-72 shrink-0 md:border-r md:border-gray-100 md:dark:border-white/4 flex flex-col overflow-hidden
						{showDiff ? 'hidden md:flex' : 'flex'}"
					>
						{#if view === 'changes'}
							<!-- Global checkbox -->
							{#if totalChanges > 0}
								<button
									class="flex items-center gap-1.5 h-7 px-2.5 border-b border-gray-100 dark:border-white/4 hover:bg-gray-50 dark:hover:bg-white/3 transition-colors duration-75 shrink-0"
									onclick={toggleAll}
								>
									<span
										class="flex items-center justify-center w-3 h-3 rounded border shrink-0
										{allStaged
											? 'border-gray-300 dark:border-gray-600 bg-gray-800 dark:bg-white'
											: someStaged
												? 'border-gray-300 dark:border-gray-600 bg-gray-400 dark:bg-gray-500'
												: 'border-gray-300 dark:border-gray-600'}"
									>
										{#if allStaged || someStaged}
											<Icon
												name={allStaged ? 'check' : 'minus'}
												size={7}
												class="text-white dark:text-black"
											/>
										{/if}
									</span>
									<span class="text-[11px] text-gray-600 dark:text-gray-400"
										>{$t('git.changedFile', { count: totalChanges })}</span
									>
								</button>
							{/if}

							<!-- File list -->
							<div class="flex-1 overflow-y-auto">
								{#each gitStatus?.files ?? [] as file (file.path)}
									{@const fp = fPath(file.path)}
									{@const sc = statusChar(file.status)}
									<button
										class="group flex items-center gap-1.5 w-full h-7 px-2.5 text-left transition-colors duration-75
											{selectedFile === file.path
											? 'bg-gray-100 dark:bg-white/8'
											: 'hover:bg-gray-50 dark:hover:bg-white/3'}"
										onclick={() => selectFile(file.path, file.staged, file.status === 'untracked')}
									>
										<!-- svelte-ignore a11y_no_static_element_interactions -->
										<span
											class="flex items-center justify-center w-3 h-3 rounded border shrink-0 cursor-pointer
												{file.staged
												? 'border-gray-300 dark:border-gray-600 bg-gray-800 dark:bg-white'
												: 'border-gray-300 dark:border-gray-600 hover:border-gray-500 dark:hover:border-gray-400'}"
											onclick={(e) => {
												e.stopPropagation();
												toggleStage(e, file);
											}}
										>
											{#if file.staged}
												<Icon name="check" size={7} class="text-white dark:text-black" />
											{/if}
										</span>
										{#if fp.dir}
											<span
												class="text-[10px] text-gray-400 dark:text-gray-600 truncate shrink min-w-0"
												>{fp.dir}</span
											>
										{/if}
										<!-- svelte-ignore a11y_no_static_element_interactions -->
										<span
											class="text-[11px] text-gray-800 dark:text-gray-200 truncate shrink-0 hover:underline cursor-pointer"
											onclick={(e) => {
												e.stopPropagation();
												openFileTab(workspacePath.replace(/\/$/, '') + '/' + file.path);
											}}>{fp.name}</span
										>
										<span class="ml-auto text-[10px] font-mono font-bold shrink-0 {sc.color}"
											>{sc.char}</span
										>
										<!-- svelte-ignore a11y_no_static_element_interactions -->
										<span
											class="flex items-center justify-center w-5 h-5 rounded shrink-0 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-200 dark:hover:bg-white/10 transition-all duration-75"
											role="button"
											tabindex="-1"
											onclick={(e) => openFileMenu(e, file)}
											aria-label={$t('files.moreActions')}
										>
											<Icon name="three-dots" size={12} />
										</span>
									</button>
								{/each}
							</div>

							<!-- Commit area: combined input group -->
							<div class="border-t border-gray-100 dark:border-white/4 p-2 shrink-0">
								<div
									class="rounded-lg border border-gray-200 dark:border-white/8 overflow-hidden focus-within:border-gray-300 dark:focus-within:border-white/15 transition-colors"
								>
									<input
										type="text"
										class="w-full h-7 px-2 bg-transparent text-[11px] text-gray-900 dark:text-white placeholder:text-gray-400 dark:placeholder:text-gray-600 outline-none"
										placeholder={$t('git.summaryRequired')}
										bind:value={commitSummary}
										onkeydown={(e) => {
											if (e.key === 'Enter' && !e.shiftKey) doCommit();
										}}
									/>
									<textarea
										class="w-full px-2 py-1.5 bg-transparent text-[11px] text-gray-900 dark:text-white placeholder:text-gray-400 dark:placeholder:text-gray-600 outline-none resize-none border-t border-gray-100 dark:border-white/4"
										rows="2"
										placeholder={$t('git.description')}
										bind:value={commitDescription}
									></textarea>
								</div>
								<button
									class="w-full h-7 mt-1.5 rounded-lg text-[11px] font-medium transition-colors duration-75
										{stagedFiles.length && commitSummary.trim()
										? 'bg-gray-900 dark:bg-white text-white dark:text-black hover:bg-gray-800 dark:hover:bg-gray-200'
										: 'bg-gray-100 dark:bg-white/6 text-gray-400 dark:text-gray-600 cursor-default'}"
									disabled={!commitSummary.trim() || !stagedFiles.length || loading}
									onclick={doCommit}
								>
									{#if stagedFiles.length}
										{$t('git.commitFilesToBranch', {
											count: stagedFiles.length,
											branch: gitStatus.branch
										})}
									{:else}
										{$t('git.commitToBranch', { branch: gitStatus.branch })}
									{/if}
								</button>
							</div>
						{:else}
							<!-- History: commit list -->
							<div class="flex-1 overflow-y-auto">
								{#each commits as c, i}
									{#if i === unpushedCount && unpushedCount > 0}
										<div
											class="flex items-center gap-2 px-2.5 py-1 border-b border-gray-100 dark:border-white/4 bg-gray-50/50 dark:bg-white/2"
										>
											<Icon
												name="upload"
												size={10}
												class="text-gray-400 dark:text-gray-600 shrink-0"
											/>
											<span class="text-[10px] text-gray-400 dark:text-gray-600">
												{unpushedCount} unpushed {unpushedCount === 1 ? 'commit' : 'commits'}
											</span>
										</div>
									{/if}
									<button
										class="group flex items-center gap-1.5 w-full px-2.5 py-1.5 text-left border-b border-gray-50 dark:border-white/3 transition-colors duration-75
											{selectedCommit?.hash === c.hash
											? 'bg-gray-100 dark:bg-white/8'
											: 'hover:bg-gray-50 dark:hover:bg-white/3'}"
										onclick={() => selectCommit(c)}
									>
										{#if i < unpushedCount}
											<span
												class="w-1.5 h-1.5 rounded-full bg-blue-500 dark:bg-blue-400 shrink-0"
												title="Unpushed"
											></span>
										{/if}
										<div class="flex flex-col min-w-0 flex-1">
											<span class="text-xs text-gray-800 dark:text-gray-200 truncate w-full"
												>{c.message}</span
											>
											<span class="text-[10px] text-gray-400 dark:text-gray-600 font-mono"
												>{c.short_hash} · {c.author} · {relTime(c.date)}</span
											>
										</div>
										<!-- svelte-ignore a11y_no_static_element_interactions -->
										<span
											class="flex items-center justify-center w-5 h-5 rounded shrink-0 opacity-0 group-hover:opacity-100 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-200 dark:hover:bg-white/10 transition-all duration-75"
											role="button"
											tabindex="-1"
											onclick={(e) => openCommitMenu(e, c, i === 0)}
											aria-label={$t('files.moreActions')}
										>
											<Icon name="three-dots" size={12} />
										</span>
									</button>
								{/each}
								{#if !commits.length}
									<div
										class="flex items-center justify-center h-full text-[11px] text-gray-400 dark:text-gray-600"
									>
										{$t('git.noCommits')}
									</div>
								{/if}
							</div>
						{/if}
					</div>

					<!-- Right pane: diff viewer -->
					<div
						class="flex-1 overflow-hidden font-mono text-[11px] leading-[18px]
						{showDiff ? 'flex flex-col' : 'hidden md:flex md:flex-col'}"
					>
						{#if fileDiff.length}
							<div
								class="hidden md:flex items-center h-6 px-2 border-b border-gray-100 dark:border-white/4 shrink-0"
							>
								<span class="text-[10px] text-gray-400 dark:text-gray-600 font-mono truncate">
									{#if selectedCommit}
										{selectedCommit.short_hash} · {selectedCommit.message}
									{:else}
										{selectedFile}
									{/if}
								</span>
							</div>
							<div class="flex-1 overflow-auto">
								<div class="diff-content">
									{#each fileDiff as df}
										{#if fileDiff.length > 1}
											<div
												class="px-2 py-1 text-[10px] text-gray-500 dark:text-gray-400 bg-white dark:bg-[#1a1a1a] border-b border-gray-100 dark:border-white/4 sticky top-0 z-10 font-medium"
											>
												{df.path}
											</div>
										{/if}
										{#each df.hunks as hunk}
											<div
												class="px-2 py-0.5 text-gray-400 dark:text-gray-600 bg-gray-50 dark:bg-white/3 border-b border-gray-100 dark:border-white/4 w-full"
											>
												{hunk.header}
											</div>
											{#each groupLines(hunk.lines) as group}
												<div class="w-full {blockClass(group.type)}">
													{#each group.lines as line}
														<div class="px-2 whitespace-pre-wrap break-all">
															<span
																class={line.type === 'added'
																	? 'text-green-600 dark:text-green-400'
																	: line.type === 'removed'
																		? 'text-red-500 dark:text-red-400'
																		: 'text-gray-400 dark:text-gray-600'}
																>{line.type === 'added'
																	? '+'
																	: line.type === 'removed'
																		? '-'
																		: ' '}</span
															><span
																class={line.type === 'added'
																	? 'text-green-900 dark:text-green-300'
																	: line.type === 'removed'
																		? 'text-red-900 dark:text-red-300'
																		: 'text-gray-600 dark:text-gray-400'}>{line.content}</span
															>
														</div>
													{/each}
												</div>
											{/each}
										{/each}
									{/each}
								</div>
							</div>
						{:else}
							<div class="flex items-center justify-center h-full">
								{#if view === 'history' && !selectedCommit}
									<span class="text-[11px] text-gray-400 dark:text-gray-600"
										>{$t('git.selectCommit')}</span
									>
								{:else if totalChanges}
									<span class="text-[11px] text-gray-400 dark:text-gray-600"
										>{$t('git.selectFile')}</span
									>
								{:else}
									<span class="text-[11px] text-gray-400 dark:text-gray-600 font-sans"
										>{$t('git.noLocalChanges')}</span
									>
								{/if}
							</div>
						{/if}
					</div>
				</div>
			</div>
		{/if}
	</div>
{/if}

{#if pendingCheckoutBranch}
	<Modal onclose={() => (pendingCheckoutBranch = null)} class="w-full max-w-sm mx-4">
		<div class="p-4">
			<h2 class="text-sm font-medium text-gray-900 dark:text-white">Switch branches?</h2>
			<p class="mt-1.5 text-xs leading-relaxed text-gray-500 dark:text-gray-400">
				You have {totalChanges} changed {totalChanges === 1 ? 'file' : 'files'} on
				<span class="font-mono text-gray-700 dark:text-gray-300">{gitStatus?.branch}</span>. Choose
				whether to leave those changes here or bring them to
				<span class="font-mono text-gray-700 dark:text-gray-300">{pendingCheckoutBranch}</span>.
			</p>
			<div class="mt-4 flex items-center justify-end gap-2">
				<button
					class="px-2.5 py-1 text-xs text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 transition-colors"
					onclick={() => (pendingCheckoutBranch = null)}
				>
					Cancel
				</button>
				<button
					class="px-2.5 py-1 text-xs text-gray-500 hover:text-gray-900 dark:text-gray-400 dark:hover:text-white transition-colors"
					onclick={() => performBranchCheckout(pendingCheckoutBranch!, 'leave')}
					disabled={loading}
				>
					Leave changes
				</button>
				<button
					class="px-3.5 py-1.5 text-xs bg-black hover:bg-gray-900 text-white dark:bg-white dark:text-black dark:hover:bg-gray-100 transition-colors rounded-full disabled:opacity-50"
					onclick={() => performBranchCheckout(pendingCheckoutBranch!, 'bring')}
					disabled={loading}
				>
					Bring changes
				</button>
			</div>
		</div>
	</Modal>
{/if}

{#if contextMenu}
	<DropdownMenu
		anchor={contextMenu.anchor}
		items={[
			{
				label: $t('git.discard'),
				icon: 'xmark',
				onclick: () => discardFile(contextMenu!.file.path)
			},
			{
				label: $t('git.copyFilePath'),
				icon: 'copy',
				onclick: () => copyFilePath(contextMenu!.file.path)
			},
			{
				label: $t('git.copyRelativePath'),
				icon: 'copy',
				onclick: () => copyRelativePath(contextMenu!.file.path)
			}
		]}
		onclose={closeContextMenu}
	/>
{/if}

{#if commitMenu}
	<DropdownMenu
		anchor={commitMenu.anchor}
		items={[
			...(commitMenu.isLatest
				? [
						{
							label: $t('git.undoCommit'),
							icon: 'undo',
							onclick: () => {
								doUncommit();
								closeCommitMenu();
							}
						}
					]
				: []),
			{
				label: $t('git.copyCommitHash'),
				icon: 'copy',
				onclick: () => {
					navigator.clipboard.writeText(commitMenu!.commit.hash);
					flash($t('git.copiedPath'));
					closeCommitMenu();
				}
			}
		]}
		onclose={closeCommitMenu}
	/>
{/if}

<style>
	.diff-content {
		width: max-content;
		min-width: 100%;
	}

	.diff-gutter-removed {
		border-left: 3px solid transparent;
		border-image: repeating-linear-gradient(
				-45deg,
				#ef4444 0,
				#ef4444 1px,
				transparent 1px,
				transparent 3px
			)
			3;
	}

	.git-resize-handle {
		position: absolute;
		top: -3px;
		left: 0;
		right: 0;
		height: 6px;
		cursor: row-resize;
		z-index: 10;
		transition: background 0.15s;
	}

	.git-resize-handle:hover,
	.git-resize-handle.active {
		background: rgba(150, 150, 150, 0.12);
	}
</style>
