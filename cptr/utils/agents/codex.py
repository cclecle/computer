"""Codex app-server adapter."""

from __future__ import annotations

import asyncio
import json
import os
import re
from contextlib import suppress
from typing import Any, AsyncIterator

from cptr.utils.agents.attachments import PreparedAgentAttachments
from cptr.utils.agents.events import (
    AgentDone,
    AgentError,
    AgentEvent,
    AgentReasoningDelta,
    AgentTextDelta,
    AgentToolUpdate,
)


class CodexAppServer:
    def __init__(self, command: str, cwd: str, env: dict[str, str]) -> None:
        self.command = command
        self.cwd = cwd
        self.env = env
        self.proc: asyncio.subprocess.Process | None = None
        self.reader_task: asyncio.Task | None = None
        self.stderr_task: asyncio.Task | None = None
        self.pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self.events: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.next_id = 1

    async def start(self) -> None:
        self.proc = await asyncio.create_subprocess_exec(
            self.command,
            "app-server",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.cwd or os.getcwd(),
            env=self.env,
        )
        self.reader_task = asyncio.create_task(self._reader_loop())
        self.stderr_task = asyncio.create_task(self._stderr_loop())
        await self.request(
            "initialize",
            {
                "clientInfo": {"name": "cptr", "version": "0"},
                "capabilities": {"experimentalApi": True},
            },
        )
        await self.notify("initialized")

    async def close(self) -> None:
        if self.proc and self.proc.returncode is None:
            self.proc.terminate()
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self.proc.wait(), timeout=3)
            if self.proc.returncode is None:
                self.proc.kill()
                await self.proc.wait()
        for task in (self.reader_task, self.stderr_task):
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        for future in self.pending.values():
            if not future.done():
                future.cancel()
        self.pending.clear()

    async def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = self.next_id
        self.next_id += 1
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self.pending[request_id] = future
        await self._send({"id": request_id, "method": method, "params": params})
        response = await future
        if response.get("error"):
            raise RuntimeError(str(response["error"]))
        return response

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {"method": method}
        if params is not None:
            payload["params"] = params
        await self._send(payload)

    async def _send(self, payload: dict[str, Any]) -> None:
        assert self.proc is not None and self.proc.stdin is not None
        self.proc.stdin.write((json.dumps(payload) + "\n").encode())
        await self.proc.stdin.drain()

    async def _reader_loop(self) -> None:
        assert self.proc is not None and self.proc.stdout is not None
        while True:
            line = await self.proc.stdout.readline()
            if not line:
                break
            try:
                message = json.loads(line.decode())
            except Exception:
                continue
            if (
                "id" in message
                and "method" not in message
                and ("result" in message or "error" in message)
            ):
                future = self.pending.pop(int(message["id"]), None)
                if future and not future.done():
                    future.set_result(message)
            else:
                await self.events.put(message)

    async def _stderr_loop(self) -> None:
        assert self.proc is not None and self.proc.stderr is not None
        while await self.proc.stderr.readline():
            pass


