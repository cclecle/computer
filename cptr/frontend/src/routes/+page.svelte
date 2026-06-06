<script lang="ts">
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { currentWorkspace, activeTab, workspaceList, addWorkspace, loadWorkspace, gitReviewOpen, setActiveGroup, setSplitRatio, moveTabToGroup, openInSplit, openTabInSplit, setSplitDirection } from '$lib/stores';
	import { splitActive } from '$lib/stores';
	import type { Tab, EditorGroup, WorkspaceState } from '$lib/stores';
	import { t } from '$lib/i18n';
	import { get } from 'svelte/store';
	import { getWelcome } from '$lib/apis/state';
	import { createSession } from '$lib/apis/terminal';
	import FileBrowser from '$lib/components/FileBrowser.svelte';
	import FileEditor from '$lib/components/FileEditor.svelte';
	import GitView from '$lib/components/GitView.svelte';
	import Terminal from '$lib/components/Terminal.svelte';
	import PortPreview from '$lib/components/PortPreview.svelte';
	import ChatPanel from '$lib/components/chat/ChatPanel.svelte';
	import DirectoryPicker from '$lib/components/DirectoryPicker.svelte';
	import GroupTabBar from '$lib/components/GroupTabBar.svelte';
	import Icon from '$lib/components/Icon.svelte';
	import SystemInfo from '$lib/components/SystemInfo.svelte';

	let showPicker = $state(false);

	// ── URL-driven workspace loading ───────────────────────────────
	// The workspace path comes from the URL query param: ?workspace=/path/to/dir
	// Each browser tab has its own URL → its own workspace.

	let lastLoadedPath = $state<string | null>(null);

	$effect(() => {
		const wsPath = $page.url.searchParams.get('workspace');
		if (wsPath && wsPath !== lastLoadedPath) {
			lastLoadedPath = wsPath;
			loadWorkspace(wsPath);
		} else if (!wsPath && lastLoadedPath !== null) {
			lastLoadedPath = null;
			currentWorkspace.set(null);
		}
	});

	// Welcome page data
	let welcomeData = $state<{
		hostname: string;
		platform: string;
		version: string;
		system: {
			os: string;
			arch: string;
			python: string;
			cpu_count: number;
			memory_total?: number;
			memory_available?: number;
			disk_total?: number;
			disk_used?: number;
			disk_free?: number;
			uptime_seconds?: number;
			load_avg?: number[];
			cpu_usage?: number;
			network?: { name: string; ip: string }[];
		};
		processes: { pid: number; cpu: number; mem: number; name: string }[];
		suggestions: { name: string; path: string }[];
		recent: { name: string; path: string }[];
	} | null>(null);

	// Fetch welcome data whenever no workspace is active
	$effect(() => {
		if (!$currentWorkspace) {
			getWelcome()
				.then((data) => { welcomeData = data; })
				.catch(() => {});
		}
	});

	// Lazy-init terminal sessions for any group's active tab
	let initingTerminal = $state(false);
	$effect(() => {
		const ws = $currentWorkspace;
		if (!ws || initingTerminal) return;

		// Find any terminal tab across all groups that needs a session
		for (const group of ws.groups) {
			const tab = group.tabs.find((t) => t.id === group.activeTabId);
			if (tab && tab.type === 'terminal' && !tab.sessionId) {
				initingTerminal = true;
				createSession(ws.path)
					.then((data) => {
						currentWorkspace.update((w) => {
							if (!w) return w;
							return {
								...w,
								groups: w.groups.map((g) => ({
									...g,
									tabs: g.tabs.map((t) =>
										t.id === tab.id ? { ...t, sessionId: data.session_id } : t
									),
								})),
							};
						});
					})
					.catch((e) => console.error('Failed to init terminal:', e))
					.finally(() => { initingTerminal = false; });
				return; // Only init one at a time
			}
		}
	});

	function quickOpen(path: string) {
		addWorkspace(path);
		goto(`/?workspace=${encodeURIComponent(path)}`);
	}

	function shortenPath(path: string): string {
		const home = welcomeData?.suggestions?.[0]?.path;
		if (home && path.startsWith(home)) {
			return '~' + path.slice(home.length);
		}
		return path;
	}

	// ── Draggable divider ──────────────────────────────────────────

	let isDragging = $state(false);
	let containerEl: HTMLDivElement | undefined = $state();

	function handleDividerPointerDown(e: PointerEvent) {
		e.preventDefault();
		isDragging = true;
		(e.target as HTMLElement).setPointerCapture(e.pointerId);
	}

	function handleDividerPointerMove(e: PointerEvent) {
		if (!isDragging || !containerEl) return;
		const rect = containerEl.getBoundingClientRect();
		const direction = $currentWorkspace?.splitDirection ?? 'horizontal';

		let ratio: number;
		if (direction === 'horizontal') {
			ratio = (e.clientX - rect.left) / rect.width;
		} else {
			ratio = (e.clientY - rect.top) / rect.height;
		}
		setSplitRatio(ratio);
	}

	function handleDividerPointerUp() {
		isDragging = false;
	}

	// Computed
	let isWideScreen = $state(typeof window !== 'undefined' ? window.innerWidth >= 1024 : false);

	$effect(() => {
		if (typeof window === 'undefined') return;
		function onResize() { isWideScreen = window.innerWidth >= 1024; }
		window.addEventListener('resize', onResize);
		return () => window.removeEventListener('resize', onResize);
	});

	const allGroups = $derived($currentWorkspace?.groups ?? []);
	const splitDirection = $derived($currentWorkspace?.splitDirection ?? 'horizontal');
	const splitRatio = $derived($currentWorkspace?.splitRatio ?? 0.5);

	// On mobile, collapse to just the active group
	const displayGroups = $derived(
		isWideScreen
			? allGroups
			: allGroups.filter((g) => g.id === $currentWorkspace?.activeGroupId).slice(0, 1)
	);
	const hasSplit = $derived(displayGroups.length > 1);

	function getGroupActiveTab(group: EditorGroup): Tab | null {
		return group.tabs.find((t) => t.id === group.activeTabId) ?? null;
	}

	// ── Drag-to-split ─────────────────────────────────────────────

	let dragOverZone = $state<'right' | 'bottom' | null>(null);

	function handleContainerDragOver(e: DragEvent) {
		if (!containerEl || !isWideScreen) return;
		// Only respond to tab drags, not file uploads
		if (!e.dataTransfer?.types.includes('text/tab-id')) return;
		// Only show drop zones when not already split
		if (hasSplit) return;

		e.preventDefault();
		const rect = containerEl.getBoundingClientRect();
		const xRatio = (e.clientX - rect.left) / rect.width;
		const yRatio = (e.clientY - rect.top) / rect.height;

		if (xRatio > 0.75) {
			dragOverZone = 'right';
		} else if (yRatio > 0.75) {
			dragOverZone = 'bottom';
		} else {
			dragOverZone = null;
		}
	}

	function handleContainerDragLeave(e: DragEvent) {
		// Only reset if leaving the container entirely
		if (containerEl && !containerEl.contains(e.relatedTarget as Node)) {
			dragOverZone = null;
		}
	}

	function handleContainerDrop(e: DragEvent) {
		if (!dragOverZone || !e.dataTransfer) {
			dragOverZone = null;
			return;
		}
		// Don't intercept file uploads
		if (e.dataTransfer.types.includes('Files')) {
			dragOverZone = null;
			return;
		}

		const tabId = e.dataTransfer.getData('text/tab-id');
		const fromGroupId = e.dataTransfer.getData('text/group-id');
		if (!tabId || !fromGroupId) {
			dragOverZone = null;
			return;
		}

		e.preventDefault();
		const direction = dragOverZone === 'right' ? 'horizontal' : 'vertical';
		setSplitDirection(direction as any);

		// Move the dragged tab into a new split pane
		const ws = $currentWorkspace;
		if (ws) {
			const sourceGroup = ws.groups.find((g) => g.id === fromGroupId);
			const tab = sourceGroup?.tabs.find((t) => t.id === tabId);
			if (tab) {
				openTabInSplit(tabId, direction as any);
			}
		}
		dragOverZone = null;
	}
