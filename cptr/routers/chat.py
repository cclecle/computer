"""Chat router: CRUD for chats + model aggregation."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from cptr.models import Chat, ChatMessage, Config
from cptr.utils.config import check_access, now_ms, _get_jwt_secret
from cptr.utils.crypto import decrypt_key

router = APIRouter(prefix="/api/chats", tags=["chats"])

COOKIE_NAME = "cptr_session"


def _ensure_gitignore(workspace: str) -> None:
    """If workspace is a git repo, ensure .cptr is listed in .gitignore."""
    ws = Path(workspace)
    if not (ws / ".git").exists():
        return

    gitignore = ws / ".gitignore"
    entry = ".cptr"

    # Check if already ignored
    if gitignore.exists():
        content = gitignore.read_text(encoding="utf-8", errors="replace")
        # Match .cptr as a standalone line (not a substring of something else)
        for line in content.splitlines():
            stripped = line.strip()
            if stripped == entry or stripped == entry + "/":
                return
        # Append with a preceding newline if file doesn't end with one
        if content and not content.endswith("\n"):
            content += "\n"
        content += f"{entry}\n"
        gitignore.write_text(content, encoding="utf-8")
    else:
        gitignore.write_text(f"{entry}\n", encoding="utf-8")


def _get_user(request: Request) -> str:
    """Extract user_id from cookie, raise 401 if not authenticated."""
    token = request.cookies.get(COOKIE_NAME)
    client_host = request.client.host if request.client else "127.0.0.1"
    auth = check_access(client_host=client_host, jwt_token=token)
    if not auth or not auth.user_id:
        raise HTTPException(401, "authentication required")
    return auth.user_id


# ── List chats for a workspace ──────────────────────────────


@router.get("")
async def list_chats(
    request: Request,
    workspace: str = Query(..., description="Workspace root path"),
    limit: int = Query(50, ge=1, le=200, description="Max chats to return"),
    offset: int = Query(0, ge=0, description="Number of chats to skip"),
    sort_by: str = Query("updated_at", description="Sort field: 'title' or 'updated_at'"),
    sort_dir: str = Query("desc", description="Sort direction: 'asc' or 'desc'"),
):
    """List chats for a workspace by scanning .cptr/chats/ for JSON files.

    Returns chat metadata with relative folder paths for sidebar display.
    Supports pagination via limit/offset and sorting via sort_by/sort_dir.
    """
    user_id = _get_user(request)
    chats_dir = Path(workspace) / ".cptr" / "chats"

    if not chats_dir.exists():
        return {"chats": [], "total": 0, "has_more": False}

    # Scan filesystem for chat JSON files in a thread
    def _scan_chat_files() -> list[dict]:
        entries = []
        for json_file in chats_dir.rglob("*.json"):
            chat_id = json_file.stem
            rel_folder = str(json_file.parent.relative_to(chats_dir))
            if rel_folder == ".":
                rel_folder = ""
            entries.append({"id": chat_id, "folder": rel_folder})
        return entries

    chat_entries = await asyncio.to_thread(_scan_chat_files)

    if not chat_entries:
        return {"chats": [], "total": 0, "has_more": False}

    # Batch-fetch from DB
    chat_ids = [e["id"] for e in chat_entries]
    chats = await Chat.get_by_ids(chat_ids)
    chat_map = {c.id: c for c in chats}

    # Build response: only include chats owned by this user
    result = []
    for entry in chat_entries:
        chat = chat_map.get(entry["id"])
        if chat and chat.user_id == user_id:
            result.append(
                {
                    "id": chat.id,
                    "title": chat.title,
                    "summary": chat.summary,
                    "folder": entry["folder"],
                    "meta": chat.meta,
                    "current_message_id": chat.current_message_id,
                    "created_at": chat.created_at,
                    "updated_at": chat.updated_at,
                }
            )

    # Sort by requested field
    sort_field = sort_by if sort_by in ("title", "updated_at") else "updated_at"
    reverse = sort_dir != "asc"
    result.sort(key=lambda c: c[sort_field] or "", reverse=reverse)
    total = len(result)
    page = result[offset : offset + limit]
    return {"chats": page, "total": total, "has_more": offset + limit < total}


# ── Models aggregation ──────────────────────────────────────
# NOTE: Must be declared before /{chat_id} to avoid 'models' being treated as a chat_id.


async def _get_connections() -> list[dict]:
    return await Config.get("chat.connections") or []


# ── Model cache (app.state) ─────────────────────────────────


async def _get_connection_models(conn: dict, app_state) -> list[str]:
    """Get models for a connection: from stored data, cache, or auto-discover."""
    stored = conn.get("data", {}).get("models")
    if stored:
        return stored

    conn_id = conn.get("id", "")
    cache = getattr(app_state, "MODELS", None)
    if cache is None:
        cache = {}
        app_state.MODELS = cache

    if conn_id in cache:
        return cache[conn_id]

    models = await _fetch_provider_models(conn)
    cache[conn_id] = models
    return models


def invalidate_model_cache(app_state):
    """Clear cached models. Call after connection create/update/delete."""
    app_state.MODELS = {}


@router.get("/models")
async def get_models(request: Request):
    """Aggregate available models across all connections.

    If a connection has data.models set, use those.
    Otherwise, call the provider's /models endpoint to discover available models.
    """
    _get_user(request)
    connections = [c for c in await _get_connections() if c.get("enabled", True)]
    models = []

    for conn in connections:
        model_ids = await _get_connection_models(conn, request.app.state)

        prefix = (conn.get("prefix_id") or "").strip()

        for model_id in model_ids or []:
            prefixed_id = f"{prefix}/{model_id}" if prefix else model_id
            models.append(
                {
                    "id": prefixed_id,
                    "name": model_id,
                    "provider": conn.get("provider", ""),
                    "connection_id": conn["id"],
                }
            )

    default_model = await Config.get("chat.default_model")
    return {"models": models, "default": default_model}


async def _fetch_provider_models(conn: dict) -> list[str]:
    """Discover models from a provider's /models endpoint."""
    import httpx

    secret = _get_jwt_secret()
    api_key = decrypt_key(conn.get("api_key", ""), secret) if conn.get("api_key") else None
    provider = conn.get("provider", "")
    base_url = conn.get("base_url")

    try:
        if provider == "anthropic":
            url = (base_url or "https://api.anthropic.com/v1") + "/models"
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    url,
                    headers={
                        "x-api-key": api_key or "",
                        "anthropic-version": "2023-06-01",
                    },
                )
                if r.status_code == 200:
                    data = r.json()
                    return [m["id"] for m in data.get("data", [])]

        elif provider == "openai":
            url = (base_url or "https://api.openai.com/v1") + "/models"
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    url,
                    headers={
                        "Authorization": f"Bearer {api_key or ''}",
                    },
                )
                if r.status_code == 200:
                    data = r.json()
                    return [m["id"] for m in data.get("data", [])]

    except Exception:
        pass

    return []


