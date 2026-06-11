"""Tests for the WebEx bot gateway-call path and intent routing (mocked; no network/SDK)."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

import packages.webex_bot.app as app
from packages.webex_bot.nlp import IntentCategory


class TestExtractText:
    def test_objects_with_text(self):
        blocks = [SimpleNamespace(text="a"), SimpleNamespace(text="b")]
        assert app._extract_text(blocks) == "a\nb"

    def test_dict_blocks(self):
        blocks = [{"type": "text", "text": "x"}, {"type": "image", "data": "..."}]
        assert app._extract_text(blocks) == "x"

    def test_empty(self):
        assert app._extract_text(None) == ""


class TestCallGatewayDispatch:
    @pytest.mark.asyncio
    async def test_mcp_mode_is_default(self, monkeypatch):
        monkeypatch.setattr(app, "GATEWAY_MODE", "mcp")

        async def fake_mcp(tool, args):
            return f"MCP:{tool}"

        monkeypatch.setattr(app, "_call_gateway_mcp", fake_mcp)
        assert await app.call_gateway("network_status") == "MCP:network_status"

    @pytest.mark.asyncio
    async def test_http_mode_selected(self, monkeypatch):
        monkeypatch.setattr(app, "GATEWAY_MODE", "http")

        async def fake_http(tool, args):
            return f"HTTP:{tool}"

        monkeypatch.setattr(app, "_call_gateway_http", fake_http)
        assert await app.call_gateway("gateway_health") == "HTTP:gateway_health"

    @pytest.mark.asyncio
    async def test_unreachable_is_friendly_not_raised(self, monkeypatch):
        monkeypatch.setattr(app, "GATEWAY_MODE", "mcp")

        async def boom(tool, args):
            raise httpx.ConnectError("no route")

        monkeypatch.setattr(app, "_call_gateway_mcp", boom)
        out = await app.call_gateway("observability", {"platforms": ["infer"]})
        assert "unreachable" in out.lower()

    @pytest.mark.asyncio
    async def test_generic_error_is_friendly(self, monkeypatch):
        monkeypatch.setattr(app, "GATEWAY_MODE", "mcp")

        async def boom(tool, args):
            raise RuntimeError("handshake failed")

        monkeypatch.setattr(app, "_call_gateway_mcp", boom)
        out = await app.call_gateway("security")
        assert "error communicating" in out.lower()


class TestHttpFallbackParsing:
    @pytest.mark.asyncio
    async def test_parses_internal_call_content(self, monkeypatch):
        class _Resp:
            def raise_for_status(self):
                return None

            def json(self):
                return {"content": [{"type": "text", "text": "## Health: ok"}]}

        async def fake_post(url, json=None):
            assert url.endswith("/internal/call")
            assert json["tool"] == "gateway_health"
            return _Resp()

        monkeypatch.setattr(app.http_client, "post", fake_post)
        assert await app._call_gateway_http("gateway_health", {}) == "## Health: ok"


class TestGatewayHealthPhrasing:
    @pytest.mark.parametrize(
        "text", ["gateway health", "Gateway Status", "miga status", "are you up?"]
    )
    def test_matches(self, text):
        assert app._is_gateway_health_query(text) is True

    @pytest.mark.parametrize("text", ["network status", "risk score", "help"])
    def test_non_matches(self, text):
        assert app._is_gateway_health_query(text) is False


class TestIntentToTool:
    def test_six_roles_plus_status(self):
        m = app.INTENT_TO_TOOL
        assert m[IntentCategory.OBSERVABILITY] == "observability"
        assert m[IntentCategory.SECURITY] == "security"
        assert m[IntentCategory.AUTOMATION] == "automation"
        assert m[IntentCategory.CONFIGURATION] == "configuration"
        assert m[IntentCategory.COMPLIANCE] == "compliance"
        assert m[IntentCategory.IDENTITY] == "identity"
        assert m[IntentCategory.STATUS] == "network_status"
