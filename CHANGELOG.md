# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.1] - 2026-06-16

### Added

- 🎚️ **TTS playback speed control.** You can now adjust how fast the AI reads responses aloud. A new speed slider in Settings > Audio lets you pick anything from 0.5x to 2x. Your preference syncs across devices.

### Fixed

- 📱 **TTS no longer silently fails on mobile.** On iOS and other mobile browsers, audio playback could fail because the browser requires a user gesture before playing sound. Entering voice mode now "unlocks" the audio system with a silent tap so speech plays reliably from the first message.
- 🛡️ **Empty audio responses no longer break playback.** If the TTS provider returned an empty file, the player would get stuck and stop reading. Empty responses are now caught and reported as errors, and corrupted cache entries are cleaned up automatically.
- ⚡ **Faster first sentence.** The text-to-speech system now starts speaking sooner by splitting the first sentence at a shorter boundary, so you hear the beginning of a response more quickly.
- 🔄 **Smoother audio prefetching.** Instead of requesting all upcoming sentences at once, the player now fetches up to two ahead at a time. This avoids flooding the TTS API with requests and keeps playback steady on slower connections.

## [0.5.0] - 2026-06-16

### Added

- 🎙️ **Voice mode.** Talk to the AI hands-free. When text-to-speech is configured, a new voice button appears in the chat input. Tap it to start listening. Speak your message, and cptr will transcribe it, send it to the AI, and read the response back to you out loud. The mic re-arms automatically so you can have a back-and-forth conversation without touching the screen.
- 🔊 **Text-to-speech.** AI responses can now be read aloud. Connect any OpenAI-compatible TTS API from Settings > Audio, pick a voice and format, and responses will stream as audio sentence by sentence. Works with voice mode or on its own: click the speaker icon on any message to hear it.
- 💭 **Reasoning display.** Models that think before responding (like o3 or Claude with extended thinking) now show their reasoning in the chat. Thought steps appear as collapsible sections you can expand to see what the AI was considering.
- 📋 **Audit logging.** Every mutating API request (POST, PUT, PATCH, DELETE) can now be logged to a structured JSON file. Sensitive fields like passwords and API keys are automatically redacted. Configure the level of detail with the `CPTR_AUDIT_LOG_LEVEL` environment variable: metadata only, request bodies, or full request and response.
- 📊 **Upstream request logging.** Optionally log every outgoing AI API call (provider, model, endpoint, request body) to a separate file for debugging and cost tracking. Enable with `CPTR_LOG_UPSTREAM_REQUESTS=true`.
- 🪵 **Structured logging.** All application logs now go through Loguru with configurable format (text or JSON), level, and rotation. Standard library loggers (uvicorn, etc.) are intercepted and routed through the same system.

### Changed

- 💬 **Redesigned tool call and reasoning UI.** Tool calls and reasoning steps are now displayed as clean, collapsible rows with status indicators (spinning while running, green check when done, red X if rejected). Consecutive tool calls are grouped together so the chat stays compact. Each group shows a summary like "3 read_file, 1 edit_file" and can be expanded to see individual calls with their inputs and outputs.
- 🔊 **Audio settings expanded.** The Audio admin panel now has separate sections for speech-to-text and text-to-speech, plus a voice mode system prompt that tells the AI to keep responses short and conversational when you are talking to it.
- 🎙️ **Transcription caching.** Audio transcriptions are cached in the workspace so the same recording is not sent to the API twice. Transcription results are also saved alongside the audio file.
- 📱 **PWA icon and touch icon.** Updated app icons and added an Apple touch icon for better home screen appearance on iOS.
- 🌍 **New translation keys.** Added voice mode, TTS, reasoning, and tool call labels across all 10 supported languages.

## [0.4.10] - 2026-06-15

### Changed

- 📁 **File browser drag-and-drop completely reworked.** You can now freely drag and drop files and folders anywhere — into folders, onto breadcrumbs, or between nested directories. Multi-select drag, auto-expand on hover, and full expanded-area highlighting are all supported.

### Fixed

- 📋 **Dropdown menus no longer get cut off by the keyboard on mobile.** Menus that open upward (like the model picker) now anchor from the bottom of the screen instead of the top, so they stay fully visible even when the on-screen keyboard is open.
- 🔄 **Renamed files no longer break git operations.** Renaming or moving a file could cause errors when staging, discarding, or viewing changes — the file list would show garbled entries like "R100 old-name.txt" instead of the actual file. This is now handled correctly.

