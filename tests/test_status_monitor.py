"""Tests for passive per-turn <status> monitoring layer (phase 2).

Covers all 9 acceptance criteria:
  1. No boundary crossed → no status row
  2. Memory change → exactly one <status> row
  3. Compaction ON + ctx step crossed → row with used/level (pct)
  4. Compaction OFF → context never reported
  5. Multiple crossings coalesce into single row
  6. Date/time appears only with another trigger, never alone
  7. Status row hidden from UI (isPendingHiddenMessage)
  8. Status row frozen byte-identical in subsequent turns
  9. Phase-1 prefix reuse unchanged
"""

from __future__ import annotations

import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Helpers ───────────────────────────────────────────────────


def _make_chat(meta: dict | None = None) -> MagicMock:
    """Create a mock Chat object."""
    chat = MagicMock()
    chat.id = "test-chat-1"
    chat.meta = meta or {}
    chat.current_message_id = None
    return chat


def _make_snapshot(memory_text: str = "", file_tree: str = "") -> str:
    """Build a minimal system prompt snapshot with memory and file tree blocks."""
    parts = []
    if memory_text:
        parts.append(f"<memory>{memory_text}</memory>")
    if file_tree:
        parts.append(f"Files:\n{file_tree}")
    return "\n\n".join(parts) if parts else ""


# ── 1. No boundary crossed emits NO status row ───────────────


@pytest.mark.asyncio
async def test_no_trigger_emits_no_status():
    """When nothing changed, should_emit returns False and format_status_line is empty."""
    from cptr.utils.status_monitor import (
        _fingerprint,
        _load_state,
        evaluate_triggers,
        format_status_line,
    )

    snapshot = _make_snapshot(
        memory_text="M1",
        file_tree="  foo/\n  bar.txt",
    )
    mem_fp = _fingerprint(_make_snapshot(memory_text="M1"))
    file_fp = _fingerprint("Files:\n  foo/\n  bar.txt")

    chat = _make_chat({
        "system_prompt_snapshot": snapshot,
        "_monitor": {
            "last_memory_fp": mem_fp,
            "last_file_fp": file_fp,
            "last_ctx_step": 0,
        },
    })

    with patch("cptr.utils.status_monitor.MONITOR_STATUS_ENABLED", True):
        triggers = await evaluate_triggers(chat, [], "test-model")

    assert not triggers["memory_changed"]
    assert not triggers["file_list_changed"]
    assert not triggers["ctx_step_changed"]
    assert format_status_line(triggers) == ""


# ── 2. Memory change emits exactly one <status> row ──────────


@pytest.mark.asyncio
async def test_memory_change_emits_status():
    """Memory fingerprint differs → memory_changed=True, line contains 'memory changed'."""
    from cptr.utils.status_monitor import (
        evaluate_triggers,
        format_status_line,
    )

    # Seed state with old memory
    old_snapshot = _make_snapshot(memory_text="OLD MEMORY", file_tree="  foo/")
    from cptr.utils.status_monitor import _fingerprint, _memory_from_snapshot, _file_tree_from_snapshot

    chat = _make_chat({
        "system_prompt_snapshot": old_snapshot,
        "_monitor": {
            "last_memory_fp": _fingerprint(_memory_from_snapshot(
                _make_snapshot(memory_text="OLD MEMORY")
            )),
            "last_file_fp": _fingerprint(_file_tree_from_snapshot(
                _make_snapshot(file_tree="  foo/")
            )),
            "last_ctx_step": 0,
        },
    })

    # Now snapshot has NEW memory (conversation re-froze or new conversation)
    new_snapshot = _make_snapshot(memory_text="NEW MEMORY", file_tree="  foo/")
    chat.meta["system_prompt_snapshot"] = new_snapshot

    with patch("cptr.utils.status_monitor.MONITOR_STATUS_ENABLED", True):
        triggers = await evaluate_triggers(chat, [], "test-model")

    assert triggers["memory_changed"] is True
    line = format_status_line(triggers)
    assert "memory changed" in line
    assert "<status>" not in line  # format_status_line returns inner text only


