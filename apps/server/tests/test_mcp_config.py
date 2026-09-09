"""Wave C: Codex 对标 mcp_cmd.rs/mcp_types.rs/agents_md.rs 4用例。"""
from __future__ import annotations

import asyncio
import logging
import pathlib
import sys
import types
from contextlib import asynccontextmanager

import pytest

from app.agents.prompts_loader import load_layered_agents_md
from app.mcp import client as mcp_client


def test_transport_mutual_exclusion_prefers_stdio(caplog):
    cfg = {
        "servers": {
            "mixed": {
                "command": "py",
                "args": ["-m", "app.mcp.servers.calendar"],
                "cwd": "apps/server",
                "url": "http://127.0.0.1:8001/mcp",
                "tools": ["t"],
            }
        }
    }
    with caplog.at_level(logging.WARNING, logger="app.mcp.client"):
        out = mcp_client.validate_mcp_config(cfg)
    mixed = out["servers"]["mixed"]
    # 冲突取 stdio：保留 command/args/cwd，删掉 url
    assert mixed["command"] == "py"
    assert mixed["args"] == ["-m", "app.mcp.servers.calendar"]
    assert mixed["cwd"] == "apps/server"
    assert "url" not in mixed
    assert any("互斥" in r.message for r in caplog.records)


def test_call_timeout_propagated(monkeypatch):
    # 缺省 3.0
    assert mcp_client._get_call_timeout({}) == 3.0
    assert mcp_client._get_call_timeout(None) == 3.0
    assert mcp_client._get_call_timeout({"call_timeout": "bad"}) == 3.0
    # 透传自定义值
    assert mcp_client._get_call_timeout({"call_timeout": 7.5}) == 7.5
    cfg = {"servers": {"s": {"command": "py", "call_timeout": 7.5}}}
    out = mcp_client.validate_mcp_config(cfg)
    assert out["servers"]["s"]["call_timeout"] == 7.5

    # _call_once 用各 server call_timeout：fake SDK 捕获 wait_for timeout
    timeouts: list[float] = []
    orig_wait_for = asyncio.wait_for

    async def spy_wait_for(coro, *, timeout=None):
        timeouts.append(timeout)
        return await orig_wait_for(coro, timeout=timeout)

    class _FakeResult:
        structured_content = {"ok": True}
        is_error = False

    class _FakeSession:
        def __init__(self, *args, **kwargs):
            pass

        async def initialize(self):
            return {}

        async def call_tool(self, name, arguments=None):
            return _FakeResult()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    class _FakeParams:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    @asynccontextmanager
    async def _fake_stdio(params):
        yield (object(), object())

    fake_mcp = types.ModuleType("mcp")
    fake_mcp.ClientSession = _FakeSession  # type: ignore[attr-defined]
    fake_mcp.StdioServerParameters = _FakeParams  # type: ignore[attr-defined]
    fake_stdio_mod = types.ModuleType("mcp.client.stdio")
    fake_stdio_mod.stdio_client = _fake_stdio  # type: ignore[attr-defined]
    fake_stdio_mod.StdioServerParameters = _FakeParams  # type: ignore[attr-defined]
    fake_sess_mod = types.ModuleType("mcp.client.session")
    fake_sess_mod.ClientSession = _FakeSession  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "mcp", fake_mcp)
    monkeypatch.setitem(sys.modules, "mcp.client.stdio", fake_stdio_mod)
    monkeypatch.setitem(sys.modules, "mcp.client.session", fake_sess_mod)
    monkeypatch.setattr(mcp_client.asyncio, "wait_for", spy_wait_for)
    monkeypatch.setitem(
        mcp_client._SERVERS_CFG,
        "__tmp_timeout_srv__",
        {
            "command": "fake-cmd",
            "args": [],
            "tools": [],
            "call_timeout": 7.5,
            "timeout": 10.0,
        },
    )
    try:
        res = asyncio.run(mcp_client._call_once("__tmp_timeout_srv__", "t", {}))
    finally:
        mcp_client._SERVERS_CFG.pop("__tmp_timeout_srv__", None)
    assert res.get("ok") is True
    assert 7.5 in timeouts


def test_plaintext_bearer_token_ignored(monkeypatch, caplog):
    monkeypatch.setenv("WAVEC_TEST_TOKEN", "env-secret")
    cfg = {
        "name": "s",
        "bearer_token": "plaintext-secret",
        "bearer_token_env_var": "WAVEC_TEST_TOKEN",
    }
    with caplog.at_level(logging.WARNING, logger="app.mcp.client"):
        got = mcp_client.resolve_bearer(cfg)
    assert got == "env-secret"
    assert any("明文" in r.message for r in caplog.records)

    # 缺环境变量时返回 None（绝不回退明文）
    monkeypatch.delenv("WAVEC_TEST_TOKEN", raising=False)
    with caplog.at_level(logging.WARNING, logger="app.mcp.client"):
        got2 = mcp_client.resolve_bearer(cfg)
    assert got2 is None


def test_layered_agents_md(tmp_path):
    root = tmp_path / "repo"
    sub = root / "a" / "b"
    sub.mkdir(parents=True)
    (root / "AGENTS.md").write_text("root rules", encoding="utf-8")
    (root / "a" / "AGENTS.md").write_text("middle rules", encoding="utf-8")
    (sub / "AGENTS.md").write_text("leaf rules", encoding="utf-8")

    out = load_layered_agents_md(sub)
    assert "root rules" in out
    assert "middle rules" in out
    assert "leaf rules" in out
    # 来源标注
    assert str(root / "AGENTS.md") in out
    assert str(sub / "AGENTS.md") in out
    # 根在前、叶子在后
    assert out.index("root rules") < out.index("leaf rules")

    # 缺失返回 ""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    assert load_layered_agents_md(empty_dir) == ""

    # 字节预算
    big = "x" * 5000
    (sub / "AGENTS.md").write_text(big, encoding="utf-8")
    small_out = load_layered_agents_md(sub, max_bytes=100)
    assert len(small_out.encode("utf-8")) <= 100 + 256
    assert "source" in small_out
