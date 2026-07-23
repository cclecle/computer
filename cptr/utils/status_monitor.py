"""Passive per-turn <status> monitoring layer (phase 2).

Evaluates fingerprint triggers (memory, file list, context step) and
formats a terse <status>…</status> line.  State is persisted in
chat.meta["_monitor"] so it survives restarts.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from cptr.env import MONITOR_CTX_GRANULARITY, MONITOR_STATUS_ENABLED
from cptr.models import Chat
from cptr.utils.config import now_ms
from cptr.utils.context import (
    estimate_messages_tokens,
    estimate_tokens,
    load_compact_token_threshold,
    usage_context_tokens,
)
from cptr.utils.gitignore import is_gitignored_rel, load_gitignore
from cptr.utils.prompt_templates import SYSTEM_PROMPT_SNAPSHOT_KEY

logger = logging.getLogger(__name__)

META_KEY = "_monitor"

# Directories never worth watching: VCS internals, dependency and build
# output, and cptr's own chat store — which is rewritten on every turn and
# would otherwise fire the file trigger forever.
SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".cptr",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".next",
    "build",
    "dist",
    ".svelte-kit",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".idea",
}

# Hard cap so a huge workspace can never stall a turn.
MAX_WALK_ENTRIES = 20_000

# ── Config ───────────────────────────────────────────────────


def _enabled() -> bool:
    return MONITOR_STATUS_ENABLED


# ── Fingerprinting ───────────────────────────────────────────


def _fingerprint(text: str) -> str:
    """SHA-256 hex digest of *text*, truncated to 16 chars."""
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


def workspace_file_digest(workspace: str) -> str:
    """Fingerprint every visible file in *workspace* by path, mtime and size.

    Deliberately *not* the frozen prompt's file tree: that listing is two
    levels deep and carries names only, so editing a file — or adding one
    three directories down — left it byte-identical and the trigger never
    fired. Hashing stat metadata over the whole tree catches edits, creates,
    deletes and renames alike.

    Gitignored paths are skipped so build output, logs and caches don't fire
    the trigger on every turn. Blocking I/O — call via a thread.
    """
    root = Path(workspace) if workspace else None
    if root is None or not root.is_dir():
        return ""

    base, patterns = load_gitignore(root)
    # Patterns are relative to the repo root, which may sit above the
    # workspace; resolve the offset once instead of per entry.
    try:
        prefix = root.resolve().relative_to(base).as_posix()
    except ValueError:
        prefix = ""
    prefix = "" if prefix == "." else prefix

    records: list[str] = []
    # Breadth-first over name-sorted entries: with a cap in play the walk has
    # to visit the same files in the same order every time, or a workspace
    # past the cap would fire the trigger just because the filesystem handed
    # back a different scandir order.
    queue: deque[tuple[Path, str]] = deque([(root, "")])

    while queue:
        current, current_rel = queue.popleft()
        try:
            with os.scandir(current) as it:
                entries = sorted(it, key=lambda e: e.name)
        except OSError:
            continue

        for entry in entries:
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                continue
            if is_dir and entry.name in SKIP_DIRS:
                continue

            rel = f"{current_rel}/{entry.name}" if current_rel else entry.name
            match_rel = f"{prefix}/{rel}" if prefix else rel
            if is_gitignored_rel(match_rel, patterns, is_dir=is_dir):
                continue

            if is_dir:
                queue.append((Path(entry.path), rel))
                continue

            try:
                st = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            records.append(f"{rel}\0{st.st_mtime_ns}\0{st.st_size}")

        if len(records) >= MAX_WALK_ENTRIES:
            records = records[:MAX_WALK_ENTRIES]
            break

    records.sort()
    return _fingerprint("\n".join(records))


async def _live_fingerprints(chat: Chat) -> tuple[str, str]:
    """Return (memory_fp, file_fp) computed from LIVE state, not the snapshot."""
    workspace = (chat.meta or {}).get("workspace") or ""

    try:
        from cptr.utils.memory import build_frozen_memory_prompt

        live_memory = await build_frozen_memory_prompt(chat.user_id, workspace)
    except Exception:
        logger.debug("[monitor] memory fingerprint failed", exc_info=True)
        live_memory = ""

    try:
        file_fp = await asyncio.to_thread(workspace_file_digest, workspace)
    except Exception:
        logger.debug("[monitor] file fingerprint failed", exc_info=True)
        file_fp = ""

    return _fingerprint(live_memory), file_fp


# ── Context step (compaction-anchored) ───────────────────────


async def _current_context_tokens(
    chat_id: str, message_id: str | None, model: str
) -> tuple[int, int]:
    """Return (current_tokens, compaction_level).

    compaction_level is 0 when compaction is disabled.
    """
    level = await load_compact_token_threshold(model)
    if not message_id:
        return (0, level)

    # Fast path: read real usage from the latest checkpoint
    from cptr.models import ChatMessage

    all_msgs = await ChatMessage.get_all_by_chat(chat_id)
    msg_map = {m.id: m for m in all_msgs}

    # Walk back from message_id to find the latest usage checkpoint
    cur = msg_map.get(message_id)
    chain: list[ChatMessage] = []
    while cur:
        chain.append(cur)
        cur = msg_map.get(cur.parent_id) if cur.parent_id else None
    chain.reverse()

    for i in range(len(chain) - 1, -1, -1):
        msg = chain[i]
        if msg.chat_summary:
            # Past a compaction boundary; can't use old usage
            break
        if msg.role == "assistant" and msg.usage:
            tokens = usage_context_tokens(msg.usage)
            if tokens > 0:
                # Add trailing messages after this checkpoint
                trailing = chain[i + 1 :]
                if trailing:
                    tokens += estimate_messages_tokens(
                        [{"role": m.role, "content": m.content or ""} for m in trailing]
                    )
                return (tokens, level)

    # Fallback: estimate from messages + system prompt snapshot
    chat = await Chat.get_by_id(chat_id)
    snapshot = (chat.meta or {}).get(SYSTEM_PROMPT_SNAPSHOT_KEY, "") if chat else ""
    tokens = estimate_tokens(snapshot) + estimate_messages_tokens(
        [{"role": m.role, "content": m.content or ""} for m in all_msgs]
    )
    return (tokens, level)


def _compute_ctx_step(tokens: int, level: int, granularity: float | None = None) -> int:
    """Bucketed step index relative to the compaction level.

    Returns 0 when compaction is disabled (level <= 0).
    """
    if level <= 0:
        return 0
    g = granularity if granularity is not None else MONITOR_CTX_GRANULARITY
    if g <= 0:
        g = 0.10
    bucket_size = max(1, int(level * g))
    return tokens // bucket_size


# ── State persistence ────────────────────────────────────────


def _load_state(meta: dict | None) -> dict:
    """Load monitor state from chat.meta, returning defaults if absent."""
    raw = (meta or {}).get(META_KEY)
    if isinstance(raw, dict):
        return raw
    return {"last_memory_fp": "", "last_file_fp": "", "last_ctx_step": 0}


async def _save_state(chat_id: str, state: dict) -> None:
    """Persist monitor state into chat.meta[META_KEY]."""
    chat = await Chat.get_by_id(chat_id)
    if not chat:
        return
    meta = dict(chat.meta or {})
    meta[META_KEY] = state
    await Chat.update_meta(chat_id, meta, now_ms())


# ── Trigger evaluation ───────────────────────────────────────


def _idle_triggers() -> dict:
    return {
        "memory_changed": False,
        "file_list_changed": False,
        "ctx_step_changed": False,
        "ctx_step": 0,
        "ctx_info": None,
        "timestamp": "",
        "memory_fp": "",
        "file_fp": "",
    }


def _fmt_tokens(n: int) -> str:
    return f"{n // 1000}k" if n >= 1000 else str(n)


async def _ctx_state(
    chat: Chat, model: str, granularity: float | None
) -> tuple[int, bool, dict | None]:
    """Return (ctx_step, changed, ctx_info) for the chat's current leaf."""
    if not chat.current_message_id:
        return (0, False, None)

    tokens, level = await _current_context_tokens(chat.id, chat.current_message_id, model)
    step = _compute_ctx_step(tokens, level, granularity)
    ctx_info = None
    if level > 0:
        ctx_info = {
            "used": _fmt_tokens(tokens),
            "level": _fmt_tokens(level),
            "pct": round((tokens / level) * 100),
        }
    changed = step != _load_state(chat.meta).get("last_ctx_step", 0)
    return (step, changed, ctx_info)


