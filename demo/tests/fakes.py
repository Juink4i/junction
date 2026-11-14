"""Pytest fixtures shared by agent/, web/ and demo/ tests: a running fake trade server."""

from __future__ import annotations

import pytest

from demo import fake_server
from demo.servers import run_in_thread


@pytest.fixture(scope="session")
def _fake_running():
    running = run_in_thread(fake_server.app())
    yield running
    running.stop()


@pytest.fixture
def fake(_fake_running, tmp_path, monkeypatch):
    """A clean fake server. `fake.mcp_url`, `fake.base_url`, `fake.overrides` (a writable path)."""
    fake_server.STATE.reset()
    overrides = tmp_path / "overrides.json"
    monkeypatch.setattr(fake_server, "OVERRIDES_FILE", overrides)

    class Handle:
        base_url = _fake_running.base_url
        mcp_url = f"{_fake_running.base_url}/mcp"
        state = fake_server.STATE

    Handle.overrides = overrides
    return Handle
