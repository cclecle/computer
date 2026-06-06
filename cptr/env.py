"""Centralized environment configuration for cptr.

All environment variable reads go here. Import from this module
instead of reading os.environ directly.
"""

from __future__ import annotations

import os
from pathlib import Path

# ── Data directory ──────────────────────────────────────────
# Where cptr stores its database, config, and user data.
# Default: ~/.cptr
DATA_DIR = Path(os.environ.get("CPTR_DATA_DIR", str(Path.home() / ".cptr")))
CONFIG_FILE = DATA_DIR / "config.toml"
DB_FILE = DATA_DIR / "app.db"

# ── Startup token ───────────────────────────────────────────
# One-time token for first-time setup. Set by CLI, consumed by app.
STARTUP_TOKEN: str | None = os.environ.pop("CPTR_STARTUP_TOKEN", None)

# ── Chat settings ───────────────────────────────────────────
CHAT_MAX_ITERATIONS = int(os.environ.get("CHAT_MAX_ITERATIONS", "2048"))
ENABLE_CHAT_RECONCILE_ON_STARTUP: bool = os.environ.get(
    "ENABLE_CHAT_RECONCILE_ON_STARTUP", "true"
).lower() in ("true", "1", "yes")
CHAT_TOOL_MAX_CHARS = int(os.environ.get("CHAT_TOOL_MAX_CHARS", "50000"))
CHAT_TOOL_COMMAND_MAX_CHARS = int(os.environ.get("CHAT_TOOL_COMMAND_MAX_CHARS", "8000"))

# ── AI stream settings ──────────────────────────────────────
STREAM_CONNECT_TIMEOUT_SECONDS = float(os.environ.get("CPTR_STREAM_CONNECT_TIMEOUT", "30"))
STREAM_READ_TIMEOUT_SECONDS = float(os.environ.get("CPTR_STREAM_READ_TIMEOUT", "300"))
STREAM_WRITE_TIMEOUT_SECONDS = float(os.environ.get("CPTR_STREAM_WRITE_TIMEOUT", "600"))
