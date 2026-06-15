"""Chat task runner: agentic loop with tool calling.

Runs as an asyncio.Task. Streams deltas via Socket.IO, persists to DB.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path

from cptr.env import CHAT_MAX_ITERATIONS, CHAT_TOOL_MAX_CHARS
from cptr.utils.context import should_compact
from cptr.utils.skills import discover_skills, load_skill, build_catalog_xml, format_skill_content
from cptr.utils.summarize import summarize_messages
from cptr.models import Chat, ChatMessage, Config
from cptr.socket.main import emit_to_user
from cptr.utils.ai import (
    ChatCompletionForm,
    chat_completion,
    stream_anthropic,
    stream_openai_completions,
    stream_openai_responses,
)
from cptr.utils.config import _get_jwt_secret, now_ms
from cptr.utils.crypto import decrypt_key
from cptr.utils.tools import ALL_TOOLS, execute_tool, get_tool_list, _fn_to_schema, create_artifact
from cptr.utils.chat_export import export_chat_to_file
from cptr.utils.json_parser import extract_json

logger = logging.getLogger(__name__)

PLAN_MODE_PROMPT = (
    "[Plan Mode] Research the codebase with read-only tools, then present your plan "
    "using create_artifact. Wait for approval before coding."
)

# ── Task registry ───────────────────────────────────────────

_tasks: dict[str, asyncio.Task] = {}  # message_id → asyncio.Task
_task_state: dict[str, dict] = {}  # message_id → {content, output}
_task_chat: dict[str, str] = {}  # message_id → chat_id
_queue_locks: dict[str, asyncio.Lock] = {}  # chat_id → Lock


def start_task(
    message_id: str,
    chat_id: str,
    user_id: str,
    connection: dict,
    workspace: str,
    model: str,
    regeneration_prompt: str | None = None,
    output_queue: asyncio.Queue | None = None,
):
    """Launch the agentic loop as a background asyncio.Task."""
    task = asyncio.create_task(
        run_chat_task(
            message_id,
            chat_id,
            user_id,
            connection,
            workspace,
            model,
            regeneration_prompt,
            output_queue,
        )
    )
    _tasks[message_id] = task
    _task_chat[message_id] = chat_id


async def cancel_task(message_id: str) -> bool:
    """Cancel a running task. Returns True if found."""
    task = _tasks.get(message_id)
    if task:
        task.cancel()
        return True
    return False


def is_running(message_id: str) -> bool:
    """Check if a task is currently running."""
    task = _tasks.get(message_id)
    return task is not None and not task.done()


def get_live_state(message_id: str) -> dict | None:
    """Get live in-memory state for a running task."""
    return _task_state.get(message_id)


def get_active_chat_ids() -> set[str]:
    """Return the set of chat_ids that currently have a running task."""
    return {cid for mid, cid in _task_chat.items() if mid in _tasks and not _tasks[mid].done()}


# ── Queue processing ────────────────────────────────────────


async def _process_queue(chat_id: str, user_id: str, workspace: str):
    """Check for queued user messages and start the next task.

    Uses a per-chat lock to prevent concurrent processing from
    both the task's finally block and the API double-check.
    """
    lock = _queue_locks.setdefault(chat_id, asyncio.Lock())
    async with lock:
        all_msgs = await ChatMessage.get_all_by_chat(chat_id)

        # Don't process queue if there's still an active generation
        if any(m.role == "assistant" and not m.done for m in all_msgs):
            return

        # Find queued messages (ordered by created_at)
        queued = [m for m in all_msgs if m.role == "user" and m.meta and m.meta.get("queued")]
        if not queued:
            return

        # Combine all queued prompts into one user message
        combined_content = "\n\n".join(m.content for m in queued if m.content)

        # Find the current leaf (latest done assistant message)
        done_assistants = [m for m in all_msgs if m.role == "assistant" and m.done]
        parent_id = done_assistants[-1].id if done_assistants else queued[0].parent_id

        # Delete individual queued messages, create one combined message
        for m in queued:
            await ChatMessage.delete(m.id)

        combined_msg = await ChatMessage.create(
            chat_id=chat_id,
            role="user",
            content=combined_content,
            parent_id=parent_id,
            created_at=now_ms(),
        )

        # Resolve model from the chat's last used model
        chat = await Chat.get_by_id(chat_id)
        if not chat:
            return
        model_id = (chat.meta or {}).get("last_model", "")
        if not model_id:
            # Fall back to the model from the last assistant message
            last_asst = done_assistants[-1] if done_assistants else None
            model_id = (last_asst.model if last_asst else "") or ""
        if not model_id:
            logger.error("[queue] No model found for chat %s, cannot process queue", chat_id)
            return

        # Resolve connection
        try:
            from cptr.routers.chat import _resolve_connection

            connection, bare_model = await _resolve_connection(model_id)
        except Exception:
            logger.exception("[queue] Failed to resolve connection for model %s", model_id)
            return

        # Create assistant placeholder
        assistant_msg = await ChatMessage.create(
            chat_id=chat_id,
            role="assistant",
            content="",
            parent_id=combined_msg.id,
            model=model_id,
            done=False,
            created_at=now_ms(),
        )
        await Chat.update_current_message(chat_id, assistant_msg.id, now_ms())

        # Notify frontend that queue was processed (new messages appeared)
        await emit_to_user(
            user_id,
            {"chat_id": chat_id, "message_id": assistant_msg.id, "queue_processed": True},
        )

        # Start new task
        start_task(
            message_id=assistant_msg.id,
            chat_id=chat_id,
            user_id=user_id,
            connection=connection,
            workspace=workspace,
            model=bare_model,
        )
        logger.info(
            "[queue] Processed %d queued message(s) for chat %s",
            len(queued),
            chat_id[:8],
        )


async def reconcile_chat_state():
    """Recover from server crash: fix stuck messages, process orphaned queues.

    Called once on startup when ENABLE_CHAT_RECONCILE_ON_STARTUP=true (default).
    Finds:
      1. Assistant messages with done=False that have no running task → mark done
      2. Chats with queued user messages → process them
    """
    from sqlalchemy import select, and_
    from cptr.utils.db import get_db

    async with await get_db() as db:
        result = await db.execute(
            select(ChatMessage).where(
                and_(
                    ChatMessage.role == "assistant",
                    ChatMessage.done == False,  # noqa: E712
                )
            )
        )
        stuck = list(result.scalars().all())

    healed_chats: set[str] = set()
    for msg in stuck:
        if not is_running(msg.id):
            logger.warning("[reconcile] Marking stuck message %s as done", msg.id)
            meta = dict(msg.meta or {})
            meta["error"] = "interrupted by server restart"
            await ChatMessage.update(msg.id, done=True, meta=meta)
            healed_chats.add(msg.chat_id)

    # Process orphaned queues for healed chats
    for cid in healed_chats:
        chat = await Chat.get_by_id(cid)
        if chat:
            workspace = (chat.meta or {}).get("workspace", "")
            try:
                await _process_queue(cid, chat.user_id, workspace)
            except Exception:
                logger.exception("[reconcile] Failed to process queue for chat %s", cid)

    if healed_chats:
        logger.info("[reconcile] Recovered %d chat(s) on startup", len(healed_chats))


# ── System prompt ───────────────────────────────────────────


def _get_file_tree(workspace: str, max_entries: int = 200) -> str:
    """Generate a compact file tree listing for the workspace."""
    ws = Path(workspace)
    if not ws.is_dir():
        return ""
    ignore = {
        ".git",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        ".next",
        "build",
        "dist",
        ".cptr",
        ".svelte-kit",
        ".DS_Store",
    }
    entries = []
    for item in sorted(ws.iterdir()):
        if item.name in ignore:
            continue
        suffix = "/" if item.is_dir() else ""
        entries.append(f"  {item.name}{suffix}")
        if item.is_dir():
            try:
                for child in sorted(item.iterdir()):
                    if child.name in ignore:
                        continue
                    csuffix = "/" if child.is_dir() else ""
                    entries.append(f"    {child.name}{csuffix}")
                    if len(entries) >= max_entries:
                        entries.append("    ...")
                        break
            except PermissionError:
                pass
        if len(entries) >= max_entries:
            break
    return "\n".join(entries)


INSTRUCTION_FILENAMES = ["MEMORY.md", "AGENTS.md", "AGENT.md", "CLAUDE.md"]


def _load_instruction_files(workspace: str, max_bytes: int = 32_000) -> str:
    """Load well-known AI instruction files from workspace root.

    Scans for MEMORY.md, AGENTS.md, AGENT.md, CLAUDE.md.
    All found files are concatenated (not first-found-wins).
    """
    ws = Path(workspace)
    if not ws.is_dir():
        return ""
    parts: list[str] = []
    total = 0
    for name in INSTRUCTION_FILENAMES:
        path = ws / name
        if path.is_file():
            remaining = max_bytes - total
            if remaining <= 0:
                break
            try:
                content = path.read_text(errors="replace")[:remaining].strip()
            except OSError:
                continue
            if content:
                parts.append(f"# {name}\n{content}")
                total += len(content)
                logger.debug("[instructions] Loaded %s (%d bytes)", name, len(content))
    return "\n\n".join(parts)


# ── Template engine ─────────────────────────────────────────

import platform
import re
from datetime import date

_TEMPLATE_RE = re.compile(r"\{\{(\w+)\}\}")

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful coding assistant. "
    "You have access to tools to read, search, and modify files in the workspace. "
    "Use them to help the user with their coding tasks.\n\n"
    "For complex tasks, create an implementation plan first using "
    "create_artifact, then wait for approval before coding."
    "\n\n{{INSTRUCTIONS}}"
    "\n\n{{SKILLS}}"
    "\n\nWorkspace: {{WORKSPACE_NAME}}"
    "\nFiles:\n{{FILE_TREE}}"
)


def _render_template(template: str, variables: dict[str, str]) -> str:
    """Render {{VARIABLE}} placeholders in a template string.

    - Known variables are substituted with their values.
    - Unrecognized {{...}} tokens are left as-is.
    - Cleans up excess blank lines left by empty variable substitutions.
    """

    def _replace(match: re.Match) -> str:
        key = match.group(1)
        if key in variables:
            return variables[key]
        return match.group(0)  # leave unrecognized tokens as-is

    result = _TEMPLATE_RE.sub(_replace, template)
    # Clean up triple+ blank lines left by empty substitutions
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def _build_template_variables(workspace: str, model: str = "") -> dict[str, str]:
    """Build the dict of template variable values for the current context."""
    ws_path = Path(workspace)

    # Build instructions content
    instructions = _load_instruction_files(workspace)
    if instructions:
        instructions_block = (
            f"<instructions>\n{instructions}\n</instructions>"
            "\n\nThe above <instructions> were loaded from instruction files in the workspace root. "
            "These files persist across sessions. "
            "You can update them with your file tools to save learnings, decisions, or "
            "project conventions for future sessions."
        )
    else:
        instructions_block = ""

    # Build skills catalog
    skills = discover_skills(workspace)
    skills_block = build_catalog_xml(skills)

    return {
        "WORKSPACE_NAME": ws_path.name if ws_path.is_dir() else "",
        "WORKSPACE_PATH": str(ws_path),
        "FILE_TREE": _get_file_tree(workspace),
        "INSTRUCTIONS": instructions_block,
        "SKILLS": skills_block,
        "OS": platform.system().replace("Darwin", "macOS"),
        "DATE": date.today().isoformat(),
        "MODEL": model,
    }


async def _load_system_prompt(workspace: str, model: str = "") -> str:
    """Load system prompt with template variable rendering.

    Resolution order (most specific wins):
      1. .cptr/system.md in the workspace (file override)
      2. Per-model system_prompt from chat.models config
      3. Global (*) system_prompt from chat.models config
      4. DEFAULT_SYSTEM_PROMPT constant (hardcoded fallback)

    All sources support {{VARIABLE}} template substitution.
    """
    template = None

    # 1. Workspace file override (.cptr/system.md)
    ws_prompt = Path(workspace) / ".cptr" / "system.md"
    if ws_prompt.is_file():
        template = ws_prompt.read_text(errors="replace").strip()

    # 2 & 3. Config-based prompts (per-model → global)
    if template is None:
        try:
            chat_models_config = await Config.get("chat.models") or {}
            # Per-model prompt
            if model:
                model_prompt = (
                    chat_models_config.get(model, {}).get("params", {}).get("system_prompt")
                )
                if model_prompt:
                    template = model_prompt
            # Global prompt
            if template is None:
                global_prompt = (
                    chat_models_config.get("*", {}).get("params", {}).get("system_prompt")
                )
                if global_prompt:
                    template = global_prompt
        except Exception:
            logger.debug("[system_prompt] Failed to load from config", exc_info=True)

    # 4. Hardcoded fallback
    if template is None:
        template = DEFAULT_SYSTEM_PROMPT

    # Render template variables
    variables = _build_template_variables(workspace, model)
    return _render_template(template, variables)


# ── Title generation ────────────────────────────────────────


TITLE_PROMPT = (
    "Generate a concise title (max 8 words) for this conversation based on the user's message. "
    'Respond with ONLY a JSON object: {"title": "Your Title Here"}. '
    "Do not include quotes around the JSON. Do not explain."
)


async def generate_chat_title(
    chat_id: str,
    user_id: str,
    connection: dict,
    model: str,
    user_message: str,
):
    """Generate a proper title for a new chat via a lightweight LLM call.

    Uses the shared chat_completion() helper from ai.py.
    On success, updates the DB and emits a socket event so the frontend
    updates the tab label in real time.
    """
    provider = connection["provider"]
    api_key = decrypt_key(connection.get("api_key", ""), _get_jwt_secret())
    base_url = connection.get("base_url") or _default_base_url(provider)
    api_type = connection.get("api_type", "chat_completions")

    # Truncate very long messages to keep the prompt small
    truncated = user_message[:200].strip()
    if len(user_message) > 200:
        truncated += "..."

    try:
        text = await chat_completion(
            provider=provider,
            base_url=base_url,
            api_key=api_key,
            model=model,
            messages=[{"role": "user", "content": truncated}],
            system=TITLE_PROMPT,
            max_tokens=50,
            api_type=api_type,
        )

        # Parse the JSON title
        parsed = extract_json(text)
        title = (parsed.get("title", "") if isinstance(parsed, dict) else "").strip()
        if not title:
            return

        # Persist and notify
        await Chat.update_title(chat_id, title, now_ms())
        await emit_to_user(user_id, {"chat_id": chat_id, "title": title})
        logger.info("[title] Generated title for chat %s: %s", chat_id[:8], title)

    except Exception:
        logger.debug("[title] Failed to generate title for chat %s", chat_id[:8], exc_info=True)


# ── Message history ─────────────────────────────────────────


async def _load_message_history(chat_id: str, message_id: str) -> tuple[list[dict], str | None]:
    """Load the ancestor chain from message_id to root as LLM messages.

    Walks up via parent_id so only the active branch is included.
    The current message (message_id) is always included even if done=False,
    since it may contain completed tool calls from prior approval rounds.

    If any message in the chain has a chat_summary, everything before it
    is skipped and the summary is returned separately for the system prompt.

    Returns (messages, chat_summary_or_None).
    """
    all_msgs = await ChatMessage.get_all_by_chat(chat_id)
    msg_map = {m.id: m for m in all_msgs}

    # Trace from message_id up to root
    chain: list = []
    cur = msg_map.get(message_id)
    while cur:
        chain.append(cur)
        cur = msg_map.get(cur.parent_id) if cur.parent_id else None
    chain.reverse()  # root → leaf

    # Find the most recent message with a chat_summary
    existing_summary = None
    for i, m in enumerate(chain):
        if m.chat_summary:
            chain = chain[i:]  # keep this message and everything after
            existing_summary = m.chat_summary
            break

    result = []
    for m in chain:
        # Skip in-progress assistant placeholders, but NOT the current
        # message being continued, which may have accumulated tool call
        # results from prior approval rounds that the LLM needs to see.
        if m.role == "assistant" and not m.done and m.id != message_id:
            continue
        # For the current message, skip if it has no content and no output
        # (truly empty placeholder on first run)
        if m.id == message_id and not m.done and not m.content and not m.output:
            continue
        entry: dict = {"role": m.role, "content": m.content or ""}

        # Transform uploaded images into base64 multimodal blocks; inline text files
        if m.role == "user":
            attached_files = (m.meta or {}).get("files", [])
            images = [
                f
                for f in attached_files
                if isinstance(f, dict)
                and (f.get("type") == "image" or (f.get("content_type") or "").startswith("image/"))
            ]
            non_images = [f for f in attached_files if isinstance(f, dict) and f not in images]

            if images or non_images:
                from cptr.utils.storage import get_storage
                import base64

                text_content = entry["content"]

                # Append file:// references so the AI can read them with read_file
                if non_images:
                    from cptr.utils.storage import UPLOADS_DIR

                    file_refs = []
                    for f in non_images:
                        file_id = f.get("id")
                        if not file_id:
                            continue
                        name = f.get("name", "file")
                        file_path = UPLOADS_DIR / file_id
                        file_refs.append(f"[{name}](file://{file_path})")
                    if file_refs:
                        text_content += "\n\nAttached files:\n" + "\n".join(file_refs)

                content_blocks = [{"type": "text", "text": text_content}] if text_content else []

                for img in images:
                    file_id = img.get("id")
                    if not file_id:
                        continue
                    data = await get_storage().get(file_id)
                    if data:
                        b64_str = base64.b64encode(data).decode("utf-8")
                        ctype = img.get("content_type") or "image/png"
                        content_blocks.append(
                            {"type": "image", "media_type": ctype, "base64": b64_str}
                        )

                if len(content_blocks) > (1 if text_content else 0):
                    entry["content"] = content_blocks
                elif text_content != entry["content"]:
                    entry["content"] = text_content

        # Reconstruct tool calls from output items for the provider.
        #
        # Output items accumulate across agentic-loop iterations within a
        # single assistant message.  The Responses API (reasoning models)
        # requires that each function_call is paired with the reasoning
        # items from the *same* API response.  To reconstruct the correct
        # interleaved history we group output items into "turns":
        #
        #   Turn = [reasoning…, function_call…, function_call_output…]
        #
        # Each turn produces one assistant message (with tool_calls +
        # reasoning_items) followed by the corresponding tool-result
        # messages.
        if m.output:
            # ── Collect the set of call_ids that have outputs ──
            # This is needed to filter out orphaned function_calls
            # (e.g. from crashes, partial persistence, or data corruption).
            output_call_ids = {
                item["call_id"]
                for item in m.output
                if item.get("type") == "function_call_output"
            }

            # ── Group output items into per-iteration turns ──
            turns: list[dict] = []  # each: {reasoning: [], calls: [], outputs: []}
            current_turn: dict = {"reasoning": [], "calls": [], "outputs": []}

            for item in m.output:
                itype = item.get("type")
                if itype == "reasoning":
                    # A reasoning item after we already have outputs means
                    # a new API iteration started — flush the current turn.
                    if current_turn["outputs"]:
                        turns.append(current_turn)
                        current_turn = {"reasoning": [], "calls": [], "outputs": []}
                    current_turn["reasoning"].append(item)
                elif itype == "function_call" and item.get("status") == "completed":
                    # Only include calls that have a matching output
                    if item["call_id"] not in output_call_ids:
                        logger.warning(
                            "[history] Skipping orphaned function_call %s (%s) — no matching output",
                            item.get("call_id", "?"),
                            item.get("name", "?"),
                        )
                        continue
                    # A new function_call after outputs means
                    # a new iteration (model saw results and called again).
                    if current_turn["outputs"]:
                        turns.append(current_turn)
                        current_turn = {"reasoning": [], "calls": [], "outputs": []}
                    tc = {
                        "id": item["call_id"],
                        "type": "function",
                        "function": {
                            "name": item["name"],
                            "arguments": json.dumps(item.get("arguments", {})),
                        },
                    }
                    # Preserve Responses API fc_ ID for round-tripping
                    if item.get("fc_id"):
                        tc["fc_id"] = item["fc_id"]
                    current_turn["calls"].append(tc)
                elif itype == "function_call_output":
                    current_turn["outputs"].append(item)
                # Skip other types (message, artifact, pending calls, etc.)

            # Don't forget the last turn
            if current_turn["calls"] or current_turn["outputs"]:
                turns.append(current_turn)

            if not turns:
                # No tool calls — keep entry as-is (plain text assistant)
                pass
            else:
                for ti, turn in enumerate(turns):
                    # Filter calls to only those with matching outputs
                    turn_output_ids = {o["call_id"] for o in turn["outputs"]}
                    matched_calls = [
                        tc for tc in turn["calls"]
                        if tc["id"] in turn_output_ids
                    ]
                    if matched_calls:
                        if ti == 0:
                            # First turn: attach to the existing entry
                            entry["tool_calls"] = matched_calls
                            if turn["reasoning"]:
                                entry["reasoning_items"] = turn["reasoning"]
                        else:
                            # Subsequent turns: create a new assistant entry
                            entry = {
                                "role": "assistant",
                                "content": "",
                                "tool_calls": matched_calls,
                            }
                            if turn["reasoning"]:
                                entry["reasoning_items"] = turn["reasoning"]
                    for out in turn["outputs"]:
                        result.append(entry)
                        entry = {
                            "role": "tool",
                            "tool_call_id": out["call_id"],
                            "content": out.get("output", ""),
                        }

        result.append(entry)

    # ── Final sanitization: ensure every tool_call has a matching tool result ──
    # This catches edge cases from compaction, DB corruption, or partial persistence.
    result = _sanitize_tool_pairs(result)

    return result, existing_summary


def _sanitize_tool_pairs(messages: list[dict]) -> list[dict]:
    """Ensure every tool_call in an assistant message has a matching tool result.

    Walks the message list and collects all tool result call_ids.  Then
    strips any tool_call entries from assistant messages that have no
    matching result.  Also removes orphaned tool-result messages.

    This is the last line of defence against 400 errors from providers
    that require strict tool_call ↔ tool_result pairing (OpenAI).
    """
    # Collect all tool-result call_ids in the conversation
    tool_result_ids = {
        m["tool_call_id"]
        for m in messages
        if m.get("role") == "tool" and m.get("tool_call_id")
    }

    # Collect all tool_call ids declared by assistant messages
    tool_call_ids = set()
    for m in messages:
        if m.get("role") == "assistant" and m.get("tool_calls"):
            for tc in m["tool_calls"]:
                tool_call_ids.add(tc.get("id", ""))

    sanitized = []
    for m in messages:
        if m.get("role") == "assistant" and m.get("tool_calls"):
            # Keep only tool_calls that have a matching tool result
            kept = [tc for tc in m["tool_calls"] if tc.get("id") in tool_result_ids]
            dropped = len(m["tool_calls"]) - len(kept)
            if dropped:
                logger.warning(
                    "[sanitize] Dropped %d orphaned tool_call(s) from assistant message",
                    dropped,
                )
            if kept:
                m = dict(m)
                m["tool_calls"] = kept
                sanitized.append(m)
            else:
                # No tool_calls left — keep as plain text if there's content
                m = dict(m)
                del m["tool_calls"]
                m.pop("reasoning_items", None)
                if m.get("content"):
                    sanitized.append(m)
                # else: drop empty assistant message entirely
        elif m.get("role") == "tool":
            # Drop tool results that have no matching tool_call
            if m.get("tool_call_id") not in tool_call_ids:
                logger.warning(
                    "[sanitize] Dropped orphaned tool result for call_id=%s",
                    m.get("tool_call_id", "?"),
                )
                continue
            sanitized.append(m)
        else:
            sanitized.append(m)

    return sanitized


def _parse_image_data_uri(result: str) -> tuple[str, str] | None:
    """Check if a tool result is a data URI image (from read_file on image files).

    Returns (media_type, base64_data) if it's a data URI image, else None.
    """
    if not result.startswith("data:image/"):
        return None
    # data:image/png;base64,iVBOR...
    try:
        header, b64_data = result.split(",", 1)
        media_type = header.split(";")[0].replace("data:", "")
        return media_type, b64_data
    except (ValueError, IndexError):
        return None


def _append_tool_to_messages(
    messages: list[dict], event: dict, result: str, provider: str,
    reasoning_items: list[dict] | None = None,
):
    """Append a tool call + result to the message history for the next API call."""
    # Check for image result before truncation (data URI is large but needed)
    image = _parse_image_data_uri(result)

    if not image:
        # Guard against oversized tool outputs (skip for images, handled above)
        if len(result) > CHAT_TOOL_MAX_CHARS:
            half = CHAT_TOOL_MAX_CHARS // 2
            result = result[:half] + "\n\n...(truncated)...\n\n" + result[-half:]

    # Add assistant message with tool_call
    assistant_msg = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": event["call_id"],
                "fc_id": event.get("id", ""),
                "type": "function",
                "function": {
                    "name": event["name"],
                    "arguments": json.dumps(event["arguments"]),
                },
            }
        ],
    }
    # Attach reasoning items for round-tripping (Responses API reasoning models)
    if reasoning_items:
        assistant_msg["reasoning_items"] = reasoning_items
    messages.append(assistant_msg)

    if image:
        # Structured multimodal content — provider converters handle the
        # "image" block type appropriately for each API.
        media_type, b64_data = image
        path = event["arguments"].get("path", "image")
        messages.append(
            {
                "role": "tool",
                "tool_call_id": event["call_id"],
                "content": [
                    {"type": "text", "text": f"Image file: {path}"},
                    {
                        "type": "image",
                        "media_type": media_type,
                        "base64": b64_data,
                    },
                ],
            }
        )
    else:
        # Plain text tool result
        messages.append(
            {
                "role": "tool",
                "tool_call_id": event["call_id"],
                "content": result,
            }
        )


def _append_batch_to_messages(
    messages: list[dict],
    call_results: list[tuple[dict, str]],
    provider: str,
    reasoning_items: list[dict] | None = None,
):
    """Append multiple tool calls + results as a single assistant message.

    Unlike _append_tool_to_messages (which creates one assistant message per
    call), this batches all calls into one assistant message.  This is
    required for the Responses API with reasoning models, where all
    function_calls from one API response share the same reasoning items.
    """
    if not call_results:
        return

    tool_calls = []
    for event, _ in call_results:
        tool_calls.append(
            {
                "id": event["call_id"],
                "fc_id": event.get("id", ""),
                "type": "function",
                "function": {
                    "name": event["name"],
                    "arguments": json.dumps(event["arguments"]),
                },
            }
        )

    assistant_msg: dict = {
        "role": "assistant",
        "content": "",
        "tool_calls": tool_calls,
    }
    if reasoning_items:
        assistant_msg["reasoning_items"] = reasoning_items
    messages.append(assistant_msg)

    for event, result in call_results:
        # Guard against oversized tool outputs
        image = _parse_image_data_uri(result)
        if not image:
            if len(result) > CHAT_TOOL_MAX_CHARS:
                half = CHAT_TOOL_MAX_CHARS // 2
                result = result[:half] + "\n\n...(truncated)...\n\n" + result[-half:]

        if image:
            media_type, b64_data = image
            path = event["arguments"].get("path", "image")
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": event["call_id"],
                    "content": [
                        {"type": "text", "text": f"Image file: {path}"},
                        {
                            "type": "image",
                            "media_type": media_type,
                            "base64": b64_data,
                        },
                    ],
                }
            )
        else:
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": event["call_id"],
                    "content": result,
                }
            )


def _scrub_incomplete_items(output_items: list[dict]) -> None:
    """Mark any in-progress function_call items as 'failed'.

    Called before persisting output_items after an error or cancellation.
    Without this, "in_progress" items stay in the DB.  While
    _load_message_history skips non-"completed" items today, marking
    them explicitly prevents any future code from misinterpreting them.
    """
    for item in output_items:
        if item.get("type") == "function_call" and item.get("status") in (
            "in_progress",
            "pending",
        ):
            item["status"] = "failed"


def _find_safe_split(messages: list[dict], target_keep: int) -> int:
    """Find a safe split index that doesn't break tool call pairs.

    Returns the index where keep_zone starts. Ensures:
    - Never splits between an assistant tool_call and its tool result
    - keep_zone doesn't start with a tool result message
    - At least 2 messages are kept
    """
    n = len(messages)
    split = max(2, n - target_keep)

    # Walk forward from the initial split to find a safe boundary
    while split < n - 1:
        msg = messages[split]
        # Don't start keep_zone with a tool result — it needs its preceding assistant
        if msg.get("role") == "tool":
            split += 1
            continue
        break

    return min(split, n - 2)  # always keep at least 2


# ── Connection resolution ───────────────────────────────────


def build_artifact_item(tool_name: str, arguments: dict, result: str) -> dict | None:
    """Build an artifact output item if the tool call produced an artifact.

    Works for both create_artifact and create_file with artifact_type.
    Returns None if no artifact card should be shown.
    """
    artifact_type = arguments.get("artifact_type", "")
    if tool_name == "create_artifact":
        artifact_type = artifact_type or "implementation_plan"
    if not artifact_type:
        return None

    try:
        meta = json.loads(result)
    except (json.JSONDecodeError, TypeError):
        meta = {}

    return {
        "type": "artifact",
        "artifact_type": artifact_type,
        "title": meta.get("title")
        or arguments.get("title")
        or artifact_type.replace("_", " ").title(),
        "content": arguments.get("content", ""),
        "path": meta.get("path") or arguments.get("path", ""),
    }


def _default_base_url(provider: str) -> str:
    return {
        "anthropic": "https://api.anthropic.com/v1",
        "openai": "https://api.openai.com/v1",
    }.get(provider, "https://api.openai.com/v1")


# ── The agentic loop ────────────────────────────────────────


async def run_chat_task(
    message_id: str,
    chat_id: str,
    user_id: str,
    connection: dict,
    workspace: str,
    model: str,
    regeneration_prompt: str | None = None,
    output_queue: asyncio.Queue | None = None,
):
    """Plain async function. Makes raw API calls in a loop."""

    async def emit(**data):
        """Stream an output delta to the user."""
        try:
            await emit_to_user(user_id, {"chat_id": chat_id, "message_id": message_id, **data})
        except Exception:
            # Socket failure must not prevent the queue push below,
            # otherwise the gateway SSE stream hangs forever.
            logger.debug("[task %s] emit_to_user failed", message_id[:8], exc_info=True)
        # Push to gateway queue if present
        if output_queue is not None:
            if "delta" in data:
                await output_queue.put({"type": "delta", "content": data["delta"]})
            elif "output" in data:
                await output_queue.put({"type": "output", "item": data["output"]})
            elif data.get("done"):
                if "error" in data:
                    await output_queue.put({"type": "error", "message": data["error"]})
                else:
                    await output_queue.put({"type": "done", "finish_reason": "stop"})

    async def _emit_done():
        """Emit done=True enriched with chat title and content preview."""
        try:
            chat_obj = await Chat.get_by_id(chat_id)
            title = chat_obj.title if chat_obj else "Chat"
        except Exception:
            title = "Chat"
        preview = content[:300] if content else ""
        ws_name = workspace.rstrip("/").rsplit("/", 1)[-1] if workspace else ""
        await emit(done=True, title=title, content=preview, workspace=ws_name)

    # Load existing state so continuations don't overwrite previous output
    msg = await ChatMessage.get_by_id(message_id)
    content = (msg.content or "") if msg else ""
    output_items: list[dict] = list(msg.output or []) if msg else []
    text_buffer = ""  # Accumulates text between tool calls

    logger.info(
        "[task %s] start: existing content=%d chars, output=%d items",
        message_id[:8],
        len(content),
        len(output_items),
    )

    def _flush_text() -> dict | None:
        """Flush accumulated text into a message output item."""
        nonlocal text_buffer
        if not text_buffer:
            return None
        logger.info(
            "[task %s] flush_text: %d chars into message item", message_id[:8], len(text_buffer)
        )
        item = {
            "type": "message",
            "id": str(uuid.uuid4()),
            "status": "completed",
            "role": "assistant",
            "content": [{"type": "output_text", "text": text_buffer}],
        }
        output_items.append(item)
        text_buffer = ""
        _sync_state()
        return item

    def _sync_state():
        """Update in-memory state so API can serve it on refresh."""
        _task_state[message_id] = {"content": content, "output": output_items}

    try:
        provider = connection["provider"]
        api_key = decrypt_key(connection.get("api_key", ""), _get_jwt_secret())
        base_url = connection.get("base_url") or _default_base_url(provider)

        system = await _load_system_prompt(workspace, model)
        messages, loaded_summary = await _load_message_history(chat_id, message_id)
        if loaded_summary:
            system += f"\n\n[CONVERSATION SUMMARY]\n{loaded_summary}"
        if regeneration_prompt:
            messages.append({"role": "user", "content": regeneration_prompt})
        tools = await get_tool_list()

        # Remove view_skill tool if no skills are available
        skills = discover_skills(workspace)
        if not skills:
            tools = [t for t in tools if t["name"] != "view_skill"]

        # Strip delegate_task from sub-agent chats (depth limit = 1)
        chat_obj = await Chat.get_by_id(chat_id)
        if chat_obj and (chat_obj.meta or {}).get("subagent"):
            tools = [t for t in tools if t["name"] != "delegate_task"]

        # Parse $skill-name mentions from the user message to auto-activate skills
        chat_params = (chat_obj.meta or {}).get("params", {}) if chat_obj else {}
        attached_skill_ids: list[str] = []
        if skills and messages:
            # Find the last user message
            last_user = next((m for m in reversed(messages) if m["role"] == "user"), None)
            if last_user:
                import re as _re

                mentioned = _re.findall(
                    r"\$([a-z0-9](?:[a-z0-9-]*[a-z0-9])?)", last_user["content"]
                )
                skill_names = {s.name for s in skills}
                attached_skill_ids = [m for m in mentioned if m in skill_names]
        if attached_skill_ids:
            from cptr.utils.tools import _activated_skills

            skill_blocks = []
            for sid in attached_skill_ids:
                skill = load_skill(workspace, sid)
                if skill:
                    skill_blocks.append(format_skill_content(skill))
                    _activated_skills.add(sid)  # mark as activated for dedup
            if skill_blocks:
                system += "\n\n" + "\n\n".join(skill_blocks)

        # Plan mode: strip write tools, inject prompt as user message (not system, to preserve cache)
        plan_mode = chat_params.get("plan_mode", False)
        if plan_mode:
            tools = [t for t in tools if ALL_TOOLS.get(t["name"], {}).get("auto")]
            # Inject create_artifact (only available in plan mode)
            tools.append(_fn_to_schema("create_artifact", create_artifact))
            messages.append({"role": "user", "content": PLAN_MODE_PROMPT})
            logger.info(
                "[task %s] plan mode active, %d tools available", message_id[:8], len(tools)
            )

        # Tool approval mode: 'ask' | 'auto' | 'full'
        #   ask  = require approval for ALL tools (including reads)
        #   auto = auto-approve tools marked auto=True, ask for others
        #   full = auto-approve everything
        approval_mode = chat_params.get("tool_approval_mode", "auto")
        # Legacy compat: old boolean auto_approve_tools
        if "tool_approval_mode" not in chat_params and "auto_approve_tools" in chat_params:
            approval_mode = "full" if chat_params["auto_approve_tools"] else "auto"

        last_usage: dict | None = None  # real usage from last API call
        new_messages_since: int = 0  # messages appended since last API call

        # Request params: arbitrary key-value pairs merged into the API request body
        # Merge order: global ("*") → per-model → chat overrides (chat wins)
        chat_request_params = chat_params.get("request_params") or {}
        global_rp = {}
        model_rp = {}
        try:
            chat_models_config = await Config.get("chat.models") or {}
            global_rp = chat_models_config.get("*", {}).get("params", {}).get("request_params", {})
            model_rp = chat_models_config.get(model, {}).get("params", {}).get("request_params", {})
        except Exception:
            pass
        request_params = {**global_rp, **model_rp, **chat_request_params} or None

        for _iteration in range(CHAT_MAX_ITERATIONS):
            # ── Context compaction: summarize older messages if too large ──
            if should_compact(messages, system, last_usage, new_messages_since):
                target_keep = max(2, len(messages) * 2 // 5)
                split_idx = _find_safe_split(messages, target_keep)
                drop_zone = messages[:split_idx]
                keep_zone = messages[split_idx:]

                api_type = connection.get("api_type", "chat_completions")
                summary = await summarize_messages(
                    drop_zone,
                    loaded_summary,
                    provider,
                    base_url,
                    api_key,
                    model,
                    api_type=api_type,
                )

                # Store on the current message — this IS the cutoff
                await ChatMessage.update(message_id, chat_summary=summary)
                loaded_summary = summary

                # Append summary to system prompt (works for all providers)
                system = await _load_system_prompt(workspace, model)
                system += f"\n\n[CONVERSATION SUMMARY]\n{summary}"
                # Re-inject attached skills after compaction (protect from pruning)
                if attached_skill_ids:
                    skill_blocks = []
                    for sid in attached_skill_ids:
                        skill = load_skill(workspace, sid)
                        if skill:
                            skill_blocks.append(format_skill_content(skill))
                    if skill_blocks:
                        system += "\n\n" + "\n\n".join(skill_blocks)
                messages = keep_zone
                last_usage = None  # reset after compaction
                new_messages_since = 0

                logger.info(
                    "[task %s] compacted: dropped %d msgs, kept %d, summary=%d chars",
                    message_id[:8],
                    len(drop_zone),
                    len(keep_zone),
                    len(summary),
                )

            # Anthropic supports images natively in tool_result content blocks.
            # Chat Completions and Responses API don't support multimodal tool messages,
            # so extract images into a follow-up user message.
            api_messages = messages
            if provider != "anthropic":
                image_blocks = []
                api_messages = []
                for m in messages:
                    if m.get("role") == "tool" and isinstance(m.get("content"), list):
                        text_parts = []
                        for part in m["content"]:
                            if part.get("type") == "text":
                                text_parts.append(part.get("text", ""))
                            elif part.get("type") == "image":
                                image_blocks.append(part)
                        api_messages.append({**m, "content": "\n".join(text_parts)})
                    else:
                        api_messages.append(m)
                if image_blocks:
                    api_messages.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "Here are the images from the tool results above.",
                                },
                                *image_blocks,
                            ],
                        }
                    )

            form_data = ChatCompletionForm(
                model=model,
                messages=api_messages,
                instructions=system,
                tools=tools,
            )

            if provider == "anthropic":
                stream = stream_anthropic(
                    form_data, base_url, api_key, request_params=request_params
                )
            elif connection.get("api_type") == "responses":
                stream = stream_openai_responses(
                    form_data, base_url, api_key, request_params=request_params
                )
            else:
                stream = stream_openai_completions(
                    form_data, base_url, api_key, request_params=request_params
                )

            restart = False
            pending_calls: list[dict] = []  # Collect tool calls from this response
            pending_reasoning: list[dict] = []  # Reasoning items for round-tripping

            async for event in stream:
                if event["type"] == "text_delta":
                    content += event["content"]
                    text_buffer += event["content"]
                    await emit(delta=event["content"])
                    _sync_state()

                elif event["type"] == "tool_call":
                    # Collect tool call — don't execute yet
                    pending_calls.append(event)

                elif event["type"] == "reasoning":
                    # Collect reasoning items for round-tripping with tool calls
                    pending_reasoning.append(event["item"])

                elif event["type"] == "usage":
                    usage = {k: v for k, v in event.items() if k != "type"}
                    if "total_tokens" not in usage:
                        usage["total_tokens"] = usage.get("input_tokens", 0) + usage.get(
                            "output_tokens", 0
                        )
                    last_usage = usage
                    new_messages_since = 0

                    if not pending_calls:
                        # No tool calls — final response, we're done
                        _flush_text()
                        logger.info(
                            "[task %s] save (usage): content=%d chars, output=%d items, types=%s",
                            message_id[:8],
                            len(content),
                            len(output_items),
                            [i.get("type") for i in output_items],
                        )
                        await ChatMessage.update(
                            message_id,
                            content=content,
                            output=output_items,
                            usage=usage,
                            done=True,
                        )
                        _task_state.pop(message_id, None)
                        await _emit_done()
                        return

                elif event["type"] == "done":
                    # Stream ended without explicit usage
                    pass

            # ── Process collected tool calls ────────────────────
            if pending_calls:
                flushed_item = _flush_text()

                tool_ctx = {
                    "workspace": workspace,
                    "user_id": user_id,
                    "model_id": model,
                    "chat_id": chat_id,
                    "connection": connection,
                }

                # Check if any call needs approval
                needs_approval = None
                for tc in pending_calls:
                    name = tc["name"]
                    tool = ALL_TOOLS.get(name)
                    should_auto = approval_mode == "full" or (
                        approval_mode == "auto" and tool and tool["auto"]
                    )
                    if not should_auto:
                        needs_approval = tc
                        break

                if needs_approval:
                    # First non-auto tool stops the loop for approval
                    tc = needs_approval
                    # Store reasoning items before function_call for round-tripping
                    for ri in pending_reasoning:
                        output_items.append(ri)
                    item = {
                        "type": "function_call",
                        "id": str(uuid.uuid4()),
                        "call_id": tc["call_id"],
                        "fc_id": tc.get("id", ""),
                        "name": tc["name"],
                        "arguments": tc["arguments"],
                        "status": "pending",
                    }
                    output_items.append(item)
                    await ChatMessage.update(
                        message_id,
                        content=content,
                        output=output_items,
                        done=False,
                    )
                    if flushed_item:
                        await emit(output=flushed_item)
                    await emit(output=item)
                    _task_state.pop(message_id, None)
                    await emit(done=True)
                    return

                # All calls are auto-approved — store reasoning + build UI items
                for ri in pending_reasoning:
                    output_items.append(ri)
                call_items: list[tuple[dict, dict]] = []  # (event, ui_item)
                for tc in pending_calls:
                    item = {
                        "type": "function_call",
                        "id": str(uuid.uuid4()),
                        "call_id": tc["call_id"],
                        "fc_id": tc.get("id", ""),
                        "name": tc["name"],
                        "arguments": tc["arguments"],
                        "status": "in_progress",
                    }
                    output_items.append(item)
                    call_items.append((tc, item))

                # Emit all as in_progress
                if flushed_item:
                    await emit(output=flushed_item)
                for _, item in call_items:
                    await emit(output=item)
                _sync_state()

                # Separate delegate_task (concurrent) from others (sequential)
                delegate_indices = [i for i, (tc, _) in enumerate(call_items) if tc["name"] == "delegate_task"]
                other_indices = [i for i, (tc, _) in enumerate(call_items) if tc["name"] != "delegate_task"]

                # Execute non-delegate tools sequentially first
                # Collect results for batch message construction
                sequential_results: list[tuple[dict, str]] = []  # (event, result)
                for idx in other_indices:
                    tc, item = call_items[idx]
                    if tc["name"] == "create_artifact":
                        result = await create_artifact(**tc["arguments"], workspace=workspace)
                    else:
                        result = await execute_tool(tc["name"], tc["arguments"], tool_ctx)

                    # Append output BEFORE marking completed — if anything
                    # between here and persist fails, the call stays
                    # "in_progress" (safely skipped on reload) rather than
                    # "completed" without an output (corrupts history).
                    result_item = {
                        "type": "function_call_output",
                        "call_id": tc["call_id"],
                        "output": result,
                    }
                    output_items.append(result_item)
                    item["status"] = "completed"
                    await emit(output=item)
                    await emit(output=result_item)
                    _sync_state()

                    artifact_item = build_artifact_item(tc["name"], tc["arguments"], result)
                    if artifact_item:
                        output_items.append(artifact_item)
                        await emit(output=artifact_item)
                        _sync_state()

                    sequential_results.append((tc, result))

                # Build a single combined assistant message for all sequential calls
                # with their shared reasoning items (required for reasoning model round-tripping)
                if sequential_results:
                    _append_batch_to_messages(
                        messages, sequential_results, provider,
                        reasoning_items=pending_reasoning,
                    )
                    new_messages_since += 1 + len(sequential_results)

                # Execute delegate_task calls concurrently, emit each as it completes
                if delegate_indices:
                    # Create tasks, mapping task → index
                    inflight: dict[asyncio.Task, int] = {}
                    for idx in delegate_indices:
                        tc, _ = call_items[idx]
                        task = asyncio.create_task(
                            execute_tool(tc["name"], tc["arguments"], tool_ctx)
                        )
                        inflight[task] = idx

                    delegate_results: list[tuple[dict, str]] = []
                    while inflight:
                        done_set, _ = await asyncio.wait(
                            inflight.keys(), return_when=asyncio.FIRST_COMPLETED
                        )
                        for task in done_set:
                            idx = inflight.pop(task)
                            tc, item = call_items[idx]
                            try:
                                result = task.result()
                            except Exception as e:
                                result = f"Error: {e}"

                            # Append output BEFORE marking completed (same
                            # ordering fix as sequential path above).
                            result_item = {
                                "type": "function_call_output",
                                "call_id": tc["call_id"],
                                "output": result,
                            }
                            output_items.append(result_item)
                            item["status"] = "completed"
                            await emit(output=item)
                            await emit(output=result_item)
                            _sync_state()
                            delegate_results.append((tc, result))

                    # Build combined message for all delegate calls
                    if delegate_results:
                        # Only attach reasoning if sequential calls didn't consume it
                        ri = pending_reasoning if not other_indices else None
                        _append_batch_to_messages(
                            messages, delegate_results, provider,
                            reasoning_items=ri,
                        )
                        new_messages_since += 1 + len(delegate_results)

                # Persist after all tool calls
                await ChatMessage.update(message_id, content=content, output=output_items)
                restart = True

            if not restart:
                flushed_item = _flush_text()
                if flushed_item:
                    await emit(output=flushed_item)
                logger.info(
                    "[task %s] save (end): content=%d chars, output=%d items, types=%s",
                    message_id[:8],
                    len(content),
                    len(output_items),
                    [i.get("type") for i in output_items],
                )
                await ChatMessage.update(
                    message_id,
                    content=content,
                    output=output_items,
                    done=True,
                )
                _task_state.pop(message_id, None)
                await _emit_done()
                return

        # Max iterations reached
        await ChatMessage.update(
            message_id,
            content=content,
            output=output_items,
            done=True,
            meta={"error": "max iterations reached"},
        )
        _task_state.pop(message_id, None)
        await _emit_done()

    except asyncio.CancelledError:
        _flush_text()
        _scrub_incomplete_items(output_items)
        await ChatMessage.update(message_id, content=content, output=output_items, done=True)
        _task_state.pop(message_id, None)
        await _emit_done()
    except Exception as e:
        logger.exception(f"Chat task error for message {message_id}")
        _flush_text()
        error_msg = str(e)
        # Try to extract API error body for more detail
        if hasattr(e, "response"):
            try:
                body = e.response.text or ""
                if body:
                    import json as _json

                    err_data = _json.loads(body)
                    api_msg = err_data.get("error", {}).get("message", "")
                    if api_msg:
                        error_msg = api_msg
            except Exception:
                pass
        # Append error to content so it's visible in the chat
        error_block = f"\n\n> **Error:** {error_msg}"
        content += error_block
        text_buffer += error_block
        flushed_item = _flush_text()
        if flushed_item:
            await emit(output=flushed_item)
        _scrub_incomplete_items(output_items)
        await ChatMessage.update(
            message_id,
            content=content,
            output=output_items,
            done=True,
            meta={"error": error_msg},
        )
        _task_state.pop(message_id, None)
        await emit(done=True, error=error_msg)
    finally:
        # Guarantee the gateway SSE stream terminates.  If emit()
        # already pushed a done/error event the sentinel is harmless
        # (_stream checks for None separately).  Without this, a
        # crash in emit_to_user or an unexpected exit path leaves
        # the SSE generator hanging for up to 5 minutes.
        if output_queue is not None:
            try:
                await output_queue.put(None)
            except Exception:
                pass
        _tasks.pop(message_id, None)
        _task_state.pop(message_id, None)
        _task_chat.pop(message_id, None)
        try:
            await export_chat_to_file(chat_id)
        except Exception:
            logger.exception(f"Failed to export chat {chat_id}")
        # Generate a proper title if the chat still has the auto-truncated fallback
        try:
            chat_obj = await Chat.get_by_id(chat_id)
            if chat_obj:
                all_msgs = await ChatMessage.get_all_by_chat(chat_id)
                first_user = next(
                    (
                        m
                        for m in all_msgs
                        if m.role == "user" and not (m.meta and m.meta.get("queued"))
                    ),
                    None,
                )
                if first_user:
                    # The router sets title = content[:50] on creation.
                    # Only generate if the title still matches that fallback.
                    fallback = first_user.content[:50].strip() or "New Chat"
                    if chat_obj.title == fallback:
                        await generate_chat_title(
                            chat_id, user_id, connection, model, first_user.content
                        )
        except Exception:
            logger.debug(
                "[title] Error in title generation for chat %s", chat_id[:8], exc_info=True
            )
        # Fire webhook notification if configured
        try:
            webhook_url = await Config.get("notifications.webhook_url")
            if webhook_url:
                chat_obj = chat_obj or await Chat.get_by_id(chat_id)
                title = chat_obj.title if chat_obj else "Chat"
                preview = content[:300] if content else ""
                from cptr.utils.webhook import post_webhook

                await post_webhook(webhook_url, title, preview)
        except Exception:
            logger.debug("[webhook] Error sending webhook for chat %s", chat_id[:8], exc_info=True)
        # Process any queued follow-up messages
        try:
            await _process_queue(chat_id, user_id, workspace)
        except Exception:
            logger.exception(f"Failed to process queue for chat {chat_id}")