# ── Get a chat with all messages ────────────────────────────


@router.get("/{chat_id}")
async def get_chat(chat_id: str, request: Request):
    """Get chat metadata + all messages."""
    user_id = _get_user(request)
    chat = await Chat.get_by_id(chat_id)
    if not chat or chat.user_id != user_id:
        raise HTTPException(404, "chat not found")

    messages = await ChatMessage.get_all_by_chat(chat_id)
    return {
        "chat": {
            "id": chat.id,
            "title": chat.title,
            "summary": chat.summary,
            "meta": chat.meta,
            "current_message_id": chat.current_message_id,
            "created_at": chat.created_at,
            "updated_at": chat.updated_at,
        },
        "messages": [_message_dict(m) for m in messages],
    }


def _message_dict(m) -> dict:
    """Serialize a ChatMessage, overlaying live state if task is running."""
    from cptr.utils.chat_task import get_live_state

    d = {
        "id": m.id,
        "parent_id": m.parent_id,
        "role": m.role,
        "content": m.content,
        "model": m.model,
        "done": m.done,
        "output": m.output,
        "usage": m.usage,
        "meta": m.meta,
        "created_at": m.created_at,
    }
    live = get_live_state(m.id)
    if live:
        d["content"] = live["content"]
        d["output"] = live["output"]
        d["done"] = False
    return d