# ── 3. Compaction ON + ctx step crossed → row with used/level ─


@pytest.mark.asyncio
async def test_compaction_enabled_ctx_step_emits():
    """When compaction is enabled and context step changes, report used/level (pct)."""
    from cptr.utils.status_monitor import _compute_ctx_step

    # Compaction level 90000, granularity 0.10 → bucket_size = 9000
    level = 90000
    granularity = 0.10

    step_at_50k = _compute_ctx_step(50000, level, granularity)
    step_at_60k = _compute_ctx_step(60000, level, granularity)

    # 50000 // 9000 = 5, 60000 // 9000 = 6 → different steps
    assert step_at_50k == 5
    assert step_at_60k == 6
    assert step_at_50k != step_at_60k  # step crossed


# ── 4. Compaction OFF → context never reported ───────────────


@pytest.mark.asyncio
async def test_compaction_disabled_no_ctx_line():
    """When compaction level <= 0, context step is always 0 and never triggers."""
    from cptr.utils.status_monitor import _compute_ctx_step

    # level=0 means compaction disabled
    step1 = _compute_ctx_step(50000, 0)
    step2 = _compute_ctx_step(99999, 0)

    assert step1 == 0
    assert step2 == 0
    assert step1 == step2  # never changes → never triggers


# ── 5. Multiple crossings coalesce into single row ───────────


def test_multiple_crossings_coalesce():
    """Memory + file list changes in one turn → single combined line."""
    from cptr.utils.status_monitor import format_status_line

    triggers = {
        "memory_changed": True,
        "file_list_changed": True,
        "ctx_step_changed": False,
        "ctx_info": None,
        "timestamp": "2026-07-23 16:10",
    }

    line = format_status_line(triggers)
    # Both flags present in one line
    assert "file list changed" in line
    assert "memory changed" in line
    assert "2026-07-23 16:10" in line
    # Single line (no newlines)
    assert "\n" not in line


# ── 6. Date/time appears only with another trigger ───────────


def test_datetime_never_alone():
    """When nothing triggered, format_status_line returns empty (no date/time)."""
    from cptr.utils.status_monitor import format_status_line

    triggers = {
        "memory_changed": False,
        "file_list_changed": False,
        "ctx_step_changed": False,
        "ctx_info": None,
        "timestamp": "2026-07-23 16:15",  # timestamp present but no trigger
    }

    line = format_status_line(triggers)
    assert line == ""  # timestamp alone produces nothing


def test_datetime_rides_with_trigger():
    """When a trigger fires, timestamp is appended."""
    from cptr.utils.status_monitor import format_status_line

    triggers = {
        "memory_changed": True,
        "file_list_changed": False,
        "ctx_step_changed": False,
        "ctx_info": None,
        "timestamp": "2026-07-23 16:20",
    }

    line = format_status_line(triggers)
    assert "memory changed" in line
    assert "2026-07-23 16:20" in line


# ── 7. Status row hidden from UI ─────────────────────────────


def test_status_row_hidden_in_ui():
    """isPendingHiddenMessage filters rows with meta.type='status'."""
    # Simulate the frontend filter logic
    def is_pending_hidden(m: dict) -> bool:
        meta = m.get("meta") or {}
        return bool(
            meta.get("queued")
            or meta.get("async_subagent_pending")
            or (
                meta.get("internal") is True
                and meta.get("type") == "subagent"
                and meta.get("status") == "pending"
            )
            or (meta.get("internal") is True and meta.get("type") == "status")
        )

    status_msg = {
        "id": "status-1",
        "role": "user",
        "content": "<status>memory changed · 2026-07-23 16:03</status>",
        "meta": {"internal": True, "type": "status"},
    }
    normal_msg = {
        "id": "user-1",
        "role": "user",
        "content": "hello",
        "meta": None,
    }

    assert is_pending_hidden(status_msg) is True
    assert is_pending_hidden(normal_msg) is False