## [0.4.9] - 2026-06-15

### Fixed

- 📱 **Mobile keyboard no longer covers the chat.** On iOS and mobile browsers, opening the on-screen keyboard could push content behind it or clip the bottom of the screen. The layout now properly adjusts to keep everything visible above the keyboard.
- 🗑️ **Discarding staged files works correctly.** Previously, discarding a file that was already staged (added to a commit) could leave it in a broken state. Staged changes are now properly unstaged and cleaned up in one step.
- 🔄 **Git file list no longer flickers when staging.** Toggling a file between staged and unstaged could briefly cause a visual glitch where the list jumped. The file list now updates smoothly.

### Improved

- 📋 **Dropdown menus stay on screen.** Dropdown menus (like the model picker) now correctly reposition themselves to stay within the visible area, especially when the keyboard is open or on smaller screens.
- 📖 **README updated with badges and clearer tunnel docs.** Added project badges (stars, language, Discord) to the top of the README, and clarified the remote access / tunnel instructions.

## [0.4.8] - 2026-06-15

### Fixed

- 💬 **Clicking chats now opens them instantly.** Tapping a chat in the sidebar, clicking "View Chat" on an automation run, or following a notification toast now takes you straight to the conversation. Previously these actions could sometimes get stuck or fail to switch to the right chat.

## [0.4.7] - 2026-06-15

### Fixed

- 🛡️ **Chat no longer breaks after crashes or interruptions.** If a previous session ended unexpectedly, leftover data could cause permanent errors when resuming a conversation. The chat now automatically cleans up mismatched data on load so you can always pick up where you left off.
- 🔄 **Better compatibility with OpenAI models.** Fixed issues where certain internal data was accidentally sent to OpenAI, causing requests to fail. Conversations with tool use now work reliably across all supported providers.
- 🪵 **Clearer error reporting for AI requests.** When an AI request fails, the error details are now logged properly instead of being silently swallowed, making issues easier to diagnose.

## [0.4.6] - 2026-06-15

### Added

- 🎯 **Default model.** Pick a default model from Settings › Models. New chats and gateway requests will use it automatically instead of whichever model happens to be first in the list.

### Changed

- 🔄 **Smarter gateway model selection.** The gateway now respects your default model setting before falling back, and can auto-discover available models from providers that don't have a pre-configured list.

## [0.4.5] - 2026-06-15

### Fixed

- 🧠 **Reasoning models no longer lose chain of thought across parallel tool calls.** Multiple tool calls in the same turn are now grouped into a single assistant message with shared reasoning items, instead of being split into separate messages that broke reasoning model round-tripping (e.g. o3, o4-mini).
- 🛡️ **Orphaned tool calls no longer break chat history.** If a crash or data corruption left a function call without a matching result, the Responses API conversion now skips the orphaned call instead of sending invalid input that caused permanent 400 errors.
- 🔄 **Tool output ordering prevents corrupted history on crash.** Tool call outputs are now appended to the output list *before* marking the call as "completed", so a crash between the two steps can no longer produce a "completed" call with no output — which would corrupt the message history on reload.
- 🧹 **In-progress tool calls scrubbed on error or cancellation.** When a chat task is cancelled or hits an error, any tool calls still marked "in_progress" are now set to "failed" before persisting, preventing stale in-progress items from lingering in the database.

## [0.4.4] - 2026-06-15

### Added

- 🧙 **Setup wizard.** A friendly first-run guide walks you through picking a folder and connecting your AI. Pops up automatically after sign-up.
- 🔌 **Local tool servers (stdio).** You can now connect MCP tool servers that run as local commands — not just over HTTP. Add the command and arguments from the Tool Servers tab.
- 📄 **Read documents.** The AI can now open and read PDFs, Word docs, Excel spreadsheets, PowerPoint files, and more.
- 💬 **Send input to running commands.** The AI can now type into running processes — answering prompts, interacting with REPLs, or sending Ctrl-C.
- ↩️ **Undo last commit.** Changed your mind? Undo the last commit from the Git history and get your changes back in staging.
- 🚀 **Publish branches.** Push a new branch for the first time with one click. The button says "Publish" when there's no upstream yet.
- 🔗 **View on GitHub / GitLab.** A new link in the Git panel takes you straight to your repo on the web.
- 📋 **Commit actions menu.** Click the dots on any commit to copy its hash. On the latest commit you can also undo it.
- 🔗 **Share cptr.** Quick links on the About page to share cptr on X, Reddit, LinkedIn, or copy the URL.

