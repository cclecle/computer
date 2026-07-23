"""Passive per-turn <status> monitoring layer (phase 2).

Evaluates fingerprint triggers (memory, file list, context step) and
formats a terse <status>…</status> line.  State is persisted in
chat.meta["_monitor"] so it survives restarts.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

from cptr.env import MONITOR_CTX_GRANULARITY, MONITOR_STATUS_ENABLED
from cptr.models import Chat
from cptr.utils.config import now_ms
from cptr.utils.context import (
    estimate_messages_tokens,
    estimate_tokens,
    load_compact_token_threshold,
    usage_context_tokens,
)
from cptr.utils.prompt_templates import SYSTEM_PROMPT_SNAPSHOT_KEY, resolve_system_prompt

logger = logging.getLogger(__name__)

META_KEY = "_monitor"

# ── Config ───────────────────────────────────────────────────


def _enabled() -> bool:
    return MONITOR_STATUS_ENABLED


# ── Fingerprinting ───────────────────────────────────────────


def _fingerprint(text: str) -> str:
    """SHA-256 hex digest of *text*, truncated to 16 chars."""
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


def _memory_from_snapshot(snapshot: str | None) -> str:
    """Extract the <memory> block from a frozen system prompt snapshot."""
    if not snapshot:
        return ""
    start = snapshot.find("<memory>")
    if start == -1:
        return ""
    end = snapshot.find("</memory>", start)
    if end == -1:
        return ""
    return snapshot[start:end + len("</memory>")]


def _file_tree_from_snapshot(snapshot: str | None) -> str:
    """Extract the file tree section from a frozen system prompt snapshot.

    The file tree appears after 'Files:\n' in the system prompt.
    """
    if not snapshot:
        return ""
    marker = "Files:\n"
    idx = snapshot.find(marker)
    if idx == -1:
        return ""
    return snapshot[idx:]


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


async def evaluate_triggers(
    chat: Chat,
    messages: list,
    model: str = "",
    *,
    granularity: float | None = None,
) -> dict:
    """Evaluate which triggers have crossed since the last emit.

    Returns dict with keys:
        memory_changed, file_list_changed, ctx_step_changed,
        ctx_info (dict with used/level/pct or None),
        timestamp
    """
    if not _enabled():
        return {
            "memory_changed": False,
            "file_list_changed": False,
            "ctx_step_changed": False,
            "ctx_info": None,
            "timestamp": "",
        }

    state = _load_state(chat.meta)
    workspace = (chat.meta or {}).get("workspace", "")

    # ── Memory fingerprint (LIVE, not frozen snapshot) ──
    try:
        from cptr.utils.memory import build_frozen_memory_prompt
        live_memory = await build_frozen_memory_prompt(chat.user_id, workspace or "")
    except Exception:
        live_memory = ""
    current_mem_fp = _fingerprint(live_memory)
    memory_changed = current_mem_fp != state.get("last_memory_fp", "")

    # ── File list fingerprint (LIVE, not frozen snapshot) ──
    try:
        from cptr.utils.prompt_templates import _get_file_tree
        live_file_tree = _get_file_tree(workspace or "")
    except Exception:
        live_file_tree = ""
    current_file_fp = _fingerprint(live_file_tree)
    file_list_changed = current_file_fp != state.get("last_file_fp", "")

    # ── Context step ──
    ctx_info = None
    ctx_step_changed = False
    current_ctx_step = 0

    # Find the current leaf message id
    current_msg_id = chat.current_message_id
    if current_msg_id:
        tokens, level = await _current_context_tokens(chat.id, current_msg_id, model)
        current_ctx_step = _compute_ctx_step(tokens, level, granularity)
        if level > 0:
            pct = round((tokens / level) * 100) if level > 0 else 0
            # Format tokens in k notation
            def _fmt(n: int) -> str:
                if n >= 1000:
                    return f"{n // 1000}k"
                return str(n)

            ctx_info = {
                "used": _fmt(tokens),
                "level": _fmt(level),
                "pct": pct,
            }
        last_step = state.get("last_ctx_step", 0)
        ctx_step_changed = current_ctx_step != last_step

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

    return {
        "memory_changed": memory_changed,
        "file_list_changed": file_list_changed,
        "ctx_step_changed": ctx_step_changed,
        "ctx_step": current_ctx_step,
        "ctx_info": ctx_info,
        "timestamp": timestamp,
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


async def _get_live_fingerprints(chat: Chat) -> tuple[str, str]:
    """Return (memory_fp, file_fp) from LIVE state."""
    workspace = (chat.meta or {}).get("workspace", "")
    try:
        from cptr.utils.memory import build_frozen_memory_prompt
        live_memory = await build_frozen_memory_prompt(chat.user_id, workspace or "")
    except Exception:
        live_memory = ""
    try:
        from cptr.utils.prompt_templates import _get_file_tree
        live_file_tree = _get_file_tree(workspace or "")
    except Exception:
        live_file_tree = ""
    return _fingerprint(live_memory), _fingerprint(live_file_tree)


async def update_state_after_emit(
    chat_id: str,
    snapshot: str | None,
    ctx_step: int,
) -> None:
    """Update fingerprints and ctx_step after a successful emit."""
    chat = await Chat.get_by_id(chat_id)
    if not chat:
        return

    mem_fp, file_fp = await _get_live_fingerprints(chat)
    state = _load_state(chat.meta)
    state["last_memory_fp"] = mem_fp
    state["last_file_fp"] = file_fp
    state["last_ctx_step"] = ctx_step

    await _save_state(chat_id, state)


# ── Seed state from live state (conversation start) ──────────


async def seed_state_from_snapshot(chat_id: str, snapshot: str | None) -> None:
    """Seed fingerprints from LIVE state so stable state emits never."""
    chat = await Chat.get_by_id(chat_id)
    if not chat:
        return

    state = _load_state(chat.meta)
    # Only seed if not already seeded (empty fingerprints = unseeded)
    if not state.get("last_memory_fp") and not state.get("last_file_fp"):
        mem_fp, file_fp = await _get_live_fingerprints(chat)
        state["last_memory_fp"] = mem_fp
        state["last_file_fp"] = file_fp
        await _save_state(chat_id, state)


# ── Public convenience: should we emit? ──────────────────────


async def should_emit(chat: Chat, model: str = "") -> bool:
    """Quick check: will any trigger fire this turn?"""
    triggers = await evaluate_triggers(chat, [], model)
    return any([
        triggers["memory_changed"],
        triggers["file_list_changed"],
        triggers["ctx_step_changed"],
    ])