# ── Delete a chat ───────────────────────────────────────────


@router.delete("/{chat_id}")
async def delete_chat(chat_id: str, request: Request):
    """Delete a chat and all its messages."""
    user_id = _get_user(request)
    chat = await Chat.get_by_id(chat_id)
    if not chat or chat.user_id != user_id:
        raise HTTPException(404, "chat not found")

    # Remove .cptr/chats/{id}.json marker
    workspace = chat.meta.get("workspace", "") if chat.meta else ""
    if workspace:
        marker = Path(workspace) / ".cptr" / "chats" / f"{chat_id}.json"
        await asyncio.to_thread(marker.unlink, True)  # missing_ok=True

    await Chat.delete(chat_id)
    return {"ok": True}


# ── Send a message ──────────────────────────────────────────


class SendMessageRequest(BaseModel):
    content: str = ""
    model_id: str
    workspace: str
    chat_id: Optional[str] = None
    parent_id: Optional[str] = None
    regeneration_prompt: Optional[str] = None
    files: List[dict] = []
    params: dict = {}


@router.post("")
async def send_message(body: SendMessageRequest, request: Request):
    """Send a message. Omit chat_id to create a new chat.
    Returns: { chat_id, message_id, queued? }
    """
    user_id = _get_user(request)

    # Create or fetch chat
    if body.chat_id:
        chat = await Chat.get_by_id(body.chat_id)
        if not chat or chat.user_id != user_id:
            raise HTTPException(404, "chat not found")
        # Sync params into chat meta
        if chat.meta is None:
            chat.meta = {}
        if chat.meta.get("params") != body.params:
            chat.meta["params"] = body.params
            await Chat.update_meta(chat.id, chat.meta)
    else:
        title = body.content[:50].strip() or "New Chat"
        chat = await Chat.create(
            user_id=user_id,
            title=title,
            meta={"workspace": body.workspace, "params": body.params},
            created_at=now_ms(),
        )
        # Ensure .cptr/chats/ dir exists (export will write the full JSON)
        chats_dir = Path(body.workspace) / ".cptr" / "chats"
        await asyncio.to_thread(lambda: chats_dir.mkdir(parents=True, exist_ok=True))

        # Auto-add .cptr to .gitignore if this is a git repo
        await asyncio.to_thread(_ensure_gitignore, body.workspace)

    # Check if the chat has an in-progress assistant message.
    # If so, queue this message instead of starting a new task.
    if body.chat_id and await _chat_has_active_generation(chat.id):
        user_msg = await ChatMessage.create(
            chat_id=chat.id,
            role="user",
            content=body.content,
            parent_id=body.parent_id,
            meta={"queued": True},
            created_at=now_ms(),
        )
        # Double-check: if generation finished during our create,
        # process queue now to close the race window.
        if not await _chat_has_active_generation(chat.id):
            from cptr.utils.chat_task import _process_queue

            workspace = (chat.meta or {}).get("workspace", body.workspace)
            await _process_queue(chat.id, user_id, workspace)
        return {"chat_id": chat.id, "message_id": user_msg.id, "queued": True}

    # Resolve connection for model
    connection, bare_model = await _resolve_connection(body.model_id, request.app.state)

    # Detect regeneration by checking parent message role
    parent_msg = await ChatMessage.get_by_id(body.parent_id) if body.parent_id else None

    if parent_msg and parent_msg.role == "user":
        # Regeneration: create assistant as sibling of existing response
        assistant_parent = body.parent_id
    else:
        # Normal send: create user message first
        user_meta = {"files": body.files} if body.files else None
        user_msg = await ChatMessage.create(
            chat_id=chat.id,
            role="user",
            content=body.content,
            parent_id=body.parent_id,
            meta=user_meta,
            created_at=now_ms(),
        )
        assistant_parent = user_msg.id

    # Create empty assistant message
    assistant_msg = await ChatMessage.create(
        chat_id=chat.id,
        role="assistant",
        content="",
        parent_id=assistant_parent,
        model=body.model_id,
        done=False,
        created_at=now_ms(),
    )

    # Update chat pointer to new leaf
    await Chat.update_current_message(chat.id, assistant_msg.id, now_ms())

    # Start background task (export_chat_to_file runs after task completes)
    from cptr.utils.chat_task import start_task

    start_task(
        message_id=assistant_msg.id,
        chat_id=chat.id,
        user_id=user_id,
        connection=connection,
        workspace=body.workspace,
        model=bare_model,
        regeneration_prompt=body.regeneration_prompt,
    )

    # Return the created messages so the frontend can append them
    # directly — no separate GET needed, no client-side construction.
    resp: dict = {
        "chat_id": chat.id,
        "message_id": assistant_msg.id,
        "assistant_message": _message_dict(assistant_msg),
    }
    if parent_msg is None or parent_msg.role != "user":
        resp["user_message"] = _message_dict(user_msg)
    return resp


