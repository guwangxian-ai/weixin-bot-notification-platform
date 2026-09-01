from __future__ import annotations

import os
import sys
from pathlib import Path


def _is_hermes_agent_root(path: Path) -> bool:
    return (path / "gateway" / "platforms" / "weixin.py").is_file() and (
        path / "hermes_constants.py"
    ).is_file()


def resolve_hermes_agent_root() -> Path:
    """Locate the installed official Hermes Agent without assuming one host layout."""
    configured = os.getenv("HERMES_AGENT_ROOT", "").strip()
    if configured:
        root = Path(configured).expanduser().resolve()
        if not _is_hermes_agent_root(root):
            raise RuntimeError(
                "HERMES_AGENT_ROOT does not contain the official Hermes Weixin adapter"
            )
        return root

    candidates = (
        Path.home() / ".hermes" / "hermes-agent",
        Path("/home/ubuntu/.hermes/hermes-agent"),
    )
    for candidate in candidates:
        root = candidate.expanduser().resolve()
        if _is_hermes_agent_root(root):
            return root
    raise RuntimeError(
        "Hermes official Weixin adapter is unavailable; install Hermes Agent or set "
        "HERMES_AGENT_ROOT"
    )


def install_hermes_agent_import_path() -> Path:
    root = resolve_hermes_agent_root()
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    return root
