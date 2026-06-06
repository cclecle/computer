<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { Terminal } from '@xterm/xterm';
	import { FitAddon } from '@xterm/addon-fit';
	import { WebglAddon } from '@xterm/addon-webgl';

	// ── Compact binary WebSocket protocol ─────────────────────
	// Client → Server:  byte 0 = type, rest = payload
	//   0x00 + raw input bytes (microtask-batched for throughput)
	//   0x02 + uint16 cols + uint16 rows, big-endian (5 bytes total)
	// Server → Client:  raw PTY output bytes (no prefix)
	const MSG_INPUT = 0;
	const MSG_RESIZE = 2;

	const textEncoder = new TextEncoder();

	// ── Pre-allocated send buffer ──────────────────────────────
	// Single 4 KB buffer for all input.  Avoids per-keystroke allocation
	// and per-flush Uint8Array creation.  Microtask-flushed for batching.
	const INPUT_BUF_CAP = 4096;
	const inputBuf = new Uint8Array(INPUT_BUF_CAP);
	let inputBufLen = 0; // bytes written after the type prefix
	let inputFlushScheduled = false;
	inputBuf[0] = MSG_INPUT; // prefix is constant

	function flushInput() {
		inputFlushScheduled = false;
		if (!inputBufLen || ws?.readyState !== WebSocket.OPEN) {
			inputBufLen = 0;
			return;
		}
		// subarray() creates a zero-copy view; browser copies internally for send
		ws!.send(inputBuf.subarray(0, 1 + inputBufLen));
		inputBufLen = 0;
	}

	interface Props {
		sessionId: string;
	}

	let { sessionId }: Props = $props();

	let containerEl: HTMLDivElement | undefined = $state();
	let term: Terminal | null = null;
	let fitAddon: FitAddon | null = null;
	let ws: WebSocket | null = null;
	let resizeObserver: ResizeObserver | null = null;
	let resizeTimeout: ReturnType<typeof setTimeout> | null = null;
	let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
	let destroyed = false;
	let lastSentCols = 0;
	let lastSentRows = 0;

	function getWsUrl(sid: string): string {
		const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
		return `${proto}//${window.location.host}/api/terminal/${sid}/ws`;
	}

	function doFit() {
		if (!fitAddon || !term || !containerEl) return;
		const rect = containerEl.getBoundingClientRect();
		if (rect.width === 0 || rect.height === 0) return;
		try {
			fitAddon.fit();
		} catch {
			// FitAddon can throw if terminal not properly attached
		}
	}

	function debouncedFit() {
		if (resizeTimeout) clearTimeout(resizeTimeout);
		// 350ms debounce, long enough to outlast the mobile keyboard
		// animation so we only refit ONCE after it fully settles.
		resizeTimeout = setTimeout(() => doFit(), 350);
	}

	function isDarkMode(): boolean {
		return document.documentElement.classList.contains('dark');
	}

	const darkTheme = {
		background: '#000000',
		foreground: '#e0e0e0',
		cursor: '#e0e0e0',
		cursorAccent: '#000000',
		selectionBackground: 'rgba(255, 255, 255, 0.2)'
	};

	const lightTheme = {
		background: '#ffffff',
		foreground: '#1a1a1a',
		cursor: '#1a1a1a',
		cursorAccent: '#ffffff',
		selectionBackground: 'rgba(0, 0, 0, 0.15)'
	};

	// Send input to PTY via WebSocket (binary prefix protocol).
	// Writes directly into the pre-allocated buffer. Zero allocation
	// for the common single-ASCII-keystroke path.
	function sendInput(data: string) {
		if (ws?.readyState !== WebSocket.OPEN) return;

		if (data.length === 1 && data.charCodeAt(0) < 128) {
			// Fast path: single ASCII byte, no TextEncoder, no allocation
			if (1 + inputBufLen + 1 > INPUT_BUF_CAP) flushInput();
			inputBuf[1 + inputBufLen++] = data.charCodeAt(0);
		} else {
			const encoded = textEncoder.encode(data);
			if (1 + inputBufLen + encoded.length > INPUT_BUF_CAP) flushInput();
			inputBuf.set(encoded, 1 + inputBufLen);
			inputBufLen += encoded.length;
		}

		if (!inputFlushScheduled) {
			inputFlushScheduled = true;
			queueMicrotask(flushInput);
		}
	}

	// Pre-allocated 5-byte resize buffer, reused on every resize event
	const resizeBuf = new ArrayBuffer(5);
	const resizeView = new DataView(resizeBuf);
	resizeView.setUint8(0, MSG_RESIZE);

	function sendResize(cols: number, rows: number) {
		if (ws?.readyState !== WebSocket.OPEN) return;
		resizeView.setUint16(1, cols, false);
		resizeView.setUint16(3, rows, false);
		ws!.send(resizeBuf);
	}

	onMount(() => {
		if (!containerEl) return;

		term = new Terminal({
			cursorBlink: true,
			cursorStyle: 'bar',
			fontFamily: '"JetBrains Mono", "Fira Code", ui-monospace, monospace',
			fontSize: 13,
			lineHeight: 1.3,
			scrollback: 10000,
			macOptionClickForceSelection: true,
			theme: isDarkMode() ? darkTheme : lightTheme
		});

		// Watch for theme changes
		const observer = new MutationObserver(() => {
			if (term) {
				term.options.theme = isDarkMode() ? darkTheme : lightTheme;
			}
		});
		observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });

		// Handle macOS key combos that need special escape sequences
		term.attachCustomKeyEventHandler((e: KeyboardEvent) => {
			if (e.type !== 'keydown') return true;

			// Cmd+Arrow: line navigation
			if (e.metaKey) {
				if (e.key === 'ArrowLeft') {
					sendInput('\x01'); // Ctrl-A: beginning of line
					return false;
				}
				if (e.key === 'ArrowRight') {
					sendInput('\x05'); // Ctrl-E: end of line
					return false;
				}
			}

			// Option+Arrow: word navigation
			if (e.altKey) {
				if (e.key === 'ArrowLeft') {
					sendInput('\x1bb'); // ESC-b: backward word
					return false;
				}
				if (e.key === 'ArrowRight') {
					sendInput('\x1bf'); // ESC-f: forward word
					return false;
				}
				if (e.key === 'Backspace') {
					sendInput('\x17'); // Ctrl-W: delete word backward
					return false;
				}
			}

			return true;
		});

		fitAddon = new FitAddon();
		term.loadAddon(fitAddon);
		term.open(containerEl);
		// // iOS: Move xterm's textarea from inside .xterm-helpers (position:absolute,
		// // offscreen) to a flex sibling BELOW the terminal.
		// if ('ontouchstart' in window && term.textarea) {
		// 	containerEl.after(term.textarea);
		// 	term.focus = () => term.textarea?.focus();
		//
		// 	// xterm's mousedown calls ev.preventDefault() which blocks iOS
		// 	// viewport adjustment. Focus on touchstart (fires before mousedown).
		// 	containerEl.addEventListener('touchstart', () => {
		// 		term.textarea?.focus();
		// 	}, { passive: true });
		// }

		// GPU-accelerated rendering, 2-5x faster than canvas 2D.
		// Falls back to canvas if WebGL is unavailable.
		try {
			const webgl = new WebglAddon();
			webgl.onContextLoss(() => webgl.dispose());
			term.loadAddon(webgl);
		} catch {
			// WebGL not supported, canvas fallback is fine
		}

		// Register input/resize handlers ONCE, not per WebSocket connection.
		// This prevents duplicate SIGWINCH signals that cause rich CLI apps
		// (e.g. Claude Code, htop) to render content twice.
		term.onData((data: string) => {
			sendInput(data);
		});

		term.onResize(({ cols, rows }: { cols: number; rows: number }) => {
			// Skip if dimensions haven't actually changed. Prevents duplicate
			// SIGWINCH when keyboard open/close triggers multiple fit cycles.
			if (cols === lastSentCols && rows === lastSentRows) return;
			lastSentCols = cols;
			lastSentRows = rows;
			sendResize(cols, rows);
		});

		connectWebSocket();

		// ── Mobile touch scrolling ──
		// We use document-level listeners to guarantee touch events are received
		// regardless of CSS touch-action settings. Events are filtered to only
		// act when the touch originated inside this terminal container.
		// overscroll-behavior: none on html (app.css) prevents pull-to-refresh;
		// e.preventDefault() here is a secondary guard.
		let touchStartY = 0;
		let lastTouchY = 0;
		let touchAccum = 0;
		let touchingTerminal = false;
		const LINE_PX = 13 * 1.3; // fontSize * lineHeight

		function isAltBuffer(): boolean {
			try {
				return term?.buffer?.active?.type === 'alternate';
			} catch {
				return false;
			}
		}

		function onTouchStart(e: TouchEvent) {
			if (e.touches.length !== 1 || !containerEl) return;
			// Only track touches that started inside this terminal
			const target = e.target as HTMLElement;
			if (!containerEl.contains(target)) return;
			touchingTerminal = true;
			touchStartY = e.touches[0].clientY;
			lastTouchY = touchStartY;
			touchAccum = 0;
		}

		function onTouchMove(e: TouchEvent) {
			if (!touchingTerminal || !term || e.touches.length !== 1) return;
			e.preventDefault(); // block pull-to-refresh / page scroll

			const currentY = e.touches[0].clientY;
			const deltaY = lastTouchY - currentY; // positive = finger moved up = scroll down
			lastTouchY = currentY;
			touchAccum += deltaY;

			// Convert accumulated pixel delta to lines
			const lines = Math.trunc(touchAccum / LINE_PX);
			if (lines !== 0) {
				if (isAltBuffer()) {
					// TUI apps (vim, htop, Claude Code): send arrow keys
					const seq = lines > 0 ? '\x1b[B' : '\x1b[A';
					const count = Math.abs(lines);
					for (let i = 0; i < Math.min(count, 5); i++) {
						sendInput(seq);
					}
				} else {
					// Normal buffer: scroll terminal history
					term.scrollLines(lines);
				}
				touchAccum -= lines * LINE_PX;
			}
		}

		function onTouchEnd() {
			touchingTerminal = false;
		}

		// Document-level: guaranteed to receive events regardless of
		// which child element the touch lands on (.xterm-screen, etc.)
		document.addEventListener('touchstart', onTouchStart, { passive: true });
		document.addEventListener('touchmove', onTouchMove, { passive: false });
		document.addEventListener('touchend', onTouchEnd, { passive: true });

		// Initial fit, deferred to let the container settle in the DOM
		requestAnimationFrame(() => {
			doFit();
		});

		// ResizeObserver is the SOLE trigger for refitting on container
		// size changes. No other resize listener needed; the layout
		// already handles visualViewport → container height propagation.
		resizeObserver = new ResizeObserver(() => {
			debouncedFit();
		});
		resizeObserver.observe(containerEl);

		// Listen for ShortcutBar input
		function handleShortcutInput(e: Event) {
			const data = (e as CustomEvent).detail;
			sendInput(data);
		}
		window.addEventListener('cptr:terminal-input', handleShortcutInput);

		return () => {
			window.removeEventListener('cptr:terminal-input', handleShortcutInput);
			document.removeEventListener('touchstart', onTouchStart);
			document.removeEventListener('touchmove', onTouchMove);
			document.removeEventListener('touchend', onTouchEnd);
		};
	});

	function connectWebSocket() {
		if (!term || destroyed) return;

		const url = getWsUrl(sessionId);
		console.log(`[terminal] connecting to ${url}`);
		ws = new WebSocket(url);
		ws.binaryType = 'arraybuffer';

		ws.onopen = () => {
			console.log(`[terminal] WebSocket open for ${sessionId}`);
			if (term) {
				// Send ONE resize message with current dimensions.
				// Do NOT call doFit() here; that would trigger term.onResize
				// which sends a SECOND resize message, causing rich CLI apps
				// to receive double SIGWINCH and render content twice.
				lastSentCols = term.cols;
				lastSentRows = term.rows;
				console.log(`[terminal] sending resize: ${term.cols}x${term.rows}`);
				sendResize(term.cols, term.rows);
			}
		};

		ws.onmessage = (event) => {
			// binaryType='arraybuffer' guarantees ArrayBuffer; write
			// directly with a Uint8Array view (zero-copy wrapper)
			term?.write(new Uint8Array(event.data as ArrayBuffer));
		};

		ws.onclose = (e) => {
			console.log(
				`[terminal] WebSocket closed for ${sessionId}, code=${e.code}, reason=${e.reason}`
			);
			if (destroyed) return;
			reconnectTimer = setTimeout(() => {
				if (!destroyed) connectWebSocket();
			}, 2000);
		};

		ws.onerror = (e) => {
			console.error(`[terminal] WebSocket error for ${sessionId}`, e);
		};

		// NOTE: term.onData and term.onResize are registered in onMount,
		// NOT here. This function can be called multiple times on reconnect
		// and we must not duplicate those handlers.
	}

	onDestroy(() => {
		destroyed = true;
		if (resizeTimeout) clearTimeout(resizeTimeout);
		if (reconnectTimer) clearTimeout(reconnectTimer);
		resizeObserver?.disconnect();
		ws?.close();
		term?.dispose();
	});
</script>

<div class="flex flex-col h-full w-full">
	<div bind:this={containerEl} class="flex-1 min-h-0 pt-1 pl-2 overflow-hidden"></div>
	<!-- On mobile, xterm's textarea gets moved here as a flex sibling -->
</div>

<style>
	@reference "../../app.css";

	:global(.xterm) {
		height: 100%;
	}
	:global(.xterm-viewport) {
		overflow-y: auto !important;
		scrollbar-width: thin;
		scrollbar-color: rgba(75, 85, 99, 0.4) transparent;
		overscroll-behavior: contain;
	}
	/* When moved to flex sibling on mobile, override xterm's offscreen
	   positioning. Make it a real in-flow element like chat's textarea.
	   Use opacity:1 with transparent colors — iOS ignores opacity:0
	   elements for viewport adjustment. */
	/* :global(.xterm-helper-textarea) {
		position: relative !important;
		top: auto !important;
		left: auto !important;
		width: 100% !important;
		height: 1px !important;
		opacity: 1 !important;
		color: transparent !important;
		background: transparent !important;
		caret-color: transparent !important;
		border: none !important;
		outline: none !important;
		resize: none !important;
		flex-shrink: 0;
	} */
</style>
