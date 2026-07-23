"""Tests for the passive per-turn <status> monitoring layer (phase 2).

The layer notices out-of-band drift the frozen system prompt can no longer
report — memory edits, workspace file changes, context growth — and injects a
single terse row so the agent learns about it without breaking prefix reuse.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from cptr.utils.status_monitor import (
    _compute_ctx_step,
    evaluate_triggers,
    format_status_line,
    workspace_file_digest,
)

# ── Helpers ───────────────────────────────────────────────────


def _make_chat(meta: dict | None = None) -> MagicMock:
    chat = MagicMock()
    chat.id = "test-chat-1"
    chat.user_id = "test-user"
    chat.meta = meta or {}
    chat.current_message_id = None
    return chat


def _state(memory_fp: str = "", file_fp: str = "", ctx_step: int = 0) -> dict:
    return {
        "_monitor": {
            "last_memory_fp": memory_fp,
            "last_file_fp": file_fp,
            "last_ctx_step": ctx_step,
        }
    }


def _fake_fingerprints(memory_fp: str, file_fp: str):
    async def _impl(_chat):
        return (memory_fp, file_fp)

    return patch("cptr.utils.status_monitor._live_fingerprints", _impl)


@pytest.fixture
def workspace(tmp_path):
    """A workspace with a nested file and a .gitignore, like a real project."""
    (tmp_path / ".gitignore").write_text("*.log\nbuilt/\n")
    (tmp_path / "README.md").write_text("readme")
    nested = tmp_path / "pkg" / "utils"
    nested.mkdir(parents=True)
    (nested / "deep.py").write_text("original")
    return tmp_path


# ── Workspace digest: the trigger must survive real edits ────


def test_digest_is_stable_when_nothing_changes(workspace):
    """Traversal order must not leak into the digest, or every turn fires."""
    digests = {workspace_file_digest(str(workspace)) for _ in range(3)}

    assert len(digests) == 1


def test_digest_changes_when_a_nested_file_is_edited(workspace):
    """The bug this layer kept missing: an edit three levels down.

    The frozen prompt's file tree is two levels deep and names-only, so it
    stayed byte-identical here and the trigger never fired.
    """
    before = workspace_file_digest(str(workspace))
    target = workspace / "pkg" / "utils" / "deep.py"
    target.write_text("original plus more content")

    assert workspace_file_digest(str(workspace)) != before


def test_digest_changes_when_a_deep_file_is_added(workspace):
    before = workspace_file_digest(str(workspace))
    (workspace / "pkg" / "utils" / "brand_new.py").write_text("x")

    assert workspace_file_digest(str(workspace)) != before


def test_digest_changes_when_a_file_is_deleted(workspace):
    before = workspace_file_digest(str(workspace))
    (workspace / "README.md").unlink()

    assert workspace_file_digest(str(workspace)) != before


def test_digest_ignores_gitignored_paths(workspace):
    """Build output and logs must not fire the trigger on every turn."""
    before = workspace_file_digest(str(workspace))
    (workspace / "debug.log").write_text("noise")
    built = workspace / "built"
    built.mkdir()
    (built / "bundle.js").write_text("noise")

    assert workspace_file_digest(str(workspace)) == before


def test_digest_ignores_skipped_dirs(workspace):
    """.cptr holds the chat store itself — watching it would self-trigger."""
    before = workspace_file_digest(str(workspace))
    for name in (".git", ".cptr", "node_modules", "__pycache__"):
        d = workspace / name
        d.mkdir()
        (d / "churn").write_text("noise")

    assert workspace_file_digest(str(workspace)) == before


def test_digest_empty_for_missing_workspace(tmp_path):
    assert workspace_file_digest("") == ""
    assert workspace_file_digest(str(tmp_path / "nope")) == ""


def test_digest_respects_entry_cap(tmp_path, monkeypatch):
    monkeypatch.setattr("cptr.utils.status_monitor.MAX_WALK_ENTRIES", 5)
    for i in range(50):
        (tmp_path / f"f{i}.txt").write_text("x")

    # Bounded walk still returns a usable digest instead of stalling.
    assert workspace_file_digest(str(tmp_path))


# ── Trigger evaluation ───────────────────────────────────────


@pytest.mark.asyncio
async def test_no_trigger_when_fingerprints_match():
    chat = _make_chat(_state(memory_fp="mem1", file_fp="file1"))

    with patch("cptr.utils.status_monitor.MONITOR_STATUS_ENABLED", True), _fake_fingerprints(
        "mem1", "file1"
    ):
        triggers = await evaluate_triggers(chat, "test-model")

    assert not triggers["memory_changed"]
    assert not triggers["file_list_changed"]
    assert not triggers["ctx_step_changed"]
    assert format_status_line(triggers) == ""


@pytest.mark.asyncio
async def test_file_change_emits_status():
    chat = _make_chat(_state(memory_fp="mem1", file_fp="file1"))

    with patch("cptr.utils.status_monitor.MONITOR_STATUS_ENABLED", True), _fake_fingerprints(
        "mem1", "file2"
    ):
        triggers = await evaluate_triggers(chat, "test-model")

    assert triggers["file_list_changed"] is True
    assert not triggers["memory_changed"]
    assert "file list changed" in format_status_line(triggers)


@pytest.mark.asyncio
async def test_memory_change_emits_status():
    chat = _make_chat(_state(memory_fp="mem1", file_fp="file1"))

    with patch("cptr.utils.status_monitor.MONITOR_STATUS_ENABLED", True), _fake_fingerprints(
        "mem2", "file1"
    ):
        triggers = await evaluate_triggers(chat, "test-model")

    assert triggers["memory_changed"] is True
    line = format_status_line(triggers)
    assert "memory changed" in line
    assert "<status>" not in line  # format_status_line returns inner text only


@pytest.mark.asyncio
async def test_triggers_carry_fingerprints_for_state_update():
    """update_state_after_emit records what was compared, not a fresh read."""
    chat = _make_chat(_state(memory_fp="mem1", file_fp="file1"))

    with patch("cptr.utils.status_monitor.MONITOR_STATUS_ENABLED", True), _fake_fingerprints(
        "mem2", "file2"
    ):
        triggers = await evaluate_triggers(chat, "test-model")

    assert triggers["memory_fp"] == "mem2"
    assert triggers["file_fp"] == "file2"


@pytest.mark.asyncio
async def test_monitor_disabled_emits_nothing():
    chat = _make_chat(_state())

    with patch("cptr.utils.status_monitor.MONITOR_STATUS_ENABLED", False), _fake_fingerprints(
        "mem2", "file2"
    ):
        triggers = await evaluate_triggers(chat, "test-model")

    assert not triggers["memory_changed"]
    assert not triggers["file_list_changed"]
    assert not triggers["ctx_step_changed"]
    assert format_status_line(triggers) == ""


@pytest.mark.asyncio
async def test_evaluate_leaves_frozen_snapshot_untouched():
    from cptr.utils.prompt_templates import SYSTEM_PROMPT_SNAPSHOT_KEY

    original = "FROZEN SYSTEM PROMPT v1"
    chat = _make_chat({SYSTEM_PROMPT_SNAPSHOT_KEY: original, **_state()})

    with patch("cptr.utils.status_monitor.MONITOR_STATUS_ENABLED", True), _fake_fingerprints(
        "mem1", "file1"
    ):
        await evaluate_triggers(chat, "test-model")

    assert chat.meta[SYSTEM_PROMPT_SNAPSHOT_KEY] == original


# ── Context step ─────────────────────────────────────────────


def test_ctx_step_crosses_bucket_boundary():
    # level 90000, granularity 0.10 → bucket_size 9000
    assert _compute_ctx_step(50000, 90000, 0.10) == 5
    assert _compute_ctx_step(60000, 90000, 0.10) == 6


def test_ctx_step_inert_when_compaction_disabled():
    assert _compute_ctx_step(50000, 0) == 0
    assert _compute_ctx_step(99999, 0) == 0


# ── Status line formatting ───────────────────────────────────


def test_multiple_crossings_coalesce():
    line = format_status_line(
        {
            "memory_changed": True,
            "file_list_changed": True,
            "ctx_step_changed": True,
            "ctx_info": {"used": "80k", "level": "90k", "pct": 89},
            "timestamp": "2026-07-23 17:00",
        }
    )

    assert "context: 80k/90k (89%)" in line
    assert "file list changed" in line
    assert "memory changed" in line
    assert "2026-07-23 17:00" in line
    assert "\n" not in line


def test_datetime_never_alone():
    line = format_status_line(
        {
            "memory_changed": False,
            "file_list_changed": False,
            "ctx_step_changed": False,
            "ctx_info": None,
            "timestamp": "2026-07-23 16:15",
        }
    )

    assert line == ""


def test_context_omitted_without_ctx_info():
    """Compaction off → ctx_info is None, so context is never reported."""
    line = format_status_line(
        {
            "memory_changed": True,
            "file_list_changed": False,
            "ctx_step_changed": True,
            "ctx_info": None,
            "timestamp": "2026-07-23 16:20",
        }
    )

    assert "context" not in line
    assert "memory changed" in line