</script>

{#if !$currentWorkspace}
	<div class="flex items-center justify-center h-full p-6 overflow-y-auto">
		<div class="w-full max-w-md">
			<!-- Header -->
			<div class="mb-4">
				<div class="flex items-baseline gap-2">
					<h1 class="text-lg font-semibold tracking-tight text-gray-900 dark:text-white">cptr</h1>
					{#if welcomeData?.version}
						<span class="text-[11px] text-gray-400 dark:text-gray-600 font-mono">v{welcomeData.version}</span>
					{/if}
				</div>
				{#if welcomeData?.hostname}
					<p class="text-xs text-gray-400 dark:text-gray-600 mt-0.5 font-mono">{welcomeData.hostname}</p>
				{/if}
			</div>

			<!-- System -->
			{#if welcomeData?.system}
				<div class="mb-6">
					<SystemInfo system={welcomeData.system} processes={welcomeData.processes} />
				</div>
			{/if}

			<!-- Start -->
			<div class="mb-6">
				<h2 class="text-xs text-gray-400 dark:text-gray-600 mb-2">{$t('home.start')}</h2>
				<button
					class="flex items-center gap-2 text-[13px] text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white transition-colors duration-100"
					onclick={() => showPicker = true}
				>
					<Icon name="folder" size={15} strokeWidth={1.3} />
					{$t('home.openFolder')}
				</button>
			</div>

			<!-- Recent -->
			{#if welcomeData?.recent?.length}
				<div class="mb-6">
					<h2 class="text-xs text-gray-400 dark:text-gray-600 mb-2">{$t('home.recent')}</h2>
					<div class="flex flex-col">
						{#each welcomeData.recent as item}
							<button
								class="flex items-center gap-3 py-1.5 group text-left transition-colors duration-100"
								onclick={() => quickOpen(item.path)}
							>
								<span class="text-[13px] text-gray-700 dark:text-gray-300 group-hover:text-gray-900 dark:group-hover:text-white">{item.name}</span>
								<span class="text-[11px] text-gray-400 dark:text-gray-600 font-mono">{shortenPath(item.path)}</span>
							</button>
						{/each}
					</div>
				</div>
			{/if}

			<!-- Suggestions -->
			{#if welcomeData?.suggestions?.length}
				<div>
					<h2 class="text-xs text-gray-400 dark:text-gray-600 mb-2">{$t('home.folders')}</h2>
					<div class="flex flex-col">
						{#each welcomeData.suggestions as item}
							<button
								class="flex items-center gap-2 py-1.5 text-[13px] text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white transition-colors duration-100"
								onclick={() => quickOpen(item.path)}
							>
								<Icon name="folder" size={14} strokeWidth={1.3} />
								<span>{item.name}</span>
								<span class="text-[11px] text-gray-400 dark:text-gray-600 font-mono">{shortenPath(item.path)}</span>
							</button>
						{/each}
					</div>
				</div>
			{/if}
		</div>
	</div>

	{#if showPicker}
		<DirectoryPicker onclose={() => showPicker = false} />
	{/if}
{:else}
	<!-- Editor groups layout -->
	<div
		bind:this={containerEl}
		class="split-container"
		class:split-horizontal={splitDirection === 'horizontal'}
		class:split-vertical={splitDirection === 'vertical'}
		class:is-dragging={isDragging}
		role="presentation"
		ondragover={handleContainerDragOver}
		ondragleave={handleContainerDragLeave}
		ondrop={handleContainerDrop}
	>
		{#each displayGroups as group, i (group.id)}
			{@const groupTab = getGroupActiveTab(group)}

			{#if i > 0}
				<!-- Divider between groups -->
				<!-- svelte-ignore a11y_no_static_element_interactions -->
				<div
					class="split-divider"
					class:split-divider-h={splitDirection === 'horizontal'}
					class:split-divider-v={splitDirection === 'vertical'}
					onpointerdown={handleDividerPointerDown}
					onpointermove={handleDividerPointerMove}
					onpointerup={handleDividerPointerUp}
					onpointercancel={handleDividerPointerUp}
				>
					<div class="split-divider-handle"></div>
				</div>
			{/if}

			<!-- svelte-ignore a11y_no_static_element_interactions -->
			<div
				class="split-pane"
				style={hasSplit
					? splitDirection === 'horizontal'
						? `width: ${i === 0 ? splitRatio * 100 : (1 - splitRatio) * 100}%;`
						: `height: ${i === 0 ? splitRatio * 100 : (1 - splitRatio) * 100}%;`
					: ''}
				onclick={() => setActiveGroup(group.id)}
			>
				<!-- Per-group tab bar -->
				<GroupTabBar {group} canClose={hasSplit} isPrimary={i === 0} />

				<!-- Tab content -->
				<div class="pane-content">
					{#if $gitReviewOpen && i === 0}
						<GitView />
					{:else}
						<!-- Persist all file editor instances so drafts survive tab switches -->
						{#each group.tabs.filter(t => t.type === 'file' && t.filePath) as tab (tab.id)}
							<div
								class="persisted-tab"
								class:persisted-tab-hidden={tab.id !== group.activeTabId}
							>
								<FileEditor filePath={tab.filePath} tabId={tab.id} />
							</div>
						{/each}

						<!-- Non-file tab content (rendered only when active) -->
						{#if !groupTab || groupTab.type === 'files'}
							<FileBrowser />
						{:else if groupTab.type === 'terminal' && groupTab.sessionId}
							{#key groupTab.sessionId}
								<Terminal sessionId={groupTab.sessionId} />
							{/key}
						{:else if groupTab.type === 'terminal' && !groupTab.sessionId}
							<div class="flex items-center justify-center h-full">
								<div class="w-5 h-5 border-2 border-gray-800 border-t-gray-400 rounded-full animate-spin"></div>
							</div>
						{:else if groupTab.type === 'chat'}
							{#key groupTab.id}
								<ChatPanel workspace={$currentWorkspace.path} chatId={groupTab.path?.startsWith('new-') || groupTab.path?.startsWith('pending-') ? undefined : groupTab.path} tabId={groupTab.id} />
							{/key}
						{:else if groupTab.type === 'preview' && groupTab.port}
							<PortPreview port={groupTab.port} />
						{/if}
					{/if}
				</div>
			</div>
		{/each}

		<!-- Drop zone indicators for drag-to-split -->
		{#if dragOverZone === 'right'}
			<div class="split-drop-zone split-drop-right"></div>
		{/if}
		{#if dragOverZone === 'bottom'}
			<div class="split-drop-zone split-drop-bottom"></div>
		{/if}
	</div>
{/if}

<style>
	@reference "../app.css";

	/* Container */
	.split-container {
		display: flex;
		width: 100%;
		height: 100%;
		position: relative;
		overflow: hidden;
	}

	.split-horizontal {
		flex-direction: row;
	}

	.split-vertical {
		flex-direction: column;
	}

	/* Panes */
	.split-pane {
		display: flex;
		flex-direction: column;
		overflow: hidden;
		min-width: 0;
		min-height: 0;
	}

	/* Single pane takes all space */
	.split-pane:only-child {
		flex: 1;
		width: 100%;
		height: 100%;
	}

	.pane-content {
		flex: 1;
		min-height: 0;
		min-width: 0;
		overflow: hidden;
		position: relative;
	}

	/* ── Divider ─────────────────────────────────────────────── */
	.split-divider {
		flex-shrink: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 10;
		position: relative;
	}

	.split-divider-h {
		width: 4px;
		cursor: col-resize;
	}

	.split-divider-v {
		height: 4px;
		cursor: row-resize;
	}

	.split-divider-handle {
		position: absolute;
		border-radius: 9999px;
		background: transparent;
		transition: background 150ms ease;
	}

	.split-divider-h .split-divider-handle {
		width: 2px;
		height: 32px;
		top: 50%;
		left: 50%;
		transform: translate(-50%, -50%);
	}

	.split-divider-v .split-divider-handle {
		height: 2px;
		width: 32px;
		top: 50%;
		left: 50%;
		transform: translate(-50%, -50%);
	}

	.split-divider::before {
		content: '';
		position: absolute;
		z-index: -1;
	}

	.split-divider-h::before {
		width: 1px;
		height: 100%;
		left: 50%;
		transform: translateX(-50%);
		background: oklch(0.92 0 0);
	}

	:global(.dark) .split-divider-h::before {
		background: rgba(255, 255, 255, 0.06);
	}

	.split-divider-v::before {
		height: 1px;
		width: 100%;
		top: 50%;
		transform: translateY(-50%);
		background: oklch(0.92 0 0);
	}

	:global(.dark) .split-divider-v::before {
		background: rgba(255, 255, 255, 0.06);
	}

	.split-divider:hover .split-divider-handle,
	.is-dragging .split-divider .split-divider-handle {
		background: oklch(0.6 0.15 250);
	}

	/* Drag state */
	.is-dragging {
		user-select: none;
	}

	.is-dragging.split-horizontal {
		cursor: col-resize;
	}

	.is-dragging.split-vertical {
		cursor: row-resize;
	}

	/* ── Drop zones for drag-to-split ─────────────────── */
	.split-drop-zone {
		position: absolute;
		z-index: 15;
		background: oklch(0.65 0.15 250 / 0.08);
		border: 2px dashed oklch(0.65 0.15 250 / 0.3);
		border-radius: 8px;
		pointer-events: none;
	}

	.split-drop-right {
		top: 8px;
		right: 8px;
		bottom: 8px;
		width: 45%;
	}

	.split-drop-bottom {
		left: 8px;
		right: 8px;
		bottom: 8px;
		height: 45%;
	}

	/* ── Persisted file editor tabs ────────────────────── */
	.persisted-tab {
		position: absolute;
		inset: 0;
		z-index: 1;
		overflow: hidden;
	}

	.persisted-tab-hidden {
		visibility: hidden;
		z-index: 0;
		pointer-events: none;
	}
</style>