# ── Approve / reject a pending tool call ────────────────────


class ApproveRequest(BaseModel):
    call_id: str
    approved: bool = True


@router.post("/{chat_id}/messages/{message_id}/approve")
async def approve_tool(chat_id: str, message_id: str, body: ApproveRequest, request: Request):
    """Execute or reject a pending tool call, then continue."""
    user_id = _get_user(request)
    chat = await Chat.get_by_id(chat_id)
    if not chat or chat.user_id != user_id:
        raise HTTPException(404, "chat not found")

    msg = await ChatMessage.get_by_id(message_id)
    if not msg or msg.chat_id != chat_id:
        raise HTTPException(404, "message not found")

    # Find pending tool call
    output = msg.output or []
    call = None
    for item in output:
        if (
            item.get("type") == "function_call"
            and item.get("call_id") == body.call_id
            and item.get("status") == "pending"
        ):
            call = item
            break

    if not call:
        raise HTTPException(400, "no pending tool call with that call_id")

    if body.approved:
        # Execute the tool
        from cptr.utils.tools import execute_tool

        result = await execute_tool(
            call["name"], call.get("arguments", {}), chat.meta.get("workspace", "")
        )
        call["status"] = "completed"
        output.append(
            {
                "type": "function_call_output",
                "call_id": body.call_id,
                "output": result,
            }
        )
        await ChatMessage.update(message_id, output=output, done=False)

        # Resolve connection and continue
        model_id = msg.model or ""
        connection, bare_model = await _resolve_connection(model_id, request.app.state)
        workspace = chat.meta.get("workspace", "") if chat.meta else ""

        from cptr.utils.chat_task import start_task

        start_task(
            message_id=message_id,
            chat_id=chat_id,
            user_id=user_id,
            connection=connection,
            workspace=workspace,
            model=bare_model,
        )
    else:
        call["status"] = "rejected"
        await ChatMessage.update(message_id, output=output, done=True)
        # Process queued messages since this chat is now idle
        from cptr.utils.chat_task import _process_queue

        workspace = chat.meta.get("workspace", "") if chat.meta else ""
        await _process_queue(chat_id, user_id, workspace)

    return {"ok": True}


# ── Cancel a running task ───────────────────────────────────