async def evaluate_triggers(
    chat: Chat,
    model: str = "",
    *,
    granularity: float | None = None,
) -> dict:
    """Evaluate which triggers have crossed since the last emit.

    Returns dict with keys:
        memory_changed, file_list_changed, ctx_step_changed, ctx_step,
        ctx_info (dict with used/level/pct or None), timestamp, and the
        freshly computed memory_fp / file_fp so update_state_after_emit can
        record exactly what was compared rather than re-reading disk.
    """
    if not _enabled():
        return _idle_triggers()

    state = _load_state(chat.meta)
    memory_fp, file_fp = await _live_fingerprints(chat)
    ctx_step, ctx_step_changed, ctx_info = await _ctx_state(chat, model, granularity)

    return {
        "memory_changed": memory_fp != state.get("last_memory_fp", ""),
        "file_list_changed": file_fp != state.get("last_file_fp", ""),
        "ctx_step_changed": ctx_step_changed,
        "ctx_step": ctx_step,
        "ctx_info": ctx_info,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "memory_fp": memory_fp,
        "file_fp": file_fp,
    }


# ── Format the <status> line ─────────────────────────────────


def format_status_line(triggers: dict) -> str:
    """Build the inner text of the <status> line from trigger flags.

    Returns empty string if nothing triggered.
    """
    parts: list[str] = []

    if triggers.get("ctx_step_changed") and triggers.get("ctx_info"):
        ci = triggers["ctx_info"]
        parts.append(f"context: {ci['used']}/{ci['level']} ({ci['pct']}%)")

    if triggers.get("file_list_changed"):
        parts.append("file list changed")

    if triggers.get("memory_changed"):
        parts.append("memory changed")

    if not parts:
        return ""

    ts = triggers.get("timestamp", "")
    if ts:
        parts.append(ts)

    return " · ".join(parts)


