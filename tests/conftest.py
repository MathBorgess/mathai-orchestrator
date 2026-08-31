from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
FAKE_CLAUDE = REPO / "tests" / "fakes" / "claude"


@pytest.fixture
def repo_root() -> Path:
    return REPO


@pytest.fixture
def fake_claude() -> Path:
    mode = FAKE_CLAUDE.stat().st_mode
    FAKE_CLAUDE.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return FAKE_CLAUDE


@pytest.fixture
def claude_env(fake_claude: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("CLAUDE_BIN", str(fake_claude))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return fake_claude


@pytest.fixture
def session_dir(tmp_path: Path) -> Path:
    return tmp_path / "session"