### Changed

- ⚡ **Smoother command execution.** Commands now run in a real terminal (PTY) by default. You can choose how long to wait for output before moving on.
- 🧠 **Better reasoning model support.** Models like o3 and o4-mini now keep their chain of thought across tool calls, giving more accurate results.
- 📝 **Updated README.** New sections on accessing cptr from your phone and a list of compatible terminal agents.
- 🔧 **Clearer error messages.** Validation errors now show what actually went wrong instead of a generic status code.

### Fixed

- 🔒 **Gateway connections working again.** Fixed an error that could break the gateway models endpoint.

## [0.4.3] - 2026-06-14

### Changed

- 💬 **Telegram rich message formatting.** Telegram messages now use `sendRichMessage` / `sendRichMessageDraft` (Bot API `InputRichMessage`) for properly rendered Markdown with bold, italic, code blocks, and links. Falls back gracefully to plain text when the API is unavailable.
- 📝 **Increased Telegram streaming buffer.** The streaming buffer limit for Telegram was raised from 4 096 to 32 768 characters, allowing longer messages to stream without premature chunking.
- 🔒 **Proxy middleware authentication.** The reverse-proxy middleware now verifies the `cptr_session` cookie before forwarding requests, preventing unauthenticated access to proxied local services.
- 📖 **README refresh.** Updated the README with revised feature descriptions and setup instructions.

## [0.4.2] - 2026-06-14

### Fixed

- 🔧 **Tool calls no longer jump to the top during streaming.** Fixed a regression from 0.4.1 where tool call indicators appeared at the very top of the assistant message while streaming, instead of in their correct position after the preceding text. They would snap back to the correct position only after the response completed. Caused by a premature text buffer flush in the usage event handler that was left over from the pre-parallel-execution refactor.

## [0.4.1] - 2026-06-13

### Changed

- 🌍 **i18n for tool servers, browser, and web settings.** Replaced all remaining hardcoded English strings in the Tool Servers, Web/Browser, and admin panels with translation keys. Added ~60 new keys per locale across all 10 languages (de, en, es, fr, ja, ko, pt-BR, ru, zh-CN, zh-TW).
- 🎨 **General settings layout refactor.** Reorganised the General settings panel into a scrollable layout with grouped sections (Notifications, Updates, Message Queue). Webhook URL input is now full-width with a hint instead of an inline save button. The save button now shows a loading/saving state.
- 🖱️ **Scrollbar-on-hover utility.** Added a `.scrollbar-hover` CSS class that hides scrollbar thumbs until the user hovers, reducing visual clutter in scrollable panels.

## [0.4.0] - 2026-06-13

### Added

- 🔌 **Tool servers.** Connect external tools via MCP or OpenAPI. Add servers from the new Tool Servers admin tab, verify the connection, and the AI can use them immediately. Supports bearer auth and custom headers.
- 🤖 **Sub-agents.** The AI can now spin up sub-agents to work on tasks in parallel. Each sub-agent gets full tool access and runs as a real chat you can inspect afterwards. Configure concurrency and limits from the new Subagents admin tab.
- ⚡ **Parallel tool execution.** When the AI makes multiple tool calls in one response, they now run concurrently instead of one at a time.
- 🔐 **Signup toggle.** Enable or disable user registration directly from the Users admin tab.
- 🧠 **Context compaction threshold in UI.** The token threshold for automatic context compaction can now be set from the Models admin tab instead of editing `config.toml`.

### Changed

- 🏗️ **Admin panel restructure.** The old Settings and Browser panels have been split into focused tabs: **Web** (search providers + browser backends), **Tool Servers**, and **Subagents**.
- 🌍 **Comprehensive i18n.** 200+ new translation keys across all 10 locales. Almost every remaining hardcoded English string in the UI is now translatable.
- 🏷️ **External tool labels.** Tool calls from external servers show the tool name and server in the chat UI. Sub-agent tasks show as `Sub-agent: "task…"`.

### Fixed

- 🐛 **Plan mode with external tools.** Plan mode now correctly sees tools from connected external servers, not just built-in ones.

## [0.3.5] - 2026-06-13

### Added

