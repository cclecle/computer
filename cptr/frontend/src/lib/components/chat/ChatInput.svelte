<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { mount, unmount } from 'svelte';
	import { Editor } from '@tiptap/core';
	import StarterKit from '@tiptap/starter-kit';
	import { Markdown } from '@tiptap/markdown';
	import Placeholder from '@tiptap/extension-placeholder';
	import CodeBlockLowlight from '@tiptap/extension-code-block-lowlight';
	import { all, createLowlight } from 'lowlight';

	import { createFileMention, extractMentionedFiles, type FileMentionAttrs } from './FileMention';
	import { createSkillMention, extractMentionedSkills, type SkillMentionAttrs } from './SkillMention';
	import FileSuggestionPopup from './FileSuggestionPopup.svelte';
	import SkillSuggestionPopup from './SkillSuggestionPopup.svelte';
	import { searchFiles } from '$lib/apis/files';
	import { getSkills } from '$lib/apis/skills';
	import { uploadFile } from '$lib/apis/files';
	import ModelSelector from '../common/ModelSelector.svelte';
	import SendButton from './SendButton.svelte';
	import PlusMenu from './PlusMenu.svelte';
	import DictateButton from './DictateButton.svelte';
	import QueuedMessageItem from './QueuedMessageItem.svelte';
	import Icon from '../Icon.svelte';
	import { planMode } from '$lib/stores';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import { t } from '$lib/i18n';

	interface Props {
		inputText: string;
		selectedModel: string;
		sending: boolean;
		streaming?: boolean;
		workspace?: string;
		placeholder?: string;
		queuedMessages?: { id: string; content: string }[];
		onsend: () => void;
		oncancel?: () => void;
		onqueuesendnow?: (id: string) => void;
		onqueueedit?: (id: string) => void;
		onqueuedelete?: (id: string) => void;
	}
	let {
		inputText = $bindable(),
		selectedModel = $bindable(),
		sending,
		streaming = false,
		workspace = '',
		placeholder = 'Message...',
		queuedMessages = [],
		onsend,
		oncancel,
		onqueuesendnow,
		onqueueedit,
		onqueuedelete
	}: Props = $props();

	let editorEl: HTMLDivElement | undefined = $state();
	let editor: Editor | null = $state(null);

	// ── Lowlight setup ──────────────────────────────
	const lowlight = createLowlight(all);
	const _origHighlight = lowlight.highlight.bind(lowlight);
	lowlight.highlight = (lang: string, value: string, opts?: Record<string, unknown>) => {
		if (!lowlight.registered(lang)) return lowlight.highlightAuto(value);
		return _origHighlight(lang, value, opts);
	};

	// ── File Uploads ────────────────────────────────
	let attachedUploads = $state<{ id: string; name: string; url: string; type: string; loading?: boolean }[]>([]);
	let isDragging = $state(false);

	async function processFiles(files: File[]) {
		for (const file of files) {
			const id = Math.random().toString(36).substring(7);
			const isImage = file.type.startsWith('image/');
			const type = isImage ? 'image' : 'file';
			attachedUploads = [...attachedUploads, { id, name: file.name, url: '', type, loading: true }];
			
			try {
				const form = new FormData();
				form.append('file', file);
				const res = await uploadFile(form);
				if (res && res.id) {
					attachedUploads = attachedUploads.map(u => 
						u.id === id ? { ...u, id: res.id, url: res.url, loading: false } : u
					);
				} else {
					attachedUploads = attachedUploads.filter(u => u.id !== id);
				}
			} catch (err) {
				console.error("Upload failed", err);
				attachedUploads = attachedUploads.filter(u => u.id !== id);
			}
		}
	}

	function handleDrop(e: DragEvent) {
		e.preventDefault();
		isDragging = false;
		if (e.dataTransfer?.files) {
			processFiles(Array.from(e.dataTransfer.files));
		}
	}

	function handlePaste(e: ClipboardEvent) {
		if (e.clipboardData?.items) {
			const files: File[] = [];
			for (const item of Array.from(e.clipboardData.items)) {
				if (item.kind === 'file') {
					const file = item.getAsFile();
					if (file) files.push(file);
				}
			}
			if (files.length > 0) {
				e.preventDefault(); // Stop TipTap from inserting base64 strings
				processFiles(files);
			}
		}
	}

	function removeUpload(id: string) {
		attachedUploads = attachedUploads.filter(u => u.id !== id);
	}

	// ── @file mention suggestion ────────────────────
	let popupEl: HTMLDivElement | null = null;
	let popupComponent: Record<string, any> | null = null;
	let activeClientRectFn: (() => DOMRect | null) | null = null;
	let repositionRafId: number | null = null;

	async function fetchSuggestions({ query }: { query: string }): Promise<FileMentionAttrs[]> {
		if (!workspace) return [];
		try {
			const data = await searchFiles(query || '', workspace);
			const results = (data as any).results ?? [];
			return results.slice(0, 10).map((r: any) => ({
				id: r.type === 'directory' && !r.path.endsWith('/') ? r.path + '/' : r.path,
				label: r.name,
				type: r.type === 'directory' ? 'directory' : 'file'
			}));
		} catch {
			return [];
		}
	}

	function mountPopup(
		items: FileMentionAttrs[],
		selectedIdx: number,
		onselect: (i: number) => void
	) {
		// Destroy previous instance
		if (popupComponent) {
			try {
				unmount(popupComponent);
			} catch {}
			popupComponent = null;
		}
		if (!popupEl) {
			popupEl = document.createElement('div');
			document.body.appendChild(popupEl);
		}
		popupComponent = mount(FileSuggestionPopup, {
			target: popupEl,
			props: { items, selectedIndex: selectedIdx, onselect }
		});
	}

	function startRepositionLoop() {
		stopRepositionLoop();
		function tick() {
			if (activeClientRectFn) {
				updatePopupPosition(activeClientRectFn());
				repositionRafId = requestAnimationFrame(tick);
			}
		}
		repositionRafId = requestAnimationFrame(tick);
	}

	function stopRepositionLoop() {
		if (repositionRafId !== null) {
			cancelAnimationFrame(repositionRafId);
			repositionRafId = null;
		}
	}

	function createSuggestionRenderer() {
		let selectedIndex = 0;
		let currentItems: FileMentionAttrs[] = [];
		let command: ((attrs: FileMentionAttrs) => void) | null = null;

		function doSelect(index: number) {
			const item = currentItems[index];
			if (item && command) command(item);
		}

		function remount() {
			mountPopup(currentItems, selectedIndex, doSelect);
		}

		return {
			onStart(props: any) {
				command = props.command;
				currentItems = props.items;
				selectedIndex = 0;
				activeClientRectFn = props.clientRect ?? null;
				remount();
				updatePopupPosition(props.clientRect?.());
				startRepositionLoop();
			},
			onUpdate(props: any) {
				command = props.command;
				currentItems = props.items;
				selectedIndex = 0;
				activeClientRectFn = props.clientRect ?? null;
				remount();
				updatePopupPosition(props.clientRect?.());
			},
			onKeyDown({ event }: { event: KeyboardEvent }) {
				if (event.key === 'ArrowDown') {
					selectedIndex = (selectedIndex + 1) % Math.max(currentItems.length, 1);
					remount();
					return true;
				}
				if (event.key === 'ArrowUp') {
					selectedIndex =
						(selectedIndex - 1 + currentItems.length) % Math.max(currentItems.length, 1);
					remount();
					return true;
				}
				if (event.key === 'Enter') {
					const item = currentItems[selectedIndex];
					if (item && command) command(item);
					return true;
				}
				if (event.key === 'Escape') {
					destroyPopup();
					return true;
				}
				return false;
			},
			onExit() {
				destroyPopup();
			}
		};
	}

	function updatePopupPosition(rect: DOMRect | null) {
		if (!popupEl || !rect) return;
		const child = popupEl.firstElementChild as HTMLElement | null;
		if (!child) return;
		const popupHeight = child.offsetHeight || 200;
		child.style.position = 'fixed';
		child.style.left = `${Math.max(8, Math.min(rect.left, window.innerWidth - 340))}px`;
		child.style.top = `${rect.top - popupHeight - 8}px`;
	}

	function destroyPopup() {
		stopRepositionLoop();
		activeClientRectFn = null;
		if (popupComponent) {
			try {
				unmount(popupComponent);
			} catch {}
			popupComponent = null;
		}
		if (popupEl) {
			popupEl.remove();
			popupEl = null;
		}
	}

	// ── $skill mention suggestion ──────────────────────
	let skillPopupEl: HTMLDivElement | null = null;
	let skillPopupComponent: Record<string, any> | null = null;
	let skillActiveClientRectFn: (() => DOMRect | null) | null = null;
	let skillRepositionRafId: number | null = null;
	let cachedSkills: SkillMentionAttrs[] | null = null;

	async function fetchSkillSuggestions({ query }: { query: string }): Promise<SkillMentionAttrs[]> {
		if (!workspace) return [];
		try {
			// Cache skills list (small, doesn't change during a session)
			if (!cachedSkills) {
				const data = await getSkills(workspace);
				cachedSkills = data.map((s) => ({
					id: s.name,
					label: s.name,
					description: s.description,
					source: s.source,
				}));
			}
			if (!query) return cachedSkills;
			const q = query.toLowerCase();
			return cachedSkills.filter(
				(s) => s.label.toLowerCase().includes(q) || (s.description || '').toLowerCase().includes(q)
			);
		} catch {
			return [];
		}
	}

	function mountSkillPopup(
		items: SkillMentionAttrs[],
		selectedIdx: number,
		onselect: (i: number) => void
	) {
		if (skillPopupComponent) {
			try { unmount(skillPopupComponent); } catch {}
			skillPopupComponent = null;
		}
		if (!skillPopupEl) {
			skillPopupEl = document.createElement('div');
			document.body.appendChild(skillPopupEl);
		}
		skillPopupComponent = mount(SkillSuggestionPopup, {
			target: skillPopupEl,
			props: { items, selectedIndex: selectedIdx, onselect }
		});
	}

	function startSkillRepositionLoop() {
		stopSkillRepositionLoop();
		function tick() {
			if (skillActiveClientRectFn) {
				updateSkillPopupPosition(skillActiveClientRectFn());
				skillRepositionRafId = requestAnimationFrame(tick);
			}
		}
		skillRepositionRafId = requestAnimationFrame(tick);
	}

	function stopSkillRepositionLoop() {
		if (skillRepositionRafId !== null) {
			cancelAnimationFrame(skillRepositionRafId);
			skillRepositionRafId = null;
		}
	}

	function createSkillSuggestionRenderer() {
		let selectedIndex = 0;
		let currentItems: SkillMentionAttrs[] = [];
		let command: ((attrs: SkillMentionAttrs) => void) | null = null;

		function doSelect(index: number) {
			const item = currentItems[index];
			if (item && command) command(item);
		}

		function remount() {
			mountSkillPopup(currentItems, selectedIndex, doSelect);
		}

		return {
			onStart(props: any) {
				command = props.command;
				currentItems = props.items;
				selectedIndex = 0;
				skillActiveClientRectFn = props.clientRect ?? null;
				remount();
				updateSkillPopupPosition(props.clientRect?.());
				startSkillRepositionLoop();
			},
			onUpdate(props: any) {
				command = props.command;
				currentItems = props.items;
				selectedIndex = 0;
				skillActiveClientRectFn = props.clientRect ?? null;
				remount();
				updateSkillPopupPosition(props.clientRect?.());
			},
			onKeyDown({ event }: { event: KeyboardEvent }) {
				if (event.key === 'ArrowDown') {
					selectedIndex = (selectedIndex + 1) % Math.max(currentItems.length, 1);
					remount();
					return true;
				}
				if (event.key === 'ArrowUp') {
					selectedIndex = (selectedIndex - 1 + currentItems.length) % Math.max(currentItems.length, 1);
					remount();
					return true;
				}
				if (event.key === 'Enter') {
					const item = currentItems[selectedIndex];
					if (item && command) command(item);
					return true;
				}
				if (event.key === 'Escape') {
					destroySkillPopup();
					return true;
				}
				return false;
			},
			onExit() {
				destroySkillPopup();
			}
		};
	}

	function updateSkillPopupPosition(rect: DOMRect | null) {
		if (!skillPopupEl || !rect) return;
		const child = skillPopupEl.firstElementChild as HTMLElement | null;
		if (!child) return;
		const popupHeight = child.offsetHeight || 200;
		child.style.position = 'fixed';
		child.style.left = `${Math.max(8, Math.min(rect.left, window.innerWidth - 280))}px`;
		child.style.top = `${rect.top - popupHeight - 8}px`;
	}

	function destroySkillPopup() {
		stopSkillRepositionLoop();
		skillActiveClientRectFn = null;
		if (skillPopupComponent) {
			try { unmount(skillPopupComponent); } catch {}
			skillPopupComponent = null;
		}
		if (skillPopupEl) {
			skillPopupEl.remove();
			skillPopupEl = null;
		}
	}

	// ── Editor lifecycle ────────────────────────────
	onMount(() => {
		if (!editorEl) return;

		const fileMention = createFileMention({
			items: fetchSuggestions,
			render: createSuggestionRenderer
		});

		const skillMention = createSkillMention({
			items: fetchSkillSuggestions,
			render: createSkillSuggestionRenderer
		});

		editor = new Editor({
			element: editorEl,
			extensions: [
				StarterKit.configure({
					codeBlock: false,
					heading: { levels: [1, 2, 3] }
				}),
				Markdown,
				Placeholder.configure({ placeholder }),
				CodeBlockLowlight.configure({ lowlight }),
				fileMention,
				skillMention
			],
			content: inputText || '',
			contentType: inputText ? 'markdown' : undefined,
			autofocus: true,
			editorProps: {
				attributes: {
					class: 'chat-prosemirror',
					spellcheck: 'true'
				},
				handleKeyDown: (view, event) => {
					if (event.key === 'Enter' && !event.shiftKey) {
						// Don't send while suggestion popup is open — let it confirm selection
						if (popupComponent || skillPopupComponent) return false;
						const { state } = view;
						const head = state.selection.$head;

						let inside = false;
						for (let d = head.depth; d > 0; d--) {
							const name = head.node(d).type.name;
							if (['codeBlock', 'bulletList', 'orderedList', 'listItem'].includes(name)) {
								inside = true;
								break;
							}
						}
						if (!inside) {
							event.preventDefault();
							onsend();
							return true;
						}
					}
					return false;
				}
			},
			onUpdate: ({ editor: e }) => {
				inputText = (e as any).getMarkdown() || '';
			}
		});
	});

	onDestroy(() => {
		destroyPopup();
		destroySkillPopup();
		editor?.destroy();
		editor = null;
	});

	// Sync external inputText changes (e.g. cleared after send)
	$effect(() => {
		if (!editor || editor.isDestroyed) return;
		const editorMd = (editor as any).getMarkdown() || '';
		if (inputText !== editorMd) {
			if (inputText === '') {
				editor.commands.clearContent();
			} else {
				editor.commands.setContent(inputText);
			}
		}
	});

	export function focus() {
		editor?.commands.focus();
	}

	export function resetHeight() {
		// TipTap auto-sizes; no-op kept for API compat
	}

	export function getFiles(): any[] {
		return attachedUploads.filter(u => !u.loading);
	}

	export function clearUploads() {
		attachedUploads = [];
	}

	export function getSkillIds(): string[] {
		if (!editor) return [];
		return extractMentionedSkills(editor.getJSON());
	}

	// Allow sending during streaming (message will be enqueued server-side)
	const canSend = $derived(inputText.trim() && selectedModel && !sending);
