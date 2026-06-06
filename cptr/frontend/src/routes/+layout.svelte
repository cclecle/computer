<script lang="ts">
	import '../app.css';
	import '@xterm/xterm/css/xterm.css';

	import { onMount } from 'svelte';
	import Bar from '$lib/components/Bar.svelte';
	import Sidebar from '$lib/components/Sidebar.svelte';
	import ShortcutBar from '$lib/components/ShortcutBar.svelte';
	import GitBar from '$lib/components/GitBar.svelte';
	import QuickOpen from '$lib/components/QuickOpen.svelte';
	import SettingsModal from '$lib/components/SettingsModal.svelte';
	import AuthScreen from '$lib/components/AuthScreen.svelte';
	import ChangelogModal from '$lib/components/ChangelogModal.svelte';
	import { Toaster } from 'svelte-sonner';
	import {
		activeTab,
		currentWorkspace,
		stateLoaded,
		initState,
		gitReviewOpen,
		isGitRepo,
		splitActive,
		splitCurrentTab,
		closeGroup,
		appVersion,
		lastSeenVersion,
		showChangelog
	} from '$lib/stores';
	import { matchKeybinding, executeAction } from '$lib/stores/keybindings';
	import { systemEvents } from '$lib/stores/systemEvents.svelte';
	import { socketStore } from '$lib/stores/socket.svelte';
	import { setSession, clearSession } from '$lib/session';
	import { getSession, getConfig } from '$lib/apis/auth';
	import { gitStatusStore } from '$lib/stores/gitStatus.svelte';
	import { t } from '$lib/i18n';
	import { refreshChatState, bindGlobalChatListener } from '$lib/stores/chat';

	let { children } = $props();
	let showQuickOpen = $state(false);
	let showSettings = $state(false);

	// Auth state
	type AuthState = 'checking' | 'needs_setup' | 'needs_login' | 'authenticated';
	let authState = $state<AuthState>('checking');
	let authMode = $state<'password' | 'pam'>('password');
	let signupEnabled = $state(false);

	onMount(async () => {
		// Check auth first
		await checkAuth();

		// Periodic session health check (every 30 min).
		// This triggers the backend's sliding session refresh and
		// proactively catches expired sessions before a 401 mid-action.
		const healthCheck = setInterval(
			() => {
				if (authState === 'authenticated') {
					getSession()
						.then((auth) => {
							if (!auth.authenticated) clearSession();
						})
						.catch(() => {});
				}
			},
			30 * 60 * 1000
		);
		// iOS: Termius-style keyboard handling. visualViewport.height
		// gives us the area above the keyboard. Set max-height on the
		// main content column so the terminal shrinks to fit.
		// The layout container's overflow:hidden clips the gap.
		const vv = window.visualViewport;
		if (vv) {
			const syncHeight = () => {
				const col = document.getElementById('main-col');
				if (!col) return;
				const kbHeight = window.innerHeight - vv.height;
				console.log('[viewport]', { innerHeight: window.innerHeight, vvHeight: vv.height, kbHeight });
				col.style.maxHeight = kbHeight > 100 ? `${vv.height}px` : '';
			};
			// iOS may fire 'scroll' instead of 'resize' when keyboard opens
			vv.addEventListener('resize', syncHeight);
			vv.addEventListener('scroll', syncHeight);
			return () => {
				clearInterval(healthCheck);
				vv.removeEventListener('resize', syncHeight);
				vv.removeEventListener('scroll', syncHeight);
			};
		}
		return () => clearInterval(healthCheck);
	});

	let startupToken = $state('');

	$effect(() => {
		if ($stateLoaded && $appVersion) {
			const currentVer = $appVersion;
			const lastSeen = $lastSeenVersion;
			if (lastSeen !== currentVer) {
				if (!lastSeen) {
					// First-time load: initialize the last seen version to the current version so we don't pop up immediately
					lastSeenVersion.set(currentVer);
				} else {
					// Update: record this version as seen before showing the changelog so it doesn't reopen repeatedly.
					lastSeenVersion.set(currentVer);
					showChangelog.set(true);
				}
			}
		}
	});

	async function checkAuth() {
		try {
			const params = new URLSearchParams(window.location.search);
			const token = params.get('token');
			if (token) {
				startupToken = token;
				// Remove token from URL but preserve workspace param
				const url = new URL(window.location.href);
				url.searchParams.delete('token');
				window.history.replaceState({}, '', url.toString());
			}

			const auth = await getSession();

			getConfig()
				.then((cfg) => {
					appVersion.set(cfg.version);
				})
				.catch(() => {});

			if (auth.authenticated) {
				setSession({
					user_id: auth.user_id!,
					username: auth.username!,
					display_name: auth.display_name,
					role: auth.role!,
					profile_image_url: auth.profile_image_url
				});
				authState = 'authenticated';
				initState();
				refreshChatState();
			} else {
				const cfg = await getConfig();
				authMode = cfg.auth_mode || 'password';
				signupEnabled = cfg.signup_enabled || false;
				authState = cfg.needs_setup ? 'needs_setup' : 'needs_login';
			}
		} catch {
			authState = 'authenticated';
			initState();
			refreshChatState();
		}
	}

	async function handleAuth() {
		try {
			const auth = await getSession();
			if (auth.authenticated) {
				setSession({
					user_id: auth.user_id!,
					username: auth.username!,
					display_name: auth.display_name,
					role: auth.role!,
					profile_image_url: auth.profile_image_url
				});
				authState = 'authenticated';
				initState();
				refreshChatState();
				return;
			}
		} catch {}
		authState = 'needs_login';
	}

	function handleKeydown(e: KeyboardEvent) {
		const action = matchKeybinding(e);
		if (!action) return;
		e.preventDefault();
		executeAction(action, {
			toggleQuickOpen: () => {
				showQuickOpen = !showQuickOpen;
			},
			toggleSettings: () => {
				showSettings = !showSettings;
			}
		});
	}

	// Connect system events when workspace is active
	$effect(() => {
		const ws = $currentWorkspace;
		if (ws) {
			systemEvents.connect(ws.fileBrowserCwd || ws.path);
			socketStore.connect();
			bindGlobalChatListener();
		} else {
			systemEvents.disconnect();
			socketStore.disconnect();
		}
	});

	// Drive centralized git status from workspace
	$effect(() => {
		const ws = $currentWorkspace;
		if (!ws) {
			gitStatusStore.clear();
			isGitRepo.set(false);
			gitReviewOpen.set(false);
			return;
		}
		gitStatusStore.setRoot(ws.path);
	});

	// Sync isGitRepo flag from centralized store
	$effect(() => {
		isGitRepo.set(gitStatusStore.isRepo);
	});