- 🌳 **Chat branching from Open WebUI.** Regenerating or editing a message in Open WebUI now creates proper branches in the cptr sidebar, just like it does in OWUI. Requires custom headers on the OWUI connection (copy from Gateway settings).
- 🚦 **Background task filtering.** Open WebUI's automatic title generation, follow-up suggestions, and tag extraction no longer create ghost chats or trigger the agent loop.
- 📡 **More header templates.** Gateway settings now shows the full recommended header config for Open WebUI connections, including message and task type forwarding. One-click copy. Requires Open WebUI ≥ 0.9.7.

### Fixed

- 🐛 **Chat metadata could be empty on second turn.** Fixed an operator precedence issue in message resolution.

## [0.3.4] - 2026-06-12

### Changed

- 🛠️ **Gateway tool call visibility.** Tool calls now appear concisely in gateway responses instead of being hidden from OpenAI-compatible clients.
- ⚙️ **Gateway response model setting.** Choose the model used to generate gateway responses directly from the Gateway settings tab.

## [0.3.3] - 2026-06-12

### Added

- 🌉 **OpenAI-compatible gateway.** Expose cptr workspaces through `/v1/models` and `/v1/chat/completions`, so Open WebUI and other OpenAI-compatible clients can use each workspace as a model with the full cptr agent loop.
- 🔑 **Gateway API keys.** New Gateway admin settings tab for creating, copying, listing, and deleting API keys. Keys are stored hashed and newly generated keys are only shown once.

### Changed

- 🔄 **Gateway streaming support.** Chat tasks can now stream assistant deltas into an OpenAI-style SSE response while still updating cptr chats and sidebar state.
- 🧭 **Frontend dev proxy.** The Vite dev server now proxies `/v1` gateway requests to the backend during local development.

## [0.3.2] - 2026-06-12

### Added

- 🎙️ **Voice memos.** Record audio memos directly from the "+" menu or ⌘⇧M. Recordings are saved to your workspace as audio files with an auto-generated markdown transcript. Uses a save-first architecture with IndexedDB backup so your recording is never lost, even if the network drops. Transcription is powered by any OpenAI-compatible STT API (Whisper, etc.), configurable in Settings > Audio.
- 🔊 **Audio admin settings.** New Audio tab in admin settings with separate controls for enabling voice memos, toggling auto-transcription, and configuring STT credentials (base URL, API key, model).

### Changed

- 🎨 **Consistent admin input styling.** Standardized all input fields in the Configuration admin panel to match the Browser settings design. Uniform height, background, focus states, and label sizing across all admin tabs.

## [0.3.1] - 2026-06-12

### Added

- 🌐 **Browser tools.** Browse the web from chat. Navigate pages, click elements, type into forms, take screenshots, and run JavaScript. Works with local Chrome (auto-launched), Firecrawl, or Browser-Use. Enable in Settings > Browser.
- 🖼️ **Image understanding.** The AI can now read and describe images from your workspace. Open a screenshot or image file and it just works, across all providers.
- 🔴 **Error toasts.** When something goes wrong during a response (API errors, model failures), you'll now see a clear error message in the chat and a toast notification instead of silent failures.

### Fixed

- 🔁 **Responses API multi-turn tool calling.** Fixed an issue where tool calls would stop after the first round when using OpenAI's Responses API. The AI now correctly loops through multiple tool calls as expected.
- 💬 **`/new` command in Telegram/Discord.** Starting a new conversation with `/new` now actually creates a fresh chat instead of continuing the previous one.
- 🛡️ **Responses API spec compliance.** Input messages, tool outputs, and error handling now fully follow the Open Responses specification, preventing unexpected 400 errors.

## [0.3.0] - 2026-06-12

### Added

- 💬 **Messaging bots.** Connect your AI to Telegram, Discord, Slack, WhatsApp, and Signal from Settings. Each bot has full tool access, streams responses in real time, and syncs conversations back to the web UI. Use `/workspace` to switch projects and `/new` to start fresh conversations.
- 📊 **Usage tooltip.** Hover the info icon on completed messages to see token counts and timing.

### Changed

- 🔄 **Live tool progress.** See what tools are running as they execute, not just after they finish.
- 🌍 **i18n updates.** Full translation coverage across all 10 locales.

### Fixed

- 🐛 **Empty model selector.** Shows a helpful label when no models are configured.

## [0.2.3] - 2026-06-12

### Added

