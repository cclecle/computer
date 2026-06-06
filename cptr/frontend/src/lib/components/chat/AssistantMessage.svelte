<script lang="ts">
	import { tick } from 'svelte';
	import { slide } from 'svelte/transition';
	import { quintOut } from 'svelte/easing';
	import MarkdownRenderer from '$lib/components/markdown/MarkdownRenderer.svelte';
	import OutputEditView from './OutputEditView.svelte';

	interface Props {
		content: string;
		done: boolean;
		output: any[] | null;
		chatId: string | null;
		messageId: string;
		siblingIndex?: number;
		siblingTotal?: number;
		onapprove: (messageId: string, callId: string, approved: boolean) => void;
		onnavigate?: (direction: -1 | 1) => void;
		onregenerate?: () => void;
		onedit?: (content: string, output: any[] | null, submit: boolean) => void;
	}
	let {
		content, done, output, chatId, messageId,
		siblingIndex = 0, siblingTotal = 1,
		onapprove, onnavigate, onregenerate, onedit
	}: Props = $props();

	let edit = $state(false);
	let editedContent = $state('');
	let editedOutput = $state<any[] | null>(null);
	let copied = $state(false);
	let textareaEl: HTMLTextAreaElement;

	// Track which tool call outputs are expanded
	let expandedCalls = $state<Set<string>>(new Set());
	// Track which groups are expanded
	let expandedGroups = $state<Set<number>>(new Set());

	function toggleCallExpanded(callId: string) {
		const next = new Set(expandedCalls);
		if (next.has(callId)) next.delete(callId);
		else next.add(callId);
		expandedCalls = next;
	}

	function toggleGroupExpanded(groupIdx: number) {
		const next = new Set(expandedGroups);
		if (next.has(groupIdx)) next.delete(groupIdx);
		else next.add(groupIdx);
		expandedGroups = next;
	}

	async function startEdit() {
		edit = true;
		if (output?.length) {
			editedOutput = JSON.parse(JSON.stringify(output));
		} else {
			editedContent = content;
		}
		await tick();
		if (!editedOutput && textareaEl) {
			textareaEl.style.height = '';
			textareaEl.style.height = `${textareaEl.scrollHeight}px`;
			textareaEl.focus();
		}
	}

	function cancelEdit() {
		edit = false;
		editedContent = '';
		editedOutput = null;
	}

	function saveEdit() {
		if (editedOutput) {
			onedit?.(content, editedOutput, false);
		} else {
			onedit?.(editedContent, null, false);
		}
		edit = false;
		editedContent = '';
		editedOutput = null;
	}

	function saveAsCopy() {
		if (editedOutput) {
			onedit?.(content, editedOutput, true);
		} else {
			onedit?.(editedContent, null, true);
		}
		edit = false;
		editedContent = '';
		editedOutput = null;
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') cancelEdit();
	}

	function autoResize(e: Event) {
		const el = e.target as HTMLTextAreaElement;
		el.style.height = '';
		el.style.height = `${el.scrollHeight}px`;
	}

	function copyContent() {
		const text = (output || [])
			.filter((i: any) => i.type === 'message')
			.flatMap((i: any) => i.content || [])
			.map((c: any) => c.text)
			.join('') || content;
		navigator.clipboard.writeText(text);
		copied = true;
		setTimeout(() => { copied = false; }, 1500);
	}

	/** Human-readable label for a tool call */
	function toolLabel(name: string, args: any): string {
		switch (name) {
			case 'read_file': {
				const range = args.start_line ? ` L${args.start_line}–${args.end_line || 'end'}` : '';
				return `Read ${args.path || '?'}${range}`;
			}
			case 'edit_file': return `Edit ${args.path || '?'}`;
			case 'multi_edit_file': return `Multi-edit ${args.path || '?'}`;
			case 'create_file': return `Create ${args.path || '?'}`;
			case 'write_file': return `Write ${args.path || '?'}`;
			case 'list_directory': return `List ${args.path || '.'}${args.recursive ? ' (recursive)' : ''}`;
			case 'search_files': {
				const scope = args.include ? ` in ${args.include}` : '';
				return `Search "${args.query || '?'}"${scope}`;
			}
			case 'run_command': return args.background ? `Background: ${args.command || '?'}` : (args.command || '?');
			case 'check_task': return `Check task ${args.task_id || '?'}`;
			case 'kill_task': return `Kill task ${args.task_id || '?'}`;
			case 'web_search': return `Search web: "${args.query || '?'}"`;
			case 'read_url': {
				try { return `Fetch ${new URL(args.url).hostname}`; } catch { return `Fetch URL`; }
			}
			default: return name;
		}
	}

	// ── Consecutive grouping logic ────────────────────────────────
	// Groups consecutive function_call items together, breaking on message items.

	interface ToolGroup {
		type: 'tool_group';
		calls: any[];         // function_call items
		outputs: Map<string, any>; // call_id → function_call_output
	}

	interface MessageItem {
		type: 'message_item';
		item: any;
	}

	type DisplayItem = ToolGroup | MessageItem;

	const displayItems = $derived.by((): DisplayItem[] => {
		if (!output?.length) return [];

		const items: DisplayItem[] = [];
		let currentGroup: ToolGroup | null = null;

		// Collect all function_call_output items for lookup
		const outputMap = new Map<string, any>();
		for (const item of output) {
			if (item.type === 'function_call_output' && item.call_id) {
				outputMap.set(item.call_id, item);
			}
		}

		const flushGroup = () => {
			if (currentGroup && currentGroup.calls.length > 0) {
				items.push(currentGroup);
				currentGroup = null;
			}
		};

		for (const item of output) {
			if (item.type === 'function_call') {
				if (!currentGroup) {
					currentGroup = { type: 'tool_group', calls: [], outputs: outputMap };
				}
				currentGroup.calls.push(item);
			} else if (item.type === 'message') {
				flushGroup();
				items.push({ type: 'message_item', item });
			}
			// function_call_output items are handled via outputMap, skip standalone render
		}
		flushGroup();

		return items;
	});

	/** Summary text for a tool group header */
	function groupSummaryText(calls: any[]): string {
		if (calls.length <= 3) {
			// Show individual human-readable labels for small groups
			return calls.map((c: any) => toolLabel(c.name || 'tool', c.arguments || {})).join(', ');
		}
		// For larger groups, show counts by tool type
		const nameCounts: Record<string, number> = {};
		for (const c of calls) {
			const name = c.name || 'tool';
			nameCounts[name] = (nameCounts[name] || 0) + 1;
		}
		return Object.entries(nameCounts)
			.map(([name, count]) => count > 1 ? `${count} ${name}` : name)
			.join(', ');
	}

	function groupHasPending(calls: any[]): boolean {
		return !done && calls.some((c: any) => c.status !== 'completed' && c.status !== 'rejected');
	}

	function groupAllDone(calls: any[]): boolean {
		return calls.every((c: any) => c.status === 'completed');
	}

	function groupHasRejected(calls: any[]): boolean {
		return calls.some((c: any) => c.status === 'rejected');
	}