</script>

<svelte:head>
	<link rel="preconnect" href="https://fonts.googleapis.com" />
	<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin="anonymous" />
	<link
		href="https://fonts.googleapis.com/css2?family=Inter:wght@300..700&family=JetBrains+Mono:wght@400;500&display=swap"
		rel="stylesheet"
	/>
	<title>{$currentWorkspace ? `${$currentWorkspace.name} / cptr` : 'cptr'}</title>
	<meta name="description" content={$t('app.tagline')} />
</svelte:head>

<svelte:window onkeydown={handleKeydown} />

{#if authState === 'checking'}
	<!-- Loading spinner while checking auth -->
	<div class="flex items-center justify-center h-dvh bg-white dark:bg-black">
		<div
			class="w-5 h-5 border-2 border-gray-300 border-t-gray-600 dark:border-gray-700 dark:border-t-gray-400 rounded-full animate-spin"
		></div>
	</div>
{:else if authState === 'needs_setup' || authState === 'needs_login'}
	<!-- Auth screen -->
	<AuthScreen
		mode={authMode}
		needsSetup={authState === 'needs_setup'}
		{signupEnabled}
		token={startupToken}
		onauth={handleAuth}
	/>
{:else if $stateLoaded}
	<div
		class="h-screen max-h-[100dvh] flex overflow-hidden font-sans antialiased text-gray-900 bg-white dark:text-gray-100 dark:bg-black"
	>
		<Sidebar />

		<div id="main-col" class="flex flex-col flex-1 min-w-0 min-h-0 overflow-hidden">
			{#if !$currentWorkspace}
				<Bar />
			{/if}
			<main class="relative flex-1 min-h-0 overflow-hidden">
				{@render children()}
			</main>

			{#if $currentWorkspace && $isGitRepo && !$gitReviewOpen}
				<GitBar />
			{/if}

			{#if $activeTab?.type === 'terminal'}
				<ShortcutBar />
			{/if}
		</div>
	</div>

	{#if showQuickOpen}
		<QuickOpen onclose={() => (showQuickOpen = false)} />
	{/if}
	{#if showSettings}
		<SettingsModal onclose={() => (showSettings = false)} />
	{/if}
	<ChangelogModal />
{:else}
	<div class="flex items-center justify-center h-dvh bg-white dark:bg-black">
		<div
			class="w-5 h-5 border-2 border-gray-300 border-t-gray-600 dark:border-gray-700 dark:border-t-gray-400 rounded-full animate-spin"
		></div>
	</div>
{/if}

<Toaster
	position="bottom-center"
	toastOptions={{
		style:
			'font-size: 12px; font-family: var(--font-sans); background: #111; color: #e0e0e0; border: 1px solid rgba(255,255,255,0.06); border-radius: 8px;'
	}}
/>