- 🧩 **Skills system.** Define reusable instruction sets (SKILL.md files) in your workspace or globally. Skills are auto-discovered and surfaced in the system prompt; the AI loads them on demand via a new `view_skill` tool. Type `$` in the chat input to mention a skill directly.
- 🔔 **Update notifications.** Admins now see a non-intrusive toast when a new version is available, with a link to release notes. Dismissals are remembered for 24 hours. Toggle in Settings > General.
- 📝 **Per-model system prompts.** Configure custom system prompts per model or as a global default from the Models admin page. Supports `{{VARIABLE}}` template placeholders (workspace name, file tree, instructions, skills, OS, date, model).
- 📄 **Workspace system prompt override.** Place a `.cptr/system.md` file in any workspace to fully override the system prompt for that project.

### Changed

- 🔧 **Context-aware tool execution.** Automation tools (`create_automation`, `list_automations`, etc.) now receive full execution context (user ID, model ID) instead of just the workspace path, fixing automations being created as the wrong user.
- 🏷️ **Dynamic page titles.** Browser tab titles now reflect the active file or chat tab (e.g. "stores.ts / myproject / cptr") instead of just the workspace name.
- 🔗 **"Update available" badge in About.** The Settings > About page now shows a link to the latest release when a newer version exists.
- 🌍 **i18n updates.** Added translation keys for system prompts, model templates, update notifications, and connection editing across all 10 supported locales.

## [0.2.2] - 2026-06-11

### Added

- 🤖 **Per-model configuration.** Set custom parameters (temperature, top_p, etc.) for each model or as global defaults. Per-chat overrides still take priority.
- 🧠 **Automatic context compaction.** Long conversations are automatically summarized to keep things running smoothly, no manual intervention needed.
- ➕ **Per-chat parameters.** Override model parameters for a single chat session from the `+` menu.

### Changed

- ⚙️ **Unified settings.** Admin panel merged into Settings. No more separate modal. Admin sections appear automatically for admin users.
- ⌨️ **Shortcut hint in menu.** The Settings menu item now shows its keyboard shortcut.

## [0.2.1] - 2026-06-11

### Added

- 🔍 **Global search modal.** New unified search (⌘K / ⌘⇧F) that finds chats by title *and* message content, plus files by name — across all workspaces or scoped to the active one. Shows recent chats when the query is empty. Replaces the old QuickOpen modal.
- 🌐 **Perplexity web search provider.** Added Perplexity as a first-class search provider (auto-detected between Exa and Tavily when `PERPLEXITY_API_KEY` is set).
- 🌐 **Chat Completions search provider.** Any OpenAI-compatible `/chat/completions` endpoint (e.g. Perplexity Sonar, LiteLLM proxy) can now be used for web search. Configure via Settings or environment variables.
- ➕ **New Chat button per workspace.** Each workspace row in the sidebar now shows a pencil icon on hover to quickly create a new chat.

### Fixed

- 🔍 **Search no longer pinned to last workspace.** When on a non-workspace page (e.g. Automations), search results are now global instead of silently scoped to the last-selected workspace.
- 🔄 **Sidebar chat cache invalidated globally.** Chat events from automations or other tabs now clear the cache for *all* workspaces, so re-expanding any workspace shows fresh data.
- 🔄 **New chats from automations appear in landing page.** The chat landing now debounce-reloads when it receives a socket event for an unknown chat, so automation-created chats appear without a manual refresh.
- 🏷️ **Chat tab labels update from DB title.** Opening a chat from search or sidebar now shows the real title instead of a generic "Chat" label.
- 🔁 **Duplicate new-chat tabs prevented.** Opening a new chat reuses an existing empty/pending chat tab instead of creating duplicates.

### Changed

- 🔗 **URL-driven navigation for chat and file intents.** Clicking a chat or file in the sidebar/search now uses URL query params (`chatId`, `file`, `dir`) which are consumed and cleaned up after navigation, enabling deep-linking and back-button support.
- 🍞 **Improved toast notifications.** Toaster now uses rich colors and close buttons for better visibility.
- 🔒 **Automations sidebar link hidden when chat is disabled.** The Automations nav item is now conditionally shown only when the chat/LLM backend is available.
- ⬆️ **Python 3.10 minimum.** Bumped `requires-python` from `>=3.9` to `>=3.10`.
- 📦 **Added `truststore` dependency.** Uses platform-native TLS certificate stores for better certificate handling.
- 🌍 **i18n for search UI.** Search-related strings added across all 10 supported locales.

## [0.2.0] - 2026-06-09

### Added

