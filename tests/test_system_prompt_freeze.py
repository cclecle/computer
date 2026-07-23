"""Tests for the frozen per-conversation system prompt (KV prefix-cache fix).

The whole point of the freeze is byte-stability: turn N>=2 of a conversation
must send a system prompt that is byte-identical to turn 1 so llama.cpp (and any
prefix KV cache) can reuse the leading tokens instead of reprocessing the entire
prompt + history every turn.
"""

from __future__ import annotations

import re

import pytest

from cptr.utils.memory import build_frozen_memory_prompt, workspace_memory_path
from cptr.utils.prompt_templates import (
    SYSTEM_PROMPT_SNAPSHOT_KEY,
    load_system_prompt,
    resolve_system_prompt,
)

USER = "freeze-test-user"


class _FakeChat:
    def __init__(self, chat_id: str, meta: dict):
        self.id = chat_id
        self.meta = meta


def _patch_config(monkeypatch):
    """Make every Config.get return None so defaults apply (memory+skills on)."""
    from cptr.models import Config

    async def fake_get(key):  # noqa: ARG001 - signature match
        return None

    monkeypatch.setattr(Config, "get", staticmethod(fake_get))


def _patch_isolated_data_dir(monkeypatch, tmp_path):
    """Point user-memory root at an empty temp dir so the host's memory can't leak."""
    monkeypatch.setattr("cptr.utils.memory.DATA_DIR", tmp_path / "data")


def _patch_chat_store(monkeypatch) -> dict[str, _FakeChat]:
    store: dict[str, _FakeChat] = {}
    from cptr.models import Chat

    async def get_by_id(chat_id):
        return store.get(chat_id)

    async def update_meta(chat_id, meta, updated_at=0):  # noqa: ARG001
        chat = store.get(chat_id)
        if chat is None:
            return False
        chat.meta = meta
        return True

    monkeypatch.setattr(Chat, "get_by_id", staticmethod(get_by_id))
    monkeypatch.setattr(Chat, "update_meta", staticmethod(update_meta))
    return store


def _make_workspace(tmp_path) -> str:
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "README.md").write_text("hello\n", encoding="utf-8")
    (ws / "src").mkdir()
    (ws / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")

    mem_path = workspace_memory_path(USER, str(ws))
    mem_path.parent.mkdir(parents=True, exist_ok=True)
    mem_path.write_text("- SENTINEL_MEMORY workspace uses ruff for linting\n", encoding="utf-8")
    return str(ws)


def _mutate_workspace(ws: str) -> None:
    """Change both the memory and the file tree after the conversation froze."""
    from pathlib import Path

    workspace = Path(ws)
    (workspace / "sentinel_new_file.py").write_text("# new\n", encoding="utf-8")
    mem_path = workspace_memory_path(USER, ws)
    mem_path.write_text(
        "- SENTINEL_MEMORY workspace uses ruff for linting\n"
        "- SENTINEL_NEW_MEMORY added mid-conversation\n",
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_frozen_memory_dump_is_deterministic(tmp_path, monkeypatch):
    _patch_config(monkeypatch)
    _patch_isolated_data_dir(monkeypatch, tmp_path)
    ws = _make_workspace(tmp_path)

    first = await build_frozen_memory_prompt(USER, ws)
    second = await build_frozen_memory_prompt(USER, ws)

    assert first == second
    assert "SENTINEL_MEMORY" in first
    assert "[Workspace Memory]" in first
    # The live "[used/budget]" counter must be gone — it changes per turn.
    assert re.search(r"\[Workspace Memory\] \[\d+/\d+\]", first) is None


@pytest.mark.asyncio
async def test_load_system_prompt_freeze_is_deterministic(tmp_path, monkeypatch):
    _patch_config(monkeypatch)
    _patch_isolated_data_dir(monkeypatch, tmp_path)
    ws = _make_workspace(tmp_path)

    a = await load_system_prompt(ws, "test-model", user_id=USER, freeze=True)
    b = await load_system_prompt(ws, "test-model", user_id=USER, freeze=True)

    assert a == b
    assert "SENTINEL_MEMORY" in a


@pytest.mark.asyncio
async def test_resolve_system_prompt_is_byte_identical_across_turns(tmp_path, monkeypatch):
    _patch_config(monkeypatch)
    _patch_isolated_data_dir(monkeypatch, tmp_path)
    store = _patch_chat_store(monkeypatch)
    ws = _make_workspace(tmp_path)

    chat_id = "chat-1"
    store[chat_id] = _FakeChat(chat_id, {})

    # Turn 1: renders and freezes onto the chat.
    turn1 = await resolve_system_prompt(chat_id, ws, "m", user_id=USER)
    assert SYSTEM_PROMPT_SNAPSHOT_KEY in store[chat_id].meta
    assert store[chat_id].meta[SYSTEM_PROMPT_SNAPSHOT_KEY] == turn1

    # Memory + files change mid-conversation...
    _mutate_workspace(ws)

    # Turn 2+: byte-identical, because the frozen snapshot is reused verbatim.
    turn2 = await resolve_system_prompt(chat_id, ws, "m", user_id=USER)
    turn3 = await resolve_system_prompt(chat_id, ws, "m", user_id=USER)
    assert turn2 == turn1
    assert turn3 == turn1
    assert "SENTINEL_NEW_MEMORY" not in turn1  # mid-conversation change NOT reflected


@pytest.mark.asyncio
async def test_new_conversation_gets_fresh_snapshot(tmp_path, monkeypatch):
    _patch_config(monkeypatch)
    _patch_isolated_data_dir(monkeypatch, tmp_path)
    store = _patch_chat_store(monkeypatch)
    ws = _make_workspace(tmp_path)

    first_chat = "chat-1"
    store[first_chat] = _FakeChat(first_chat, {})
    turn1 = await resolve_system_prompt(first_chat, ws, "m", user_id=USER)

    _mutate_workspace(ws)

    # A brand new conversation re-renders and picks up the current state.
    second_chat = "chat-2"
    store[second_chat] = _FakeChat(second_chat, {})
    fresh = await resolve_system_prompt(second_chat, ws, "m", user_id=USER)

    assert fresh != turn1
    assert "SENTINEL_NEW_MEMORY" in fresh
    assert "SENTINEL_NEW_MEMORY" not in turn1


@pytest.mark.asyncio
async def test_resolve_persist_false_does_not_write_snapshot(tmp_path, monkeypatch):
    _patch_config(monkeypatch)
    _patch_isolated_data_dir(monkeypatch, tmp_path)
    store = _patch_chat_store(monkeypatch)
    ws = _make_workspace(tmp_path)

    chat_id = "chat-1"
    store[chat_id] = _FakeChat(chat_id, {})

    estimate = await resolve_system_prompt(chat_id, ws, "m", user_id=USER, persist=False)

    # Read-only estimate must not freeze anything onto the chat.
    assert SYSTEM_PROMPT_SNAPSHOT_KEY not in store[chat_id].meta
    assert "SENTINEL_MEMORY" in estimate
