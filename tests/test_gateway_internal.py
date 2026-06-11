"""Tests for the gateway dev-only /internal/call route (mocked mcp.call_tool)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import packages.gateway.server as gw


def _request(host="127.0.0.1", body=None):
    async def _json():
        if body is None:
            raise ValueError("no body")
        return body

    return SimpleNamespace(client=SimpleNamespace(host=host), json=_json)


class TestSerialize:
    def test_content_blocks(self):
        out = gw._serialize_tool_result([SimpleNamespace(text="hi"), SimpleNamespace(text="there")])
        assert out == [{"type": "text", "text": "hi"}, {"type": "text", "text": "there"}]

    def test_dict_result(self):
        out = gw._serialize_tool_result({"score": 5})
        assert out[0]["type"] == "text" and "score" in out[0]["text"]


class TestInternalCall:
    @pytest.mark.asyncio
    async def test_success(self, monkeypatch):
        monkeypatch.setenv("MIGA_ENV", "development")

        async def fake_call_tool(name, arguments):
            return [SimpleNamespace(text=f"ran {name}")]

        monkeypatch.setattr(gw.mcp, "call_tool", fake_call_tool)
        resp = await gw._internal_call(_request(body={"tool": "gateway_health", "arguments": {}}))
        assert resp.status_code == 200
        assert json.loads(resp.body)["content"][0]["text"] == "ran gateway_health"

    @pytest.mark.asyncio
    async def test_disabled_outside_development(self, monkeypatch):
        monkeypatch.setenv("MIGA_ENV", "production")
        resp = await gw._internal_call(_request(body={"tool": "gateway_health"}))
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_rejects_public_caller(self, monkeypatch):
        monkeypatch.setenv("MIGA_ENV", "development")
        resp = await gw._internal_call(_request(host="8.8.8.8", body={"tool": "gateway_health"}))
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_missing_tool(self, monkeypatch):
        monkeypatch.setenv("MIGA_ENV", "development")
        resp = await gw._internal_call(_request(body={"arguments": {}}))
        assert resp.status_code == 400
