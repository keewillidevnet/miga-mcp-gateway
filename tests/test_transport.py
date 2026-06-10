"""Tests for the MCP client transport abstraction.

Live credentials are never needed — the MCP client transport is mocked, both at
the session level (operation logic) and at the SDK-factory level (transport
selection: HTTP/SSE vs stdio incl. `docker run -i`).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from miga_shared.registry import ServerSpec
from miga_shared.transport import MCPClientPool, MCPTransportError, _normalize_result


def _http_spec(**tweaks):
    t = {"type": "http", "url": "http://meraki-mcp:8000/mcp"}
    t.update(tweaks)
    return ServerSpec(
        name="meraki",
        display_name="Meraki",
        status="community",
        roles=["observability"],
        transport=t,
        oasf_record="x.json",
    )


def _stdio_spec():
    return ServerSpec(
        name="sdwan",
        display_name="SD-WAN",
        status="community",
        roles=["automation"],
        transport={
            "type": "stdio",
            "command": "docker",
            "args": ["run", "-i", "--rm", "catalyst-sdwan-mcp:latest"],
        },
        oasf_record="x.json",
    )


# -- result normalization ----------------------------------------------------


class TestNormalizeResult:
    def test_prefers_structured_content(self):
        r = SimpleNamespace(structuredContent={"ok": True}, content=[], isError=False)
        assert _normalize_result(r) == {"ok": True}

    def test_joins_text_blocks(self):
        r = SimpleNamespace(
            structuredContent=None,
            content=[SimpleNamespace(text="a"), SimpleNamespace(text="b")],
            isError=False,
        )
        assert _normalize_result(r) == "a\nb"

    def test_error_result_raises(self):
        r = SimpleNamespace(
            structuredContent=None, content=[SimpleNamespace(text="boom")], isError=True
        )
        with pytest.raises(MCPTransportError):
            _normalize_result(r)


# -- operations via a mocked session -----------------------------------------


class _FakeSession:
    def __init__(self, tools=None, call_result=None, raise_on_call=False):
        self._tools = tools or []
        self._call_result = call_result
        self._raise = raise_on_call

    async def list_tools(self):
        return SimpleNamespace(tools=[SimpleNamespace(name=n, description="") for n in self._tools])

    async def call_tool(self, name, arguments):
        if self._raise:
            raise RuntimeError("subprocess died")
        return self._call_result


def _patch_session(pool, fake):
    @asynccontextmanager
    async def _fake_session(spec):
        yield fake

    pool._session = _fake_session  # type: ignore[method-assign]


@pytest.mark.asyncio
async def test_list_tools_returns_names():
    pool = MCPClientPool()
    _patch_session(pool, _FakeSession(tools=["meraki_org_overview", "meraki_health"]))
    tools = await pool.list_tools(_http_spec())
    assert {t["name"] for t in tools} == {"meraki_org_overview", "meraki_health"}


@pytest.mark.asyncio
async def test_call_tool_normalizes_text():
    pool = MCPClientPool()
    result = SimpleNamespace(
        structuredContent=None, content=[SimpleNamespace(text="## Health: OK")], isError=False
    )
    _patch_session(pool, _FakeSession(call_result=result))
    out = await pool.call_tool(_http_spec(), "meraki_health", {})
    assert out == "## Health: OK"


@pytest.mark.asyncio
async def test_call_tool_wraps_failures():
    pool = MCPClientPool()
    _patch_session(pool, _FakeSession(raise_on_call=True))
    with pytest.raises(MCPTransportError):
        await pool.call_tool(_stdio_spec(), "anything", {})


# -- transport selection (mock the SDK factories) ----------------------------


@pytest.mark.asyncio
async def test_transport_selection_http_and_stdio(monkeypatch):
    import mcp
    import mcp.client.sse as sse_mod
    import mcp.client.stdio as stdio_mod
    import mcp.client.streamable_http as http_mod

    calls = {}

    @asynccontextmanager
    async def fake_http(url, headers=None):
        calls["http"] = {"url": url, "headers": headers}
        yield (object(), object(), object())

    @asynccontextmanager
    async def fake_stdio(params):
        calls["stdio"] = {"command": params.command, "args": params.args}
        yield (object(), object())

    class FakeClientSession:
        def __init__(self, *a, **k): ...
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def initialize(self):
            return None

        async def list_tools(self):
            return SimpleNamespace(tools=[])

    monkeypatch.setattr(http_mod, "streamablehttp_client", fake_http)
    monkeypatch.setattr(stdio_mod, "stdio_client", fake_stdio)
    monkeypatch.setattr(sse_mod, "sse_client", fake_http)
    monkeypatch.setattr(mcp, "ClientSession", FakeClientSession)

    pool = MCPClientPool(environ={"MERAKI_API_KEY": "k"})
    await pool.list_tools(_http_spec())
    await pool.list_tools(_stdio_spec())

    assert calls["http"]["url"] == "http://meraki-mcp:8000/mcp"
    assert calls["stdio"]["command"] == "docker"
    assert "run" in calls["stdio"]["args"] and "-i" in calls["stdio"]["args"]


@pytest.mark.asyncio
async def test_unsupported_transport_raises():
    pool = MCPClientPool()
    bad = ServerSpec(
        name="x",
        display_name="x",
        status="community",
        roles=["security"],
        transport={"type": "carrier-pigeon"},
        oasf_record="x.json",
    )
    with pytest.raises(MCPTransportError):
        await pool.list_tools(bad)
