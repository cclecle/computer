"""Tool definitions: plain functions with schema introspection.

Tools are real async functions. Schemas are auto-generated from
type hints + docstrings via inspect. The LLM never sees the
`workspace` parameter; it's injected by the task runner.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import uuid
from pathlib import Path
from typing import get_type_hints
from cptr.env import CHAT_TOOL_COMMAND_MAX_CHARS, CHAT_TOOL_MAX_CHARS


# ── Background task state ───────────────────────────────────

_bg_tasks: dict[str, dict] = {}  # task_id → {proc, output, command, done}
_BG_TASK_LIMIT = 5


async def _collect_bg_output(task_id: str, proc: asyncio.subprocess.Process):
    """Collect output from a background process into the task buffer."""
    try:
        while True:
            chunk = await proc.stdout.read(4096)
            if not chunk:
                break
            task = _bg_tasks.get(task_id)
            if task:
                task["output"].extend(chunk)
                # Cap buffer at 256KB
                if len(task["output"]) > 256 * 1024:
                    task["output"] = task["output"][-256 * 1024 :]
    except Exception:
        pass
    finally:
        task = _bg_tasks.get(task_id)
        if task:
            task["done"] = True


# ── Helper ──────────────────────────────────────────────────


def _human_size(size: int) -> str:
    """Format byte size for display."""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"


def _truncate_output(text: str, max_chars: int = 80_000) -> str:
    """Truncate long output, keeping head and tail."""
    if len(text) <= max_chars:
        return text
    half = max_chars // 2
    return text[:half] + "\n\n... (truncated) ...\n\n" + text[-half:]


# ── Tool functions ──────────────────────────────────────────


async def read_file(
    path: str,
    start_line: int = 0,
    end_line: int = 0,
    *,
    workspace: str,
) -> str:
    """Read file contents with optional line range. Lines are 1-indexed.
    Supports absolute paths for user-attached files.
    :param path: Path relative to workspace root, or absolute path for attached files.
    :param start_line: First line to read (1-indexed, 0 = from beginning).
    :param end_line: Last line to read (inclusive, 0 = to end of file).
    """
    full = _resolve_path(path, workspace)
    if not full.is_file():
        return f"Error: file not found: {path}"

    size = full.stat().st_size
    if size > 500_000:
        return f"Error: file too large ({size} bytes, max 500KB)"

    lines = full.read_text(errors="replace").splitlines()
    total = len(lines)

    if start_line > 0 or end_line > 0:
        s = max(1, start_line) - 1  # Convert to 0-indexed
        e = min(total, end_line) if end_line > 0 else total
        selected = lines[s:e]
        numbered = [f"{i + s + 1}: {line}" for i, line in enumerate(selected)]
        header = f"File: {path} | Lines {s + 1}-{e} of {total}\n"
        return header + "\n".join(numbered)
    else:
        # Cap at 800 lines, show line numbers
        capped = lines[:800]
        numbered = [f"{i + 1}: {line}" for i, line in enumerate(capped)]
        header = f"File: {path} | Total lines: {total}"
        if total > 800:
            header += " (showing first 800)"
        return header + "\n" + "\n".join(numbered)


async def list_directory(
    path: str = ".",
    recursive: bool = False,
    *,
    workspace: str,
) -> str:
    """List files and directories with metadata (sizes, child counts).
    :param path: Directory path relative to workspace root.
    :param recursive: Whether to list recursively.
    """
    full = _resolve_path(path, workspace)
    if not full.is_dir():
        return f"Error: not a directory: {path}"

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
    }
    entries = []

    if recursive:
        for root, dirs, files in os.walk(full):
            dirs[:] = sorted(d for d in dirs if d not in ignore)
            rel = Path(root).relative_to(full)
            for f in sorted(files):
                fpath = Path(root) / f
                try:
                    sz = fpath.stat().st_size
                except OSError:
                    sz = 0
                entries.append(f"{rel / f}  ({_human_size(sz)})")
    else:
        for item in sorted(full.iterdir()):
            if item.name in ignore:
                continue
            if item.is_dir():
                try:
                    count = sum(1 for _ in item.rglob("*") if _.is_file())
                except (PermissionError, OSError):
                    count = 0
                entries.append(f"{item.name}/  ({count} files)")
            else:
                try:
                    sz = item.stat().st_size
                except OSError:
                    sz = 0
                entries.append(f"{item.name}  ({_human_size(sz)})")

    res = "\n".join(entries) if entries else "(empty directory)"
    return _truncate_output(res, max_chars=CHAT_TOOL_MAX_CHARS)


async def search_files(
    query: str,
    path: str = ".",
    regex: bool = False,
    case_insensitive: bool = False,
    include: str = "",
    filenames_only: bool = False,
    *,
    workspace: str,
) -> str:
    """Search files for a pattern using ripgrep. Fast, respects .gitignore.
    :param query: Search pattern (plain text or regex).
    :param path: Directory to search in, relative to workspace.
    :param regex: Treat query as a regular expression.
    :param case_insensitive: Case-insensitive matching.
    :param include: Glob pattern to filter files (e.g. '*.py', '*.ts').
    :param filenames_only: Only return filenames, not matching lines.
    """
    full = _resolve_path(path, workspace)
    if not full.is_dir():
        return f"Error: not a directory: {path}"

    # Try ripgrep first
    try:
        res = await _search_rg(query, full, regex, case_insensitive, include, filenames_only)
    except FileNotFoundError:
        # ripgrep not installed, fall back to Python
        res = await _search_python(query, full, case_insensitive)

    return _truncate_output(res, max_chars=CHAT_TOOL_MAX_CHARS)


async def _search_rg(
    query: str, full: Path, regex: bool, case_insensitive: bool, include: str, filenames_only: bool
) -> str:
    """Search using ripgrep."""
    args = ["rg", "--no-heading", "--max-count=50", "--color=never"]
    if not regex:
        args.append("--fixed-strings")
    if case_insensitive:
        args.append("--ignore-case")
    if filenames_only:
        args.append("--files-with-matches")
    else:
        args.append("--line-number")
    if include:
        for glob in include.split(","):
            glob = glob.strip()
            if glob:
                args.extend(["--glob", glob])

    args.extend(["--", query, str(full)])

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
    output = stdout.decode(errors="replace").strip()

    if proc.returncode == 1:
        return "No matches found."
    if proc.returncode > 1:
        err = stderr.decode(errors="replace").strip()
        raise FileNotFoundError(err) if "not found" in err.lower() else Exception(err)

    # Make paths relative
    prefix = str(full) + os.sep
    lines = output.splitlines()[:50]
    result = [line.replace(prefix, "") for line in lines]
    return "\n".join(result) if result else "No matches found."


async def _search_python(query: str, full: Path, case_insensitive: bool) -> str:
    """Fallback search using pure Python (when ripgrep not installed)."""
    results = []
    ignore = {".git", "node_modules", "__pycache__", ".venv", "venv"}
    q = query.lower() if case_insensitive else query

    for root, dirs, files in os.walk(full):
        dirs[:] = [d for d in dirs if d not in ignore]
        for fname in files:
            fpath = Path(root) / fname
            try:
                text = fpath.read_text(errors="replace")
            except (OSError, PermissionError):
                continue
            for i, line in enumerate(text.splitlines(), 1):
                target = line.lower() if case_insensitive else line
                if q in target:
                    rel = fpath.relative_to(full)
                    results.append(f"{rel}:{i}: {line.strip()}")
                    if len(results) >= 50:
                        results.append("... (truncated at 50 matches)")
                        return "\n".join(results)

    return "\n".join(results) if results else "No matches found."


async def create_file(
    path: str,
    content: str,
    overwrite: bool = False,
    artifact_type: str = "",
    *,
    workspace: str,
) -> str:
    """Create a new file. Errors if file already exists unless overwrite is true.
    For non-trivial tasks (multi-file changes, ambiguous requirements, architectural decisions),
    create an implementation plan first with artifact_type='implementation_plan'. Write the plan
    as markdown, then wait for the user to review before making changes.
    :param path: Path relative to workspace root.
    :param content: File contents to write.
    :param overwrite: Set to true to overwrite an existing file.
    :param artifact_type: Set to 'implementation_plan' to present a plan for user review before coding.
    """
    full = _resolve_path(path, workspace)
    if full.is_file() and not overwrite:
        return f"Error: file already exists: {path}. Use overwrite=true or edit_file to modify."
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content)
    return f"Created {path} ({len(content)} bytes, {len(content.splitlines())} lines)"


async def write_file(path: str, content: str, *, workspace: str) -> str:
    """Write or create a file (full content). Prefer edit_file for modifications.
    :param path: Path relative to workspace root.
    :param content: File contents to write.
    """
    full = _resolve_path(path, workspace)
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content)
    return f"Wrote {len(content)} bytes to {path}"


async def edit_file(
    path: str,
    target: str,
    replacement: str,
    start_line: int = 0,
    end_line: int = 0,
    *,
    workspace: str,
) -> str:
    """Replace a specific text block in a file. Only provide the text that changes.
    :param path: Path relative to workspace root.
    :param target: Exact text to find and replace (must match file content exactly).
    :param replacement: Text to replace the target with.
    :param start_line: Narrow search to lines starting here (1-indexed, 0 = from start).
    :param end_line: Narrow search to lines ending here (0 = to end).
    """
    full = _resolve_path(path, workspace)
    if not full.is_file():
        return f"Error: file not found: {path}"

    content = full.read_text(errors="replace")

    if start_line > 0 or end_line > 0:
        lines = content.splitlines(keepends=True)
        total = len(lines)
        s = max(1, start_line) - 1
        e = min(total, end_line) if end_line > 0 else total
        region = "".join(lines[s:e])

        if target not in region:
            return f"Error: target text not found in lines {s + 1}-{e} of {path}"

        count = region.count(target)
        if count > 1:
            return (
                f"Error: target text found {count} times in lines {s + 1}-{e}. "
                f"Narrow the line range or use a more specific target."
            )

        new_region = region.replace(target, replacement, 1)
        new_content = "".join(lines[:s]) + new_region + "".join(lines[e:])
    else:
        count = content.count(target)
        if count == 0:
            return f"Error: target text not found in {path}"
        if count > 1:
            return (
                f"Error: target text found {count} times in {path}. "
                f"Use start_line/end_line to disambiguate."
            )
        new_content = content.replace(target, replacement, 1)

    full.write_text(new_content)
    target_lines = len(target.splitlines())
    replacement_lines = len(replacement.splitlines())
    return (
        f"Edited {path}: replaced {target_lines} lines with {replacement_lines} lines "
        f"({len(target)} chars → {len(replacement)} chars)"
    )


async def multi_edit_file(
    path: str,
    edits: str,
    *,
    workspace: str,
) -> str:
    """Apply multiple non-contiguous edits to a file in one operation.
    :param path: Path relative to workspace root.
    :param edits: JSON array of edit objects, each with 'target' and 'replacement' strings, and optional 'start_line'/'end_line' integers.
    """
    full = _resolve_path(path, workspace)
    if not full.is_file():
        return f"Error: file not found: {path}"

    try:
        edit_list = json.loads(edits)
    except json.JSONDecodeError as e:
        return f"Error: invalid edits JSON: {e}"

    if not isinstance(edit_list, list) or not edit_list:
        return "Error: edits must be a non-empty JSON array"

    content = full.read_text(errors="replace")
    applied = 0

    for i, edit in enumerate(edit_list):
        target = edit.get("target", "")
        replacement = edit.get("replacement", "")

        if not target:
            return f"Error: edit {i + 1} missing 'target'"

        if target not in content:
            return f"Error: target not found for edit {i + 1}: {target[:100]}..."

        count = content.count(target)
        if count > 1:
            return (
                f"Error: edit {i + 1} target found {count} times. "
                f"Each target must be unique in the file."
            )

        content = content.replace(target, replacement, 1)
        applied += 1

    full.write_text(content)
    return f"Applied {applied} edits to {path}"


async def run_command(
    command: str,
    cwd: str = ".",
    timeout: int = 30,
    background: bool = False,
    *,
    workspace: str,
) -> str:
    """Run a shell command. Use background=true for long-running processes.
    :param command: The shell command to execute.
    :param cwd: Working directory relative to workspace root.
    :param timeout: Timeout in seconds (max 300, ignored if background).
    :param background: Run in background and return a task_id for status checks.
    """
    work_dir = _resolve_path(cwd, workspace)
    if not work_dir.is_dir():
        return f"Error: not a directory: {cwd}"

    env = {**os.environ, "PAGER": "cat", "GIT_PAGER": "cat"}

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(work_dir),
            env=env,
        )

        if background:
            active = sum(1 for t in _bg_tasks.values() if not t.get("done"))
            if active >= _BG_TASK_LIMIT:
                proc.kill()
                return (
                    f"Error: too many background tasks ({active}/{_BG_TASK_LIMIT}). Kill one first."
                )

            task_id = uuid.uuid4().hex[:8]
            _bg_tasks[task_id] = {
                "proc": proc,
                "output": bytearray(),
                "command": command,
                "done": False,
            }
            asyncio.create_task(_collect_bg_output(task_id, proc))
            return f"Background task started: {task_id}\nCommand: {command}\nUse check_task('{task_id}') to see output or kill_task('{task_id}') to stop it."

        timeout = min(max(timeout, 5), 300)
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        output = stdout.decode(errors="replace").strip()
        output = _truncate_output(output, max_chars=CHAT_TOOL_COMMAND_MAX_CHARS)

        if proc.returncode != 0:
            return f"Exit code {proc.returncode}\n{output}"
        return output or "(no output)"

    except asyncio.TimeoutError:
        proc.kill()
        return f"Error: command timed out after {timeout}s. Consider using background=true for long commands."
    except Exception as e:
        return f"Error: {e}"


async def check_task(task_id: str, *, workspace: str) -> str:
    """Check status and recent output of a background task.
    :param task_id: The task ID returned by run_command with background=true.
    """
    task = _bg_tasks.get(task_id)
    if not task:
        available = list(_bg_tasks.keys())
        return f"Error: no task with id '{task_id}'. Active tasks: {available or 'none'}"

    proc = task["proc"]
    output = task["output"].decode(errors="replace")
    output = _truncate_output(output, max_chars=CHAT_TOOL_COMMAND_MAX_CHARS)

    done = task.get("done", False) or proc.returncode is not None
    if done:
        status = f"exited (code {proc.returncode})"
    else:
        status = "running"

    return f"Task {task_id}: {status}\nCommand: {task['command']}\n---\n{output}"


async def kill_task(task_id: str, *, workspace: str) -> str:
    """Kill a running background task.
    :param task_id: The task ID to kill.
    """
    task = _bg_tasks.get(task_id)
    if not task:
        available = list(_bg_tasks.keys())
        return f"Error: no task with id '{task_id}'. Active tasks: {available or 'none'}"

    proc = task["proc"]
    if proc.returncode is not None:
        _bg_tasks.pop(task_id, None)
        return f"Task {task_id} already finished (code {proc.returncode})"

    try:
        proc.kill()
    except ProcessLookupError:
        pass
    _bg_tasks.pop(task_id, None)
    return f"Killed task {task_id}"


async def web_search(query: str, *, workspace: str) -> str:
    """Search the web for information. Returns summaries with source URLs.
    :param query: The search query.
    """
    # Defer to web module
    from cptr.utils.web import web_search_handler

    return await web_search_handler(query)


async def read_url(url: str, *, workspace: str) -> str:
    """Fetch content from a URL and return as text. Converts HTML to readable text.
    :param url: The URL to fetch.
    """
    from cptr.utils.web import read_url_handler

    return await read_url_handler(url)


# ── Path safety ──────────────────────────────────────────────


def _resolve_path(path: str, workspace: str) -> Path:
    """Resolve a path within the workspace or uploads dir. Rejects traversal."""
    from cptr.utils.storage import UPLOADS_DIR

    p = Path(path)
    # Allow absolute paths to the uploads directory (for user-attached files)
    if p.is_absolute():
        full = p.resolve()
        uploads = str(UPLOADS_DIR.resolve())
        ws = str(Path(workspace).resolve())
        if str(full).startswith(uploads) or str(full).startswith(ws):
            return full
        raise ValueError(f"Path outside allowed directories: {path}")

    # Relative paths resolve against workspace
    ws = Path(workspace).resolve()
    full = (ws / path).resolve()
    if not str(full).startswith(str(ws)):
        raise ValueError(f"Path traversal rejected: {path}")
    return full


# ── Registry ────────────────────────────────────────────────

TOOLS: dict[str, dict] = {
    # Read-only (auto-approve)
    "read_file": {"fn": read_file, "auto": True},
    "list_directory": {"fn": list_directory, "auto": True},
    "search_files": {"fn": search_files, "auto": True},
    "check_task": {"fn": check_task, "auto": True},
    "web_search": {"fn": web_search, "auto": True},
    "read_url": {"fn": read_url, "auto": True},
    # Write / mutate (require approval unless auto_approve_all)
    "create_file": {"fn": create_file, "auto": False},
    "edit_file": {"fn": edit_file, "auto": False},
    "multi_edit_file": {"fn": multi_edit_file, "auto": False},
    "write_file": {"fn": write_file, "auto": False},
    "run_command": {"fn": run_command, "auto": False},
    "kill_task": {"fn": kill_task, "auto": False},
}


# ── Schema from function signature ──────────────────────────

_TYPE_MAP = {str: "string", int: "integer", bool: "boolean", float: "number"}


def _parse_param_descriptions(docstring: str) -> dict[str, str]:
    """Extract :param name: description lines from docstring."""
    descs: dict[str, str] = {}
    if not docstring:
        return descs
    for line in docstring.splitlines():
        line = line.strip()
        if line.startswith(":param "):
            rest = line[7:]
            if ":" in rest:
                name, desc = rest.split(":", 1)
                descs[name.strip()] = desc.strip()
    return descs


def _fn_to_schema(name: str, fn) -> dict:
    """Introspect function → {name, description, parameters} for LLM."""
    doc = inspect.getdoc(fn) or ""
    description = doc.split("\n")[0]
    param_descs = _parse_param_descriptions(doc)
    hints = get_type_hints(fn)
    sig = inspect.signature(fn)
    properties: dict[str, dict] = {}
    required: list[str] = []
    for pname, param in sig.parameters.items():
        if pname == "workspace":
            continue
        ptype = _TYPE_MAP.get(hints.get(pname), "string")  # type: ignore[arg-type]
        prop: dict = {"type": ptype}
        if pname in param_descs:
            prop["description"] = param_descs[pname]
        properties[pname] = prop
        # Positional with no default → required
        if (
            param.default is inspect.Parameter.empty
            and param.kind != inspect.Parameter.KEYWORD_ONLY
        ):
            required.append(pname)
    return {
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }


def get_tool_list() -> list[dict]:
    """Return tool schemas for the LLM."""
    return [_fn_to_schema(name, t["fn"]) for name, t in TOOLS.items()]


async def execute_tool(name: str, args: dict, workspace: str) -> str:
    """Execute a tool by name. Returns output string."""
    info = TOOLS.get(name)
    if not info:
        return f"Error: unknown tool: {name}"
    fn = info["fn"]
    try:
        return await fn(**args, workspace=workspace)
    except Exception as e:
        return f"Error executing {name}: {e}"