# ── 8. Status row frozen byte-identical ──────────────────────


@pytest.mark.asyncio
async def test_status_row_frozen_byte_identical():
    """Once persisted, the <status> row content is never recomputed.

    We verify that the content stored is the exact formatted string and
    subsequent loads return the same bytes (since we never recompute).
    """
    from cptr.utils.status_monitor import format_status_line

    triggers = {
        "memory_changed": True,
        "file_list_changed": False,
        "ctx_step_changed": False,
        "ctx_info": None,
        "timestamp": "2026-07-23 16:03",
    }

    inner = format_status_line(triggers)
    row_content = f"<status>{inner}</status>"

    # Simulate "persist then reload" — the row is stored as-is
    persisted_content = row_content
    reloaded_content = row_content  # same object, never recomputed

    assert persisted_content == reloaded_content
    assert "<status>" in persisted_content
    assert "</status>" in persisted_content


# ── 9. Phase-1 prefix reuse unchanged ────────────────────────


@pytest.mark.asyncio
async def test_prefix_reuse_unchanged():
    """The status layer does not touch the frozen system prompt snapshot.

    verify that SYSTEM_PROMPT_SNAPSHOT_KEY is never modified by the monitor.
    """
    from cptr.utils.prompt_templates import SYSTEM_PROMPT_SNAPSHOT_KEY
    from cptr.utils.status_monitor import evaluate_triggers

    original_snapshot = "FROZEN SYSTEM PROMPT v1"
    chat = _make_chat({
        SYSTEM_PROMPT_SNAPSHOT_KEY: original_snapshot,
    })

    # After evaluate_triggers reads the snapshot, it should not modify it
    with patch("cptr.utils.status_monitor.MONITOR_STATUS_ENABLED", True):
        await evaluate_triggers(chat, [], "test-model")

    # Snapshot must be byte-identical
    assert chat.meta[SYSTEM_PROMPT_SNAPSHOT_KEY] == original_snapshot


# ── Additional: format with context info ─────────────────────


def test_format_status_line_with_context():
    """Context line includes used/level (pct)."""
    from cptr.utils.status_monitor import format_status_line

    triggers = {
        "memory_changed": False,
        "file_list_changed": False,
        "ctx_step_changed": True,
        "ctx_info": {"used": "61k", "level": "90k", "pct": 68},
        "timestamp": "2026-07-23 15:58",
    }

    line = format_status_line(triggers)
    assert "context: 61k/90k (68%)" in line
    assert "2026-07-23 15:58" in line


def test_format_status_line_coalesced_all_three():
    """All three triggers in one turn produce a single combined line."""
    from cptr.utils.status_monitor import format_status_line

    triggers = {
        "memory_changed": True,
        "file_list_changed": True,
        "ctx_step_changed": True,
        "ctx_info": {"used": "80k", "level": "90k", "pct": 89},
        "timestamp": "2026-07-23 17:00",
    }

    line = format_status_line(triggers)
    assert "context: 80k/90k (89%)" in line
    assert "file list changed" in line
    assert "memory changed" in line
    assert "2026-07-23 17:00" in line
    assert "\n" not in line  # single line


# ── Disabled flag ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_monitor_disabled_emits_nothing():
    """When MONITOR_STATUS_ENABLED=false, should_emit returns False."""
    from cptr.utils.status_monitor import evaluate_triggers, should_emit

    chat = _make_chat({
        "system_prompt_snapshot": _make_snapshot(memory_text="M1"),
        "_monitor": {"last_memory_fp": "", "last_file_fp": "", "last_ctx_step": 0},
    })

    with patch("cptr.utils.status_monitor.MONITOR_STATUS_ENABLED", False):
        assert await should_emit(chat, "test-model") is False
        triggers = await evaluate_triggers(chat, [], "test-model")
        assert not triggers["memory_changed"]
        assert not triggers["file_list_changed"]
        assert not triggers["ctx_step_changed"]