@router.post("/{chat_id}/messages/{message_id}/cancel")
async def cancel_task_endpoint(chat_id: str, message_id: str, request: Request):
    """Cancel running task, preserve partial output."""
    user_id = _get_user(request)
    chat = await Chat.get_by_id(chat_id)
    if not chat or chat.user_id != user_id:
        raise HTTPException(404, "chat not found")

    from cptr.utils.chat_task import cancel_task

    found = await cancel_task(message_id)

    if not found:
        # Task already exited (e.g., waiting for tool approval) but message
        # may still be marked done=False, force-finalize it.
        msg = await ChatMessage.get_by_id(message_id)
        if msg and not msg.done:
            output = msg.output or []
            for item in output:
                if item.get("type") == "function_call" and item.get("status") == "pending":
                    item["status"] = "rejected"
            await ChatMessage.update(message_id, output=output, done=True)

    # Process queued messages since this chat may now be idle
    from cptr.utils.chat_task import _process_queue

    workspace = chat.meta.get("workspace", "") if chat.meta else ""
    await _process_queue(chat_id, user_id, workspace)

    return {"ok": True}


# ── Update current branch pointer ──────────────────────────


class UpdateCurrentRequest(BaseModel):
    message_id: str


@router.post("/{chat_id}/current")
async def update_current(chat_id: str, body: UpdateCurrentRequest, request: Request):
    """Set current_message_id (the active branch leaf)."""
    user_id = _get_user(request)
    chat = await Chat.get_by_id(chat_id)
    if not chat or chat.user_id != user_id:
        raise HTTPException(404, "chat not found")
    await Chat.update_current_message(chat_id, body.message_id, now_ms())
    return {"ok": True}


# ── Update message content / output ────────────────────────


class UpdateMessageRequest(BaseModel):
    content: Optional[str] = None
    output: Optional[list] = None


@router.patch("/{chat_id}/messages/{message_id}")
async def update_message(
    chat_id: str, message_id: str, body: UpdateMessageRequest, request: Request
):
    """Edit a message's content or output in-place."""
    user_id = _get_user(request)
    chat = await Chat.get_by_id(chat_id)
    if not chat or chat.user_id != user_id:
        raise HTTPException(404, "chat not found")

    updates = {}
    if body.content is not None:
        updates["content"] = body.content
    if body.output is not None:
        updates["output"] = body.output
    if updates:
        await ChatMessage.update(message_id, **updates)
    return {"ok": True}


# ── Create message directly (no task) ──────────────────────


class CreateMessageRequest(BaseModel):
    parent_id: Optional[str] = None
    role: str
    content: str
    output: Optional[list] = None


@router.post("/{chat_id}/messages")
async def create_message_endpoint(chat_id: str, body: CreateMessageRequest, request: Request):
    """Create a message without starting a task (for Save As Copy)."""
    user_id = _get_user(request)
    chat = await Chat.get_by_id(chat_id)
    if not chat or chat.user_id != user_id:
        raise HTTPException(404, "chat not found")

    msg = await ChatMessage.create(
        chat_id=chat_id,
        role=body.role,
        content=body.content,
        parent_id=body.parent_id,
        output=body.output,
        done=True,
        created_at=now_ms(),
    )
    await Chat.update_current_message(chat_id, msg.id, now_ms())
    return {"ok": True, "message_id": msg.id}


async def _chat_has_active_generation(chat_id: str) -> bool:
    """Check if any assistant message in this chat has done=False."""
    messages = await ChatMessage.get_all_by_chat(chat_id)
    return any(m.role == "assistant" and not m.done for m in messages)


# ── Queue management ───────────────────────────────────────