- ⏱️ **Automations.** Schedule recurring tasks that run on a timer. Each automation creates a real chat with full tool access, so they can do anything you'd do manually. Manage them from the new `/automations` page or ask the AI to create one.
- 🔔 **Task completion notifications.** Get a browser notification (with optional sound) when a background task finishes. Toggle in Settings > General.
- 🪝 **Webhook notifications.** Send alerts to Slack, Discord, Teams, or any webhook URL when tasks complete. Configure in Settings > General.
- 💬 **Sidebar chat history.** Each workspace now shows its recent chats directly in the sidebar. Click to reopen, updates live as new chats come in.
- 🗃️ **Config file sync.** Settings now persist to `config.toml` on disk, so your configuration survives across reinstalls and can be hand-edited.

### Changed

- 🎨 **Improved artifact cards.** File previews in chat now show a file icon and cleaner styling.

## [0.1.9] - 2026-06-07

### Fixed

- 📦 **PyPI install actually works now.** Hatchling's `exclude` took precedence over `artifacts`, causing every published wheel to ship without the frontend build. The app returned `{"detail":"Not Found"}` on all non-API routes. Switched to `force-include` (matching open-webui's approach), which unconditionally bundles `cptr/frontend/build` into the wheel regardless of exclude rules.

## [0.1.8] - 2026-06-07

### Fixed

- 📦 **Attempted PyPI wheel fix (incomplete).** Changed hatchling `exclude` from a single broad pattern to granular excludes, but the `artifacts` directive still did not override `exclude`. Wheel still shipped without the frontend.

## [0.1.7] - 2026-06-07

### Fixed

- 🔄 **Messages no longer disappear after sending.** Fixed a race condition where the frontend needed a separate GET request after sending a message, creating a window where socket events were dropped. The POST now returns the created messages directly, eliminating the round-trip and the race.

## [0.1.6] - 2026-06-07

### Added

- 📋 **Plan mode.** Request an implementation plan before AI changes.

### Fixed

- 🔒 **Protected `.env` files.** File tools and search now block `.env` and `.env.*` access.

### Changed

- ✨ **Cleaner artifact cards.** Simplified assistant artifact card headers and preview text.

## [0.1.5] - 2026-06-07

### Fixed

- 🗄️ **Alembic migration no longer fails on startup.** Renamed migration revision IDs from 3-character (`001`) to 4-character (`0001`) identifiers, fixing Alembic's `ResolutionError` for partial revision matches.
- 📦 **PyPI wheel no longer bundles frontend source code.** Fixed `.gitignore` paths (old `computr/` → `cptr/`) and added an explicit `exclude` in `pyproject.toml` so only `cptr/frontend/build` ships in the wheel — eliminating ~14,000 unnecessary files including `node_modules`.

## [0.1.4] - 2026-06-06

### Fixed

- 🔄 **Chat streaming no longer drops final content.** Fixed a race where the `done` socket event arrived before the DB commit, causing a transient blank message. The streamed content now stays visible until the reload confirms it.
- 🔄 **Unflushed text no longer lost at end of chat responses.** The final text buffer is now properly flushed and emitted before marking a message as done, across all exit paths (normal completion, cancellation, and errors).
- 🔄 **Intermediate chat state persisted during tool loops.** Content and output items are now saved to the database between tool call iterations, so progress survives crashes or disconnects.
- 🧹 **In-memory task state cleaned up on completion.** The `_task_state` dict entry is now removed when a chat task finishes (done, cancelled, errored, or max iterations), preventing unbounded memory growth.
- 📱 **Sidebar stays closed on mobile.** The sidebar default breakpoint was raised to 1024px and an auto-close listener now collapses it whenever the viewport shrinks below 768px.
- 🔄 **Stale chat loads discarded.** Rapid chat switches no longer apply data from a slow earlier load, fixing a race condition that could show the wrong conversation.

### Changed

- ⚡ **All blocking filesystem I/O offloaded to threads.** File reads, writes, directory walks, search, archive creation, uploads, renames, and deletions in the workspace and tool routers now run via `asyncio.to_thread()`, preventing event-loop stalls under heavy file operations.
- ⚡ **Port scanner made fully async.** Platform-specific port scanning (Darwin `lsof`, Linux `/proc`, Windows `netstat`) and PID-to-process lookups now use `asyncio.create_subprocess_exec` or `asyncio.to_thread` instead of blocking `subprocess.run`.
- ⚡ **Welcome endpoint system info collected off the event loop.** The `/welcome` handler now gathers hostname, memory, disk, CPU, network, and process data in a background thread.