</script>

<div 
	class="relative {isDragging ? 'ring-2 ring-blue-500 rounded-3xl' : ''}"
	ondrop={handleDrop}
	onpaste={handlePaste}
	ondragover={(e) => { e.preventDefault(); isDragging = true; }}
	ondragleave={() => { isDragging = false; }}
	role="presentation"
>
	<!-- Queued messages (above input, matching open-webui layout) -->
	{#if queuedMessages.length > 0}
		<div
			class="mb-1 mx-2 py-0.5 px-1.5 rounded-2xl border border-gray-100 dark:border-white/5 overflow-x-hidden overflow-y-auto max-h-[25vh]"
		>
			{#each queuedMessages as qm (qm.id)}
				<QueuedMessageItem
					id={qm.id}
					content={qm.content}
					onsendnow={onqueuesendnow ?? (() => {})}
					onedit={onqueueedit ?? (() => {})}
					ondelete={onqueuedelete ?? (() => {})}
				/>
			{/each}
		</div>
	{/if}

	<div
		class="rounded-3xl shadow-lg border border-gray-100/40 dark:border-white/4 focus-within:border-gray-200/50 focus-within:dark:border-white/8 transition px-1 bg-white dark:bg-gray-500/5"
	>
		<!-- Uploaded Files Preview -->
		{#if attachedUploads.length > 0}
			<div class="mx-2 pt-2 flex flex-wrap gap-2">
				{#each attachedUploads as upload}
					<div class="relative group flex-shrink-0">
						{#if upload.loading}
							<div class="flex items-center justify-center size-8 bg-gray-50 dark:bg-white/5 rounded-xl border border-gray-200 dark:border-white/10 shadow-sm">
								<Spinner size={16} />
							</div>
						{:else if upload.type === 'image'}
							<img src={upload.url} alt={upload.name} class="size-8 object-cover rounded-xl border border-gray-200 dark:border-white/10 shadow-sm" />
						{:else}
							<div class="relative group px-2 w-48 h-8 flex items-center gap-1.5 bg-white dark:bg-[#1a1a1a] border border-gray-100 dark:border-white/5 rounded-xl text-left flex-shrink-0 shadow-sm">
								<div class="shrink-0">
									<Icon name="page-text" size={14} class="text-gray-500 dark:text-gray-400" />
								</div>
								<div class="flex flex-col justify-center w-full overflow-hidden">
									<div class="dark:text-gray-100 text-xs flex justify-between items-center w-full gap-2">
										<div class="font-medium truncate flex-1">{upload.name}</div>
										<div class="text-[10px] text-gray-500 capitalize shrink-0">{upload.type === 'file' ? 'File' : upload.type}</div>
									</div>
								</div>
							</div>
						{/if}
						
						<div class="absolute -top-1.5 -right-1.5 z-10">
							<button 
								class="bg-white text-black border border-white rounded-full group-hover:visible invisible transition outline-none shadow-sm flex items-center justify-center"
								type="button"
								onclick={() => removeUpload(upload.id)}
								aria-label={$t('chat.removeUpload')}
							>
								<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="size-3.5" aria-hidden="true">
									<path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z"/>
								</svg>
							</button>
						</div>
					</div>
				{/each}
			</div>
		{/if}
		<!-- Editor area -->
		<div class="px-2.5">
			<div
				bind:this={editorEl}
				class="chat-editor-mount scrollbar-hidden"
				class:opacity-50={sending}
				class:pointer-events-none={sending}
			></div>
		</div>

		<!-- Toolbar. stopPropagation prevents TipTap from stealing focus -->
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div
			class="flex items-center justify-between mt-0.5 mb-2.5 mx-0.5"
			onmousedown={(e) => e.stopPropagation()}
		>
			<div class="ml-0.5 self-end flex items-center gap-1">
				<PlusMenu
					onfiles={(files) => {
						if (files) processFiles(Array.from(files));
					}}
					oncapture={(file) => {
						processFiles([file]);
					}}
				/>
				{#if $planMode}
					<button
						type="button"
						class="group p-[5px] flex gap-1 items-center text-xs rounded-full transition-colors duration-150
						text-gray-600 dark:text-gray-300 bg-gray-50 hover:bg-gray-100 dark:bg-white/8 dark:hover:bg-white/12 border border-gray-200 dark:border-white/8"
						onclick={() => planMode.set(false)}
					>
						<svg
							class="size-3 shrink-0 group-hover:hidden"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="1.75"
							stroke-linecap="round"
							stroke-linejoin="round"
						>
							<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
							<polyline points="14 2 14 8 20 8" />
							<line x1="9" y1="13" x2="15" y2="13" />
							<line x1="9" y1="17" x2="15" y2="17" />
						</svg>
						<svg
							class="size-3 shrink-0 hidden group-hover:block"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="2"
							stroke-linecap="round"
							stroke-linejoin="round"
						>
							<line x1="18" y1="6" x2="6" y2="18" />
							<line x1="6" y1="6" x2="18" y2="18" />
						</svg>
					</button>
				{/if}
			</div>
			<div class="self-end mr-1 flex items-center gap-2">
				<ModelSelector bind:selectedModel />
				<DictateButton
					ontext={(text) => {
						inputText += text;
					}}
				/>
				<SendButton {canSend} {streaming} {onsend} {oncancel} />
			</div>
		</div>
	</div>
</div>

<style>
	@reference "../../../app.css";

	/* ── ProseMirror editor ───────────────────────── */

	.chat-editor-mount :global(.chat-prosemirror) {
		@apply pt-2.5 pb-2 px-1 min-h-6 max-h-96 overflow-y-auto text-[13px] leading-relaxed text-gray-900 dark:text-gray-100 outline-none break-words;
	}

	/* Placeholder */
	.chat-editor-mount :global(.chat-prosemirror p.is-editor-empty:first-child::before) {
		content: attr(data-placeholder);
		@apply float-left text-gray-400 dark:text-gray-600 pointer-events-none h-0;
	}

	/* Paragraphs */
	.chat-editor-mount :global(.chat-prosemirror p) {
		@apply mb-1;
	}
	.chat-editor-mount :global(.chat-prosemirror p:last-child) {
		@apply mb-0;
	}

	/* Lists */
	.chat-editor-mount :global(.chat-prosemirror ul),
	.chat-editor-mount :global(.chat-prosemirror ol) {
		@apply mb-1 pl-4.5 text-sm;
	}
	.chat-editor-mount :global(.chat-prosemirror li) {
		@apply my-0.5;
	}
	.chat-editor-mount :global(.chat-prosemirror li > p) {
		@apply mb-0.5;
	}

	/* Inline code */
	.chat-editor-mount :global(.chat-prosemirror code) {
		@apply bg-gray-100 dark:bg-white/8 rounded-sm px-1 py-px text-xs font-mono;
	}

	/* Code blocks */
	.chat-editor-mount :global(.chat-prosemirror pre) {
		@apply bg-gray-100 dark:bg-white/4 rounded-md px-3 py-2 overflow-x-auto my-1 text-xs font-mono;
	}
	.chat-editor-mount :global(.chat-prosemirror pre code) {
		@apply bg-transparent p-0 rounded-none text-inherit;
	}

	/* Blockquote */
	.chat-editor-mount :global(.chat-prosemirror blockquote) {
		@apply my-1 py-0.5 pl-3 border-l-2 border-gray-300 dark:border-white/12 text-gray-500 dark:text-gray-400;
	}

	/* Strong */
	.chat-editor-mount :global(.chat-prosemirror strong) {
		@apply font-semibold;
	}

	/* Headings */
	.chat-editor-mount :global(.chat-prosemirror h1) {
		@apply text-base font-semibold my-1;
	}
	.chat-editor-mount :global(.chat-prosemirror h2) {
		@apply text-sm font-semibold my-1;
	}
	.chat-editor-mount :global(.chat-prosemirror h3) {
		@apply text-[13px] font-semibold my-1;
	}

	/* HR */
	.chat-editor-mount :global(.chat-prosemirror hr) {
		@apply border-none border-t border-gray-200 dark:border-white/8 my-2;
	}

	/* Syntax highlighting */
	.chat-editor-mount :global(.hljs-keyword) {
		color: #c678dd;
	}
	.chat-editor-mount :global(.hljs-string) {
		color: #98c379;
	}
	.chat-editor-mount :global(.hljs-number) {
		color: #d19a66;
	}
	.chat-editor-mount :global(.hljs-comment) {
		color: #5c6370;
		font-style: italic;
	}
	.chat-editor-mount :global(.hljs-function) {
		color: #61afef;
	}
	.chat-editor-mount :global(.hljs-title) {
		color: #61afef;
	}
	.chat-editor-mount :global(.hljs-built_in) {
		color: #e5c07b;
	}
</style>