def _messages_to_prompt(messages: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")
        if isinstance(content, list):
            text = "\n".join(
                str(block.get("text", "")) for block in content if isinstance(block, dict)
            )
        else:
            text = str(content or "")
        if text:
            parts.append(f"[{role}]\n{text}")
    return "\n\n".join(parts)


def _approval_policy(value: str) -> str:
    return {"ask": "on-request", "auto": "on-failure", "full": "never"}.get(value, "on-failure")


def _chat_approval_mode(chat_params: dict[str, Any]) -> str:
    if "tool_approval_mode" in chat_params:
        return str(chat_params.get("tool_approval_mode") or "auto")
    if "auto_approve_tools" in chat_params:
        return "full" if chat_params.get("auto_approve_tools") else "auto"
    return "auto"


def _sandbox_for_approval(value: str) -> str:
    if value == "ask":
        return "read-only"
    return "workspace-write"


def _codex_turn_options(chat_params: dict[str, Any]) -> dict[str, str]:
    options: dict[str, str] = {}
    effort = chat_params.get("reasoningEffort") or chat_params.get("reasoning_effort")
    if isinstance(effort, str) and effort.strip():
        options["effort"] = effort.strip()
    service_tier = chat_params.get("serviceTier") or chat_params.get("service_tier")
    if isinstance(service_tier, str) and service_tier.strip():
        options["serviceTier"] = service_tier.strip()
    return options


def _tool_from_item_event(method: str, params: dict[str, Any]) -> AgentToolUpdate | None:
    if method not in {"item/started", "item/completed"}:
        return None
    item = params.get("item") if isinstance(params.get("item"), dict) else {}
    item_type = str(item.get("type") or "").strip()
    normalized_type = re.sub(r"[^a-z0-9]+", " ", item_type.lower()).strip()
    if not _is_tool_item_type(normalized_type):
        return None
    call_id = params.get("itemId") or item.get("id") or item.get("callId")
    if not isinstance(call_id, str) or not call_id.strip():
        return None
    title = str(item.get("title") or item.get("name") or item_type or "Codex action").strip()
    detail = _item_detail(item)
    return AgentToolUpdate(
        call_id=call_id.strip(),
        name="run_command" if "command" in normalized_type and detail else "agent_tool",
        status="completed" if method == "item/completed" else "in_progress",
        arguments={"command": detail}
        if "command" in normalized_type and detail
        else {"title": title},
        output=detail if method == "item/completed" else None,
    )


def _is_tool_item_type(normalized_type: str) -> bool:
    if not normalized_type:
        return False
    blocked = ("user", "agent message", "assistant", "reasoning", "thought", "plan", "todo")
    if any(value in normalized_type for value in blocked):
        return False
    allowed = (
        "command",
        "file change",
        "patch",
        "edit",
        "mcp",
        "dynamic tool",
        "collab",
        "web search",
        "image",
        "error",
    )
    return any(value in normalized_type for value in allowed)


def _item_detail(item: dict[str, Any]) -> str | None:
    for key in ("command", "title", "summary", "text", "path", "prompt"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


async def run_codex_agent(
    *,
    profile: dict[str, Any],
    model: str,
    workspace: str,
    messages: list[dict[str, Any]],
    system_prompt: str,
    chat_params: dict[str, Any],
    resume_state: dict[str, Any] | None,
    attachments: PreparedAgentAttachments,
) -> AsyncIterator[AgentEvent]:
    env = os.environ.copy()
    if profile.get("home"):
        env["CODEX_HOME"] = os.path.expanduser(str(profile["home"]))

    client = CodexAppServer(str(profile["command"]), workspace, env)
    thread_id: str | None = None
    turn_id: str | None = None
    try:
        await client.start()
        approval_mode = _chat_approval_mode(chat_params)
        thread_params: dict[str, Any] = {
            "cwd": workspace,
            "approvalPolicy": _approval_policy(approval_mode),
            "sandbox": _sandbox_for_approval(approval_mode),
        }
        if model != "default":
            thread_params["model"] = model
        if system_prompt:
            thread_params["developerInstructions"] = system_prompt

        response = await client.request("thread/start", thread_params)
        thread = response.get("result", {}).get("thread", {})
        thread_id = thread.get("id") if isinstance(thread, dict) else None
        if not thread_id:
            yield AgentError("Codex did not return a thread id")
            return

        prompt = _messages_to_prompt(messages)
        turn_input: list[dict[str, Any]] = []
        if prompt:
            turn_input.append({"type": "text", "text": prompt})
        for image in attachments.images:
            turn_input.append(
                {
                    "type": "image",
                    "url": f"data:{image.mime_type};base64,{image.base64}",
                }
            )
        turn_response = await client.request(
            "turn/start",
            {
                "threadId": thread_id,
                "input": turn_input,
                **_codex_turn_options(chat_params),
            },
        )
        turn = turn_response.get("result", {}).get("turn", {})
        turn_id = turn.get("id") if isinstance(turn, dict) else None

        while True:
            event = await client.events.get()
            method = event.get("method")
            params = event.get("params") if isinstance(event.get("params"), dict) else {}
            event_turn_id = params.get("turnId")
            if event_turn_id and turn_id and event_turn_id != turn_id:
                continue
            if method == "item/agentMessage/delta":
                delta = params.get("delta")
                if isinstance(delta, str) and delta:
                    yield AgentTextDelta(delta)
            elif method in ("item/reasoning/textDelta", "item/reasoning/summaryTextDelta"):
                delta = params.get("delta")
                if isinstance(delta, str) and delta:
                    yield AgentReasoningDelta(delta)
            else:
                tool = _tool_from_item_event(str(method or ""), params)
                if tool:
                    yield tool
            if method == "turn/completed":
                yield AgentDone(
                    resume_state={
                        "profile_id": profile["id"],
                        "thread_id": thread_id,
                        "turn_id": turn_id,
                        "workspace": workspace,
                        "model": model,
                    }
                )
                return
            elif method == "turn/failed":
                detail = params.get("message") or params.get("error") or "Codex turn failed"
                yield AgentError(str(detail))
                return
            elif method == "error":
                yield AgentError(str(params or "Codex app-server error"))
                return
    except asyncio.CancelledError:
        if thread_id and turn_id:
            with suppress(Exception):
                await client.request("turn/interrupt", {"threadId": thread_id, "turnId": turn_id})
        raise
    except Exception as exc:  # noqa: BLE001 - surfaced in the chat.
        yield AgentError(str(exc))
    finally:
        await client.close()
