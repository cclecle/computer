<script lang="ts">
	import { onMount, type Snippet } from 'svelte';
	import Icon from './Icon.svelte';
	import KeyPill from './KeyPill.svelte';

	interface MenuItem {
		label: string;
		icon?: string;
		onclick: () => void;
		active?: boolean;
		divider?: boolean;
		/** Optional image URL shown instead of icon (e.g. avatar). */
		image?: string;
		/** Optional check mark on the right when active. */
		check?: boolean;
		/** Optional keyboard shortcut hint displayed as a single pill on the right. */
		shortcut?: string;
	}

	interface Props {
		items: MenuItem[];
		anchor: { x: number; y: number } | HTMLElement;
		onclose: () => void;
		/** When true, match the anchor element's width. */
		matchWidth?: boolean;
		/** Prefer opening above the anchor instead of below. */
		preferAbove?: boolean;
		/** Max height for the items list (CSS value). */
		maxHeight?: string;
		/** Optional header snippet rendered above items (e.g. search input). */
		header?: Snippet;
		/** Optional snippet rendered when items array is empty. */
		empty?: Snippet;
		/** Additional CSS classes for the menu container. */
		className?: string;
		/** Horizontal alignment relative to anchor: 'start' (left) or 'end' (right). */
		align?: 'start' | 'end';
	}

	let {
		items,
		anchor,
		onclose,
		matchWidth = false,
		preferAbove = false,
		maxHeight,
		header,
		empty,
		className = '',
		align = 'start'
	}: Props = $props();

	let menuEl: HTMLDivElement | undefined = $state();
	let pos = $state<{ x: number; top?: number; bottom?: number }>({ x: -9999 });
	let anchorWidth = $state(0);
	let ready = $state(false);

	function updatePosition() {
		if (!menuEl) return;

		let ax: number;
		let anchorTop: number;
		let anchorBottom: number;

		if (anchor instanceof HTMLElement) {
			const rect = anchor.getBoundingClientRect();
			ax = rect.left;
			anchorTop = rect.top;
			anchorBottom = rect.bottom;
			if (matchWidth) anchorWidth = rect.width;
		} else {
			ax = anchor.x;
			anchorTop = anchor.y;
			anchorBottom = anchor.y;
		}

		const mw = menuEl.offsetWidth;
		const mh = menuEl.offsetHeight;
		const vw = window.innerWidth;
		const vh = window.innerHeight;
		const pad = 8;
		const gap = 4;

		// Horizontal: align to start or end of anchor
		if (align === 'end' && anchor instanceof HTMLElement) {
			const rect = anchor.getBoundingClientRect();
			ax = rect.right - mw;
		}
		if (ax + mw > vw - pad) ax = vw - mw - pad;
		if (ax < pad) ax = pad;

		// Vertical: collision detection
		const spaceAbove = anchorTop - gap - pad;
		const spaceBelow = vh - anchorBottom - gap - pad;

		if (preferAbove) {
			if (mh <= spaceAbove) {
				pos = { x: ax, bottom: vh - anchorTop + gap };
			} else {
				pos = { x: ax, top: anchorBottom + gap };
			}
		} else {
			if (mh <= spaceBelow) {
				pos = { x: ax, top: anchorBottom + gap };
			} else {
				pos = { x: ax, bottom: vh - anchorTop + gap };
			}
		}

		ready = true;
	}

	onMount(() => {
		requestAnimationFrame(updatePosition);

		// Follow anchor on scroll/resize
		window.addEventListener('scroll', updatePosition, true);
		window.addEventListener('resize', updatePosition);
		return () => {
			window.removeEventListener('scroll', updatePosition, true);
			window.removeEventListener('resize', updatePosition);
		};
	});
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
	class="fixed inset-0 z-[100]"
	onclick={onclose}
	oncontextmenu={(e) => {
		e.preventDefault();
		onclose();
	}}
></div>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
	bind:this={menuEl}
	class="fixed z-[101] min-w-36 rounded-xl bg-white dark:bg-[#1a1a1a] border border-gray-150 dark:border-white/6 shadow-xl p-0.5 {className}"
	style="left: {pos.x}px; {pos.bottom != null
		? `bottom: ${pos.bottom}px`
		: `top: ${pos.top ?? -9999}px`}; {anchorWidth ? `width: ${anchorWidth}px;` : ''} opacity: {ready
		? 1
		: 0}; pointer-events: {ready ? 'auto' : 'none'};"
	onclick={(e) => e.stopPropagation()}
	onmousedown={(e) => e.stopPropagation()}
>
	{#if header}
		{@render header()}
		<div class="h-px bg-gray-100/50 dark:bg-white/3 mx-1 my-0.5"></div>
	{/if}

	<div style={maxHeight ? `max-height: ${maxHeight}; overflow-y: auto;` : ''}>
		{#if items.length === 0 && empty}
			{@render empty()}
		{:else}
			{#each items as item}
				{#if item.divider}
					<div class="h-px bg-gray-100/50 dark:bg-white/3 mx-1 my-0.5"></div>
				{:else}
					<button
						class="flex items-center gap-2 w-full h-6 px-2 rounded-xl text-xs transition-colors duration-75
							{item.active
							? 'text-gray-900 dark:text-white bg-gray-50 dark:bg-white/5'
							: 'text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-white/5 hover:text-gray-900 dark:hover:text-white'}"
						onclick={() => {
							item.onclick();
							onclose();
						}}
					>
						{#if item.image}
							<img src={item.image} alt="" class="w-4 h-4 rounded-full object-cover shrink-0" />
						{:else if item.icon}
							<Icon name={item.icon} size={14} />
						{/if}
						<span class="flex-1 text-left truncate">{item.label}</span>
						{#if item.shortcut}
							<KeyPill text={item.shortcut} class="ml-auto shrink-0" />
						{/if}
						{#if item.check && item.active}
							<svg
								class="w-3 h-3 shrink-0 text-gray-400 dark:text-gray-500"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="2.5"
								stroke-linecap="round"
								stroke-linejoin="round"
							>
								<polyline points="20 6 9 17 4 12" />
							</svg>
						{/if}
					</button>
				{/if}
			{/each}
		{/if}
	</div>
</div>