@router.post("/{chat_id}/queue/{message_id}/send")
async def queue_send_now(chat_id: str, message_id: str, request: Request):
    """Cancel current generation, dequeue this message, send it immediately."""
    user_id = _get_user(request)
    chat = await Chat.get_by_id(chat_id)
    if not chat or chat.user_id != user_id:
        raise HTTPException(404, "chat not found")

    msg = await ChatMessage.get_by_id(message_id)
    if not msg or msg.chat_id != chat_id:
        raise HTTPException(404, "message not found")
    if not (msg.meta and msg.meta.get("queued")):
        raise HTTPException(400, "message is not queued")

    # Cancel any active task
    all_msgs = await ChatMessage.get_all_by_chat(chat_id)
    for m in all_msgs:
        if m.role == "assistant" and not m.done:
            from cptr.utils.chat_task import cancel_task

            await cancel_task(m.id)
            await ChatMessage.update(m.id, done=True)

    # Delete all OTHER queued messages, keep this one
    for m in all_msgs:
        if m.role == "user" and m.meta and m.meta.get("queued") and m.id != message_id:
            await ChatMessage.delete(m.id)

    # Clear queued flag on this message
    meta = dict(msg.meta or {})
    meta.pop("queued", None)
    await ChatMessage.update(message_id, meta=meta or None)

    # Find parent: latest done assistant message, or the queued message's parent
    done_assistants = [m for m in all_msgs if m.role == "assistant" and m.done]
    parent_id = done_assistants[-1].id if done_assistants else msg.parent_id

    # Re-parent the user message to the correct leaf
    if msg.parent_id != parent_id:
        await ChatMessage.update(message_id, parent_id=parent_id)

    # Resolve connection and start task
    model_id = msg.model or (all_msgs[-1].model if all_msgs else "")
    if not model_id:
        # Fall back to last used model from chat meta
        model_id = (chat.meta or {}).get("last_model", "")
    connection, bare_model = await _resolve_connection(model_id, request.app.state)
    workspace = (chat.meta or {}).get("workspace", "")

    assistant_msg = await ChatMessage.create(
        chat_id=chat_id,
        role="assistant",
        content="",
        parent_id=message_id,
        model=model_id,
        done=False,
        created_at=now_ms(),
    )
    await Chat.update_current_message(chat_id, assistant_msg.id, now_ms())

    from cptr.utils.chat_task import start_task

    start_task(
        message_id=assistant_msg.id,
        chat_id=chat_id,
        user_id=user_id,
        connection=connection,
        workspace=workspace,
        model=bare_model,
    )
    return {"ok": True, "chat_id": chat_id, "message_id": assistant_msg.id}


@router.delete("/{chat_id}/queue/{message_id}")
async def queue_delete(chat_id: str, message_id: str, request: Request):
    """Remove a queued message."""
    user_id = _get_user(request)
    chat = await Chat.get_by_id(chat_id)
    if not chat or chat.user_id != user_id:
        raise HTTPException(404, "chat not found")

    msg = await ChatMessage.get_by_id(message_id)
    if not msg or msg.chat_id != chat_id:
        raise HTTPException(404, "message not found")
    if not (msg.meta and msg.meta.get("queued")):
        raise HTTPException(400, "message is not queued")

    await ChatMessage.delete(message_id)
    return {"ok": True}


async def _resolve_connection(model_id: str, app_state=None) -> tuple[dict, str]:
    """Find connection for model.
    'openrouter/gpt-4o' → connection with prefix_id='openrouter', bare model='gpt-4o'
    'claude-sonnet-4-20250514' → scan all connections for match
    Raises 400 if not found.
    """
    connections = [c for c in await _get_connections() if c.get("enabled", True)]
    if not connections:
        raise HTTPException(400, "no connections configured")

    # Try prefix match first
    if "/" in model_id:
        prefix, bare = model_id.split("/", 1)
        for conn in connections:
            if (conn.get("prefix_id") or "").strip() == prefix:
                return conn, bare

    # Scan all connections using cache
    for conn in connections:
        if app_state:
            model_ids = await _get_connection_models(conn, app_state)
        else:
            model_ids = conn.get("data", {}).get("models") or await _fetch_provider_models(conn)
        prefix = (conn.get("prefix_id") or "").strip()
        for mid in model_ids:
            prefixed = f"{prefix}/{mid}" if prefix else mid
            if prefixed == model_id or mid == model_id:
                return conn, mid

    raise HTTPException(400, f"no connection found for model: {model_id}")