# ── State update after emit ──────────────────────────────────


async def update_state_after_emit(chat_id: str, triggers: dict) -> None:
    """Record the fingerprints that were just reported to the model.

    Takes the fingerprints straight from *triggers* rather than re-reading
    disk: a file touched between evaluation and this call would otherwise be
    baked into the new state and never reported at all.
    """
    chat = await Chat.get_by_id(chat_id)
    if not chat:
        return

    state = dict(_load_state(chat.meta))
    state["last_memory_fp"] = triggers.get("memory_fp", "")
    state["last_file_fp"] = triggers.get("file_fp", "")
    state["last_ctx_step"] = triggers.get("ctx_step", 0)

    await _save_state(chat_id, state)


# ── Seed state from live state (conversation start) ──────────


async def seed_state(chat_id: str) -> Chat | None:
    """Seed fingerprints on a chat's first turn so stable state never emits.

    Returns the chat with the seeded state applied, so the caller evaluates
    triggers against what was just persisted instead of a stale copy.
    """
    chat = await Chat.get_by_id(chat_id)
    if not chat or not _enabled():
        return chat

    state = dict(_load_state(chat.meta))
    # Empty fingerprints mean unseeded — a fresh conversation.
    if state.get("last_memory_fp") or state.get("last_file_fp"):
        return chat

    state["last_memory_fp"], state["last_file_fp"] = await _live_fingerprints(chat)
    await _save_state(chat_id, state)
    return await Chat.get_by_id(chat_id)