</script>

<div class="flex flex-col gap-1">
	{#if edit}
		<!-- Edit mode -->
		<div class="w-full">
			<div class="bg-gray-50 dark:bg-white/4 rounded-xl border border-gray-200 dark:border-white/8 px-3.5 py-2.5">
				{#if editedOutput}
					<OutputEditView output={editedOutput} onChange={(updated: any) => { editedOutput = updated; }} />
				{:else}
					<textarea
						bind:this={textareaEl}
						bind:value={editedContent}
						class="w-full bg-transparent outline-none resize-none text-[13px] leading-relaxed text-gray-900 dark:text-gray-200"
						oninput={autoResize}
						onkeydown={handleKeydown}
						rows="1"
					></textarea>
				{/if}
			</div>
			<div class="flex justify-between mt-2 text-[12px] font-medium">
				<button
					class="px-3 py-1 rounded-lg text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300 transition-colors duration-100"
					onclick={saveAsCopy}
				>Save As</button>
				<div class="flex gap-1.5">
					<button
						class="px-3 py-1 rounded-lg text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300 transition-colors duration-100"
						onclick={cancelEdit}
					>Cancel</button>
					<button
						class="px-3 py-1 rounded-lg bg-gray-900 dark:bg-white text-white dark:text-black hover:bg-gray-700 dark:hover:bg-gray-200 transition-colors duration-100"
						onclick={saveEdit}
					>Save</button>
				</div>
			</div>
		</div>
	{:else}
		<!-- Normal display -->
		<div>
		{#if !done && (!output || output.length === 0)}
			<MarkdownRenderer {content} /><span class="inline-block w-[2px] h-3.5 bg-gray-400 dark:bg-gray-500 ml-0.5 animate-pulse align-text-bottom"></span>
		{:else}
			{#each displayItems as displayItem, groupIdx}
				{#if displayItem.type === 'message_item'}
					<MarkdownRenderer content={displayItem.item.content?.map((c: any) => c.text).join('') || ''} />

				{:else if displayItem.type === 'tool_group'}
					{@const calls = displayItem.calls}
					{@const outputs = displayItem.outputs}
					{@const hasPending = groupHasPending(calls)}
					{@const allDone = groupAllDone(calls)}
					{@const hasRejected = groupHasRejected(calls)}
					{@const isGroupOpen = expandedGroups.has(groupIdx)}
					{@const hasPendingApproval = calls.some((c: any) => c.status === 'pending')}

					<div class="w-full">
						<!-- Group header -->
						<button
							class="w-fit text-left text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 transition cursor-pointer"
							aria-label="Toggle tool calls"
							aria-expanded={isGroupOpen}
							onclick={() => toggleGroupExpanded(groupIdx)}
						>
							<div class="flex items-center gap-1.5 text-sm {hasPending ? 'shimmer' : ''}">
								<!-- Status icon -->
								{#if hasPending}
									<div class="flex justify-center text-center">
										<svg aria-hidden="true" class="size-4" viewBox="0 0 24 24" fill="currentColor" xmlns="http://www.w3.org/2000/svg">
											<style>.spinner_tc{transform-origin:center;animation:spinner_tc_a .75s infinite linear}@keyframes spinner_tc_a{100%{transform:rotate(360deg)}}</style>
											<path d="M12,1A11,11,0,1,0,23,12,11,11,0,0,0,12,1Zm0,19a8,8,0,1,1,8-8A8,8,0,0,1,12,20Z" opacity=".25" />
											<path d="M10.14,1.16a11,11,0,0,0-9,8.92A1.59,1.59,0,0,0,2.46,12,1.52,1.52,0,0,0,4.11,10.7a8,8,0,0,1,6.66-6.61A1.42,1.42,0,0,0,12,2.69h0A1.57,1.57,0,0,0,10.14,1.16Z" class="spinner_tc" />
										</svg>
									</div>
								{:else if allDone}
									<div class="text-emerald-500 dark:text-emerald-400">
										<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="size-4">
											<path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75 11.25 15 15 9.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
										</svg>
									</div>
								{:else if hasRejected}
									<div class="text-red-400 dark:text-red-500">
										<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor" class="size-4">
											<path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
										</svg>
									</div>
								{:else}
									<div class="text-gray-400 dark:text-gray-500">
										<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.75" stroke="currentColor" class="size-3.5">
											<path stroke-linecap="round" stroke-linejoin="round" d="M11.42 15.17l-5.645 5.646a.5.5 0 01-.707 0l-1.884-1.884a.5.5 0 010-.707l5.646-5.645m6.607-6.607l-5.645 5.646m5.645-5.646a2.121 2.121 0 013 3l-5.646 5.646"/>
										</svg>
									</div>
								{/if}

								<!-- Summary text -->
								<div class="flex-1 line-clamp-1">
									<span class="text-gray-600 dark:text-gray-300">{hasPending ? 'Exploring' : 'Explored'}</span>
									{#if groupSummaryText(calls)}
										<span class="text-gray-400 dark:text-gray-500 ml-1">{groupSummaryText(calls)}</span>
									{/if}
								</div>

								<!-- Chevron -->
								<div class="flex shrink-0 self-center text-gray-400 dark:text-gray-500">
									<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="3.5" stroke="currentColor"
										class="size-3 transition-transform duration-200 {isGroupOpen ? 'rotate-180' : ''}">
										<path stroke-linecap="round" stroke-linejoin="round" d="m19.5 8.25-7.5 7.5-7.5-7.5" />
									</svg>
								</div>
							</div>
						</button>

						<!-- Expanded group content -->
						{#if isGroupOpen}
							<div transition:slide={{ duration: 300, easing: quintOut, axis: 'y' }}>
								<div class="mb-0.5 space-y-0.5 mt-1">
									{#each calls as item}
										{@const args = item.arguments || {}}
										{@const toolName = item.name}
										{@const callId = item.call_id || toolName}
										{@const isExecuting = item.status === 'running' || (!item.status && !done)}
										{@const isDone = item.status === 'completed'}
										{@const isRejected = item.status === 'rejected'}
										{@const isPending = item.status === 'pending'}
										{@const isExpanded = expandedCalls.has(callId)}
										{@const pairedOutput = outputs.get(item.call_id)}

										<div class="w-full">
											<!-- Individual tool call row -->
											<button
												class="w-fit text-left text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 transition cursor-pointer"
												onclick={() => toggleCallExpanded(callId)}
											>
												<div class="flex items-center gap-1.5 text-sm {isExecuting ? 'shimmer' : ''}">
													<!-- Status icon -->
													{#if isExecuting}
														<div class="flex justify-center text-center">
															<svg aria-hidden="true" class="size-4" viewBox="0 0 24 24" fill="currentColor" xmlns="http://www.w3.org/2000/svg">
																<style>.spinner_inner{transform-origin:center;animation:spinner_inner_a .75s infinite linear}@keyframes spinner_inner_a{100%{transform:rotate(360deg)}}</style>
																<path d="M12,1A11,11,0,1,0,23,12,11,11,0,0,0,12,1Zm0,19a8,8,0,1,1,8-8A8,8,0,0,1,12,20Z" opacity=".25" />
																<path d="M10.14,1.16a11,11,0,0,0-9,8.92A1.59,1.59,0,0,0,2.46,12,1.52,1.52,0,0,0,4.11,10.7a8,8,0,0,1,6.66-6.61A1.42,1.42,0,0,0,12,2.69h0A1.57,1.57,0,0,0,10.14,1.16Z" class="spinner_inner" />
															</svg>
														</div>
													{:else if isDone}
														<div class="text-emerald-500 dark:text-emerald-400">
															<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="size-4">
																<path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75 11.25 15 15 9.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
															</svg>
														</div>
													{:else if isRejected}
														<div class="text-red-400 dark:text-red-500">
															<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor" class="size-4">
																<path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
															</svg>
														</div>
													{:else}
														<div class="text-gray-400 dark:text-gray-500">
															<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.75" stroke="currentColor" class="size-3.5">
																<path stroke-linecap="round" stroke-linejoin="round" d="M11.42 15.17l-5.645 5.646a.5.5 0 01-.707 0l-1.884-1.884a.5.5 0 010-.707l5.646-5.645m6.607-6.607l-5.645 5.646m5.645-5.646a2.121 2.121 0 013 3l-5.646 5.646"/>
															</svg>
														</div>
													{/if}

													<!-- Label -->
													<div class="flex-1 line-clamp-1">
														<span class="font-normal">{toolLabel(toolName, args)}</span>
													</div>

													<!-- Right side: approval buttons or chevron -->
													{#if isPending && chatId}
														<!-- Approval buttons -->
														<span class="flex gap-1 shrink-0" onclick={(e) => e.stopPropagation()}>
															<button
																class="text-[11px] px-2.5 py-0.5 rounded-md
																	text-gray-600 dark:text-gray-300
																	bg-gray-100 dark:bg-white/8
																	hover:bg-gray-200 dark:hover:bg-white/12
																	transition-colors duration-100"
																onclick={() => onapprove(messageId, item.call_id, true)}
															>Allow</button>
															<button
																class="text-[11px] px-2 py-0.5 rounded-md
																	text-gray-400 dark:text-gray-500
																	hover:text-gray-600 dark:hover:text-gray-300
																	transition-colors duration-100"
																onclick={() => onapprove(messageId, item.call_id, false)}
															>Deny</button>
														</span>
													{:else}
														<!-- Chevron -->
														<div class="flex shrink-0 self-center translate-y-[1px]">
															<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="3.5" stroke="currentColor"
																class="size-3 transition-transform duration-200 text-gray-400 dark:text-gray-500 {isExpanded ? 'rotate-180' : ''}">
																<path stroke-linecap="round" stroke-linejoin="round" d="m19.5 8.25-7.5 7.5-7.5-7.5" />
															</svg>
														</div>
													{/if}
												</div>
											</button>

											<!-- Expanded detail panel -->
											{#if isExpanded}
												<div transition:slide={{ duration: 300, easing: quintOut, axis: 'y' }}>
													<div class="border border-gray-50 dark:border-gray-850/30 rounded-2xl my-1.5 p-3 space-y-3">
														<!-- Input section -->
														{#if Object.keys(args).length > 0}
															<div>
																<div class="text-[10px] uppercase tracking-wider text-gray-400 dark:text-gray-500 mb-1.5 px-1">
																	Input
																</div>
																{#if toolName === 'edit_file' && args.target}
																	<!-- Diff view for edits -->
																	<div class="text-[11px] font-mono rounded-lg overflow-hidden border border-gray-200/60 dark:border-white/6">
																		<div class="bg-red-50/80 dark:bg-red-950/20 text-red-700 dark:text-red-400 px-2.5 py-1 whitespace-pre-wrap break-all leading-relaxed">
																			<span class="select-none text-red-400 dark:text-red-600 mr-1">−</span>{args.target.length > 500 ? args.target.slice(0, 500) + '…' : args.target}
																		</div>
																		<div class="bg-green-50/80 dark:bg-green-950/20 text-green-700 dark:text-green-400 px-2.5 py-1 whitespace-pre-wrap break-all leading-relaxed">
																			<span class="select-none text-green-400 dark:text-green-600 mr-1">+</span>{(args.replacement || '').length > 500 ? args.replacement.slice(0, 500) + '…' : args.replacement || ''}
																		</div>
																	</div>
																	{#if args.start_line}
																		<div class="text-[10px] text-gray-400 dark:text-gray-600 mt-1 px-1">Lines {args.start_line}–{args.end_line || 'end'}</div>
																	{/if}
																{:else if toolName === 'run_command'}
																	<code class="block text-xs font-mono text-gray-600 dark:text-gray-300 bg-gray-50 dark:bg-gray-900 rounded-lg px-2.5 py-1.5">{args.command}</code>
																{:else}
																	<!-- Key-value pairs -->
																	<div class="px-1 space-y-0.5">
																		{#each Object.entries(args) as [key, value]}
																			<div class="flex gap-2 text-xs py-0.5">
																				<span class="text-gray-600 dark:text-gray-400 shrink-0">{key}</span>
																				<span class="text-gray-800 dark:text-gray-200 break-all">
																					{typeof value === 'object' ? JSON.stringify(value) : value}
																				</span>
																			</div>
																		{/each}
																	</div>
																{/if}
															</div>
														{/if}

														<!-- Output section -->
														{#if pairedOutput?.output}
															<div>
																<div class="text-[10px] uppercase tracking-wider text-gray-400 dark:text-gray-500 mb-1.5 px-1">
																	Output
																</div>
																<div class="w-full max-w-none">
																	<pre class="text-xs text-gray-600 dark:text-gray-300 whitespace-pre-wrap break-words font-mono max-h-64 overflow-auto leading-relaxed">{pairedOutput.output.length > 10000 ? pairedOutput.output.slice(0, 10000) : pairedOutput.output}</pre>
																	{#if pairedOutput.output.length > 10000}
																		<div class="text-[10px] text-gray-400 dark:text-gray-600 mt-1 px-1">{pairedOutput.output.length.toLocaleString()} total characters</div>
																	{/if}
																</div>
															</div>
														{/if}
													</div>
												</div>
											{/if}
										</div>
									{/each}
								</div>
							</div>
						{/if}

						<!-- Show approval buttons outside group when collapsed & has pending -->
						{#if !isGroupOpen && hasPendingApproval && chatId}
							<div class="mt-1 space-y-0.5">
								{#each calls.filter((c: any) => c.status === 'pending') as item}
									<div class="flex items-center gap-2 py-1 px-1">
										<span class="text-xs text-gray-500 dark:text-gray-400 flex-1 line-clamp-1">{toolLabel(item.name, item.arguments || {})}</span>
										<span class="flex gap-1 shrink-0">
											<button
												class="text-[11px] px-2.5 py-0.5 rounded-md
													text-gray-600 dark:text-gray-300
													bg-gray-100 dark:bg-white/8
													hover:bg-gray-200 dark:hover:bg-white/12
													transition-colors duration-100"
												onclick={() => onapprove(messageId, item.call_id, true)}
											>Allow</button>
											<button
												class="text-[11px] px-2 py-0.5 rounded-md
													text-gray-400 dark:text-gray-500
													hover:text-gray-600 dark:hover:text-gray-300
													transition-colors duration-100"
												onclick={() => onapprove(messageId, item.call_id, false)}
											>Deny</button>
										</span>
									</div>
								{/each}
							</div>
						{/if}
					</div>
				{/if}
			{/each}
			{#if !done}
				{@const flushedText = (output || [])
					.filter((i: any) => i.type === 'message')
					.flatMap((i: any) => i.content || [])
					.map((c: any) => c.text)
					.join('')}
				{@const pendingText = content.slice(flushedText.length)}
				{#if pendingText}
					<MarkdownRenderer content={pendingText} />
				{/if}
				<span class="inline-block w-[2px] h-3.5 bg-gray-400 dark:bg-gray-500 ml-0.5 animate-pulse align-text-bottom"></span>
			{/if}
		{/if}
		</div>

		<!-- Controls toolbar -->
		{#if done || siblingTotal > 1}
			<div class="flex items-center gap-1 mt-1 -ml-0.5">
				{#if siblingTotal > 1}
					<button
						class="p-0.5 rounded text-gray-400 dark:text-gray-600 hover:text-gray-600 dark:hover:text-gray-300 disabled:opacity-30 disabled:cursor-default transition-colors duration-100"
						disabled={siblingIndex === 0}
						onclick={() => onnavigate?.(-1)}
						aria-label="Previous response"
					>
						<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"/></svg>
					</button>
					<span class="text-[11px] tabular-nums text-gray-400 dark:text-gray-600 select-none">{siblingIndex + 1}/{siblingTotal}</span>
					<button
						class="p-0.5 rounded text-gray-400 dark:text-gray-600 hover:text-gray-600 dark:hover:text-gray-300 disabled:opacity-30 disabled:cursor-default transition-colors duration-100"
						disabled={siblingIndex === siblingTotal - 1}
						onclick={() => onnavigate?.(1)}
						aria-label="Next response"
					>
						<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/></svg>
					</button>
				{/if}
				{#if done && onedit}
					<button
						class="p-0.5 rounded text-gray-400 dark:text-gray-600 hover:text-gray-600 dark:hover:text-gray-300 transition-colors duration-100"
						onclick={startEdit}
						aria-label="Edit response"
					>
						<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L6.832 19.82a4.5 4.5 0 01-1.897 1.13l-2.685.8.8-2.685a4.5 4.5 0 011.13-1.897L16.863 4.487zm0 0L19.5 7.125"/></svg>
					</button>
				{/if}
				{#if done}
					<button
						class="p-0.5 rounded text-gray-400 dark:text-gray-600 hover:text-gray-600 dark:hover:text-gray-300 transition-colors duration-100"
						onclick={copyContent}
						aria-label="Copy response"
					>
						{#if copied}
							<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor" class="w-3.5 h-3.5"><path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" /></svg>
						{:else}
							<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="w-3.5 h-3.5"><path stroke-linecap="round" stroke-linejoin="round" d="M15.666 3.888A2.25 2.25 0 0013.5 2.25h-3c-1.03 0-1.9.693-2.166 1.638m7.332 0c.055.194.084.4.084.612v0a.75.75 0 01-.75.75H9a.75.75 0 01-.75-.75v0c0-.212.03-.418.084-.612m7.332 0c.646.049 1.288.11 1.927.184 1.1.128 1.907 1.077 1.907 2.185V19.5a2.25 2.25 0 01-2.25 2.25H6.75A2.25 2.25 0 014.5 19.5V6.257c0-1.108.806-2.057 1.907-2.185a48.208 48.208 0 011.927-.184" /></svg>
						{/if}
					</button>
				{/if}
				{#if done && onregenerate}
					<button
						class="p-0.5 rounded text-gray-400 dark:text-gray-600 hover:text-gray-600 dark:hover:text-gray-300 transition-colors duration-100"
						onclick={onregenerate}
						aria-label="Regenerate response"
					>
						<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>
					</button>
				{/if}
			</div>
		{/if}
	{/if}
</div>