## [0.1.3] - 2026-06-06

### Fixed

- 📱 **Tool calls no longer overflow on mobile.** Fixed tool call rendering that could exceed the parent container width on narrow screens.
- 📱 **Settings tabs scroll horizontally on mobile.** The settings tab bar now scrolls on narrow screens instead of overflowing.

### Changed

- 🔤 **Tool call labels show filenames instead of full paths.** Tool call summaries like `Read`, `Edit`, and `Write` now display just the filename (e.g. `Read stores.ts`) instead of the full absolute path, keeping labels readable on all screen sizes.
- 📋 **Redesigned changelog modal.** The changelog is now presented as a clean, continuous vertical list with color-coded section badges.

## [0.1.2] - 2026-06-06

### Fixed

- 📱 **Improved mobile keyboard handling.** The terminal and chat now resize correctly when the on-screen keyboard opens on iOS and Android.
- 📱 **Fixed page bouncing on mobile.** Eliminated unwanted page scrolling and bounce effects on touch devices.

### Changed

- 🔄 **Model selection syncs across devices.** Your selected chat model now persists across browsers and devices instead of being saved locally.

## [0.1.1] - 2026-06-06

### Fixed

- 🛑 **File browser no longer refreshes constantly.** Replaced the macOS `PollingObserver` (which generated a feedback loop of phantom filesystem events) with the native `FSEventsObserver`. Background refreshes are now silent — no more loading spinner flash on every update.
- 🔇 **Eliminated noisy filesystem watcher events.** The watcher now ignores changes in `.git`, `__pycache__`, `.DS_Store`, and `node_modules` directories, which were triggering unnecessary file browser refreshes.
- ⚡ **Centralized git status store.** All components (GitBar, GitView, FileEditor, layout) now share a single `gitStatusStore` instead of each independently polling `git/status`. On page load, this reduces git status API calls from ~6+ down to 1.
- 🔁 **Reduced git polling frequency.** Removed the 5-second git status polling intervals that were running in multiple components simultaneously.

## [0.1.0] - 2026-06-06

### Added

- 🚀 **Initial release.** First public version of cptr: your computer, from anywhere. Code, manage, and control your machine from the web.
- 🖥️ **Terminal emulator.** Full PTY-backed terminal accessible from the browser with support for macOS and Linux.
- 💬 **AI chat.** Built-in chat panel with multi-provider LLM support (OpenAI, Anthropic, Ollama, and OpenAI-compatible endpoints), model selector, tool calling, and streaming responses.
- 🔧 **Tool system.** Extensible tool framework enabling AI agents to interact with the local filesystem, run commands, search the web (Brave, DuckDuckGo, Exa, Tavily), and read URLs. Streaming JSON parser for improved tool-calling reliability.
- 📎 **File mentions.** Type `@` in the chat input to mention files with an inline suggestion popup, giving the AI context about your codebase.
- 🔄 **Queued messages.** Queue follow-up messages while the AI is responding — they'll be sent automatically when the current response completes.
- ✏️ **Output editing.** Review and edit AI-generated file changes before applying them.
- 📁 **File browser.** Web-based file explorer with directory navigation, file viewing, file icons by extension, and management capabilities.
- ⌨️ **Keyboard shortcuts.** Customizable keybinding system with a dedicated settings panel, including support for new-tab, quick-open, and other common actions.
- 📐 **Resizable sidebar.** Drag-to-resize sidebar with persistent width and smooth panel resize handles.
- 🔍 **Quick open.** Cmd+K modal with keyboard pill hints for fast file and command navigation.
- 🌐 **Proxy middleware.** Reverse-proxy system for forwarding local ports with automatic port detection and notification.
- 📁 **Workspace management.** Manage multiple project directories from a single instance.
- 📊 **Chat history.** Persistent chat list with automatic title generation, scrolling, and pagination.
- 🔐 **Authentication.** Username/password authentication with JWT-based session management.
- 🎨 **Admin settings.** Settings UI for managing AI connections and app configuration.
- 🐳 **Docker support.** Multi-stage Dockerfile and GitHub Actions workflow for building and publishing to GHCR.
- 📦 **PyPI packaging.** Hatchling-based build with frontend assets bundled into the wheel, published via trusted OIDC publishing.
