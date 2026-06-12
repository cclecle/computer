<script lang="ts">
	import '../app.css';
	import '@xterm/xterm/css/xterm.css';

	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import Bar from '$lib/components/Bar.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Sidebar from '$lib/components/Sidebar.svelte';
	import ShortcutBar from '$lib/components/ShortcutBar.svelte';
	import GitBar from '$lib/components/GitBar.svelte';
	import SearchModal from '$lib/components/SearchModal.svelte';
	import SettingsModal from '$lib/components/SettingsModal.svelte';
	import AuthScreen from '$lib/components/AuthScreen.svelte';
	import ChangelogModal from '$lib/components/ChangelogModal.svelte';
	import UpdateToast from '$lib/components/UpdateToast.svelte';
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
		latestVersion,
		updateAvailable,
		showChangelog,
		showSearch
	} from '$lib/stores';
	import { matchKeybinding, executeAction } from '$lib/stores/keybindings';
	import { systemEvents } from '$lib/stores/systemEvents.svelte';
	import { socketStore } from '$lib/stores/socket.svelte';
	import { setSession, clearSession, session } from '$lib/session';
	import { getSession, getConfig } from '$lib/apis/auth';
	import { fetchJSON } from '$lib/apis';
	import { gitStatusStore } from '$lib/stores/gitStatus.svelte';
	import { t } from '$lib/i18n';
	import { refreshChatState, bindGlobalChatListener } from '$lib/stores/chat';

	let { children } = $props();
	let showSettings = $state(false);
	let showUpdateToast = $state(false);

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

				// Check for version updates (admin only, after session is set)
				checkForUpdates();
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

	async function checkForUpdates() {
		try {
			const sess = $session;
			if (!sess || sess.role !== 'admin') return;

			// 24-hour dismiss cooldown
			const dismissed = localStorage.getItem('dismissedUpdateToast');
			if (dismissed) {
				const elapsed = Date.now() - Number(dismissed);
				if (elapsed < 24 * 60 * 60 * 1000) return;
			}

			const data = await fetchJSON<{ current: string; latest: string }>('/api/version/updates');
			latestVersion.set(data.latest);
			// Show toast if update is available (reactive via $updateAvailable)
			if (data.current !== data.latest) {
				showUpdateToast = true;
			}
		} catch {
			// Silently ignore (non-admin, network error, etc.)
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		const action = matchKeybinding(e);
		if (!action) return;
		e.preventDefault();
		executeAction(action, {
			toggleQuickOpen: () => {
				showSearch.update((v) => !v);
			},
			toggleSettings: () => {
				showSettings = !showSettings;
			},
			toggleSearch: () => {
				showSearch.update((v) => !v);
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
	<title>{$activeTab && $activeTab.type !== 'files'
		? $currentWorkspace
			? `${$activeTab.label} / ${$currentWorkspace.name} / cptr`
			: `${$activeTab.label} / cptr`
		: $currentWorkspace
			? `${$currentWorkspace.name} / cptr`
			: 'cptr'}</title>
	<meta name="description" content={$t('app.tagline')} />
</svelte:head>

<svelte:window onkeydown={handleKeydown} />

{#if authState === 'checking'}
	<!-- Loading spinner while checking auth -->
	<div class="flex items-center justify-center h-dvh bg-white dark:bg-black">
		<Spinner size={20} />
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
			{#if !$currentWorkspace && $page.url.pathname === '/'}
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

	{#if $showSearch}
		<SearchModal onclose={() => showSearch.set(false)} />
	{/if}
	{#if showSettings}
		<SettingsModal onclose={() => (showSettings = false)} />
	{/if}
	<ChangelogModal />
	{#if $updateAvailable && showUpdateToast}
		<UpdateToast
			onclose={() => {
				showUpdateToast = false;
				localStorage.setItem('dismissedUpdateToast', Date.now().toString());
			}}
		/>
	{/if}
{:else}
	<div class="flex items-center justify-center h-dvh bg-white dark:bg-black">
		<Spinner size={20} />
	</div>
{/if}

<Toaster
	position="top-right"
	theme="system"
	closeButton
	richColors
	toastOptions={{
		style:
			'font-size: 12px; font-family: var(--font-sans); border-radius: 8px;'
	}}
/>
