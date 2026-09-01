from pathlib import Path

import pytest

from app.hermes_runtime import resolve_hermes_agent_root


def make_runtime(root: Path) -> None:
    adapter = root / "gateway" / "platforms" / "weixin.py"
    adapter.parent.mkdir(parents=True)
    adapter.write_text("", encoding="utf-8")
    (root / "hermes_constants.py").write_text("", encoding="utf-8")


def test_configured_hermes_agent_root_is_used(tmp_path: Path, monkeypatch) -> None:
    make_runtime(tmp_path)
    monkeypatch.setenv("HERMES_AGENT_ROOT", str(tmp_path))

    assert resolve_hermes_agent_root() == tmp_path.resolve()


def test_invalid_configured_hermes_agent_root_fails_closed(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("HERMES_AGENT_ROOT", str(tmp_path))

    with pytest.raises(RuntimeError, match="HERMES_AGENT_ROOT"):
        resolve_hermes_agent_root()
