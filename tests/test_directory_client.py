"""Tests for the agntcy-dir SDK-based DirectoryClient.

The real SDK (agntcy-dir, from the buf.build index) and a live directory cannot run
in CI or the sandbox, so the SDK ``Client`` is mocked at the boundary (we never import
the real SDK here). These lock in the two things that matter regardless of the exact
SDK surface: the structured CID is read from the RecordRef (no string scraping), and
the best-effort / standalone fallback holds (routing never depends on the directory).
A live roundtrip is gated behind MIGA_DIRECTORY_LIVE and skipped by default.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from miga_shared.agntcy import DirectoryClient

RECORD = {"name": "Cisco ThousandEyes MCP Server", "schema_version": "1.0.0", "skills": []}


class _FakeRef:
    def __init__(self, cid):
        self.cid = cid


class _FakeClient:
    """Stand-in for agntcy.dir_sdk.client.Client."""

    def __init__(self, *, push_result=None, push_exc=None):
        self._push_result = push_result
        self._push_exc = push_exc
        self.closed = False

    def push(self, record):
        if self._push_exc is not None:
            raise self._push_exc
        return self._push_result

    def close(self):
        self.closed = True


def _client(monkeypatch, fake):
    c = DirectoryClient(addr="agntcy-directory:8888")
    monkeypatch.setattr(c, "_sdk", lambda: fake)
    # bypass the real protobuf/SDK model construction in _to_record
    monkeypatch.setattr(c, "_to_record", lambda d: d)
    return c


# -- structured CID extraction (no string scraping) --------------------------


class TestCidExtraction:
    def test_old_string_parser_is_gone(self):
        assert not hasattr(DirectoryClient, "_parse_cid")

    def test_cid_attr(self):
        assert DirectoryClient._cid_of(_FakeRef("baguqeera0001")) == "baguqeera0001"

    def test_getcid_method(self):
        ref = SimpleNamespace(GetCid=lambda: "sha256:abc123")
        assert DirectoryClient._cid_of(ref) == "sha256:abc123"

    def test_unknown(self):
        assert DirectoryClient._cid_of(SimpleNamespace()) == "unknown"


class TestResolve:
    def test_prefers_lowercase_then_pascal(self):
        pushed = []
        c = SimpleNamespace(Push=lambda r: pushed.append(r))
        resolved = DirectoryClient._resolve(c, ("push", "Push"))
        assert resolved is c.Push  # found "Push" since "push" is absent

    def test_raises_when_absent(self):
        with pytest.raises(AttributeError):
            DirectoryClient._resolve(SimpleNamespace(), ("push", "Push"))


# -- register_record: success + best-effort fallbacks ------------------------


class TestRegisterRecord:
    @pytest.mark.asyncio
    async def test_success_returns_structured_cid(self, monkeypatch):
        c = _client(monkeypatch, _FakeClient(push_result=_FakeRef("baguqeeratest0001")))
        assert await c.register_record(RECORD) == "baguqeeratest0001"

    @pytest.mark.asyncio
    async def test_sdk_not_installed_is_standalone(self, monkeypatch):
        c = DirectoryClient()
        monkeypatch.setattr(c, "_sdk", lambda: None)  # simulates ImportError path
        assert await c.register_record(RECORD) == "standalone"

    @pytest.mark.asyncio
    async def test_unreachable_is_standalone(self, monkeypatch):
        c = _client(
            monkeypatch, _FakeClient(push_exc=RuntimeError("rpc error: connection refused"))
        )
        assert await c.register_record(RECORD) == "standalone"

    @pytest.mark.asyncio
    async def test_validation_error_is_error(self, monkeypatch):
        c = _client(
            monkeypatch, _FakeClient(push_exc=ValueError("record validation failed: bad skill id"))
        )
        assert await c.register_record(RECORD) == "error"

    @pytest.mark.asyncio
    async def test_register_oasfrecord_delegates(self, monkeypatch):
        from miga_shared.agntcy import OASFRecord

        c = _client(monkeypatch, _FakeClient(push_result=_FakeRef("baguqeeraXYZ")))
        assert await c.register(OASFRecord(name="infer_mcp")) == "baguqeeraXYZ"


# -- best-effort safety on the other ops -------------------------------------


class TestBestEffortOps:
    @pytest.mark.asyncio
    async def test_pull_none_when_unavailable(self, monkeypatch):
        c = DirectoryClient()
        monkeypatch.setattr(c, "_sdk", lambda: None)
        assert await c.pull("baguqeera0001") is None

    @pytest.mark.asyncio
    async def test_discover_empty_when_unavailable(self, monkeypatch):
        c = DirectoryClient()
        monkeypatch.setattr(c, "_sdk", lambda: None)
        assert await c.discover(skills=["x"]) == []

    @pytest.mark.asyncio
    async def test_deregister_false_when_unavailable(self, monkeypatch):
        c = DirectoryClient()
        monkeypatch.setattr(c, "_sdk", lambda: None)
        assert await c.deregister("baguqeera0001") is False

    @pytest.mark.asyncio
    async def test_health_false_when_sdk_absent(self, monkeypatch):
        c = DirectoryClient()
        monkeypatch.setattr(c, "_sdk", lambda: None)
        assert await c.health() is False

    @pytest.mark.asyncio
    async def test_health_true_when_sdk_present(self, monkeypatch):
        c = DirectoryClient()
        monkeypatch.setattr(c, "_sdk", lambda: _FakeClient())
        assert await c.health() is True

    def test_default_addr_is_grpc_not_http(self):
        c = DirectoryClient()
        assert c.addr == "agntcy-directory:8888" and "http" not in c.addr


# -- live integration (opt-in only) ------------------------------------------


@pytest.mark.skipif(
    os.getenv("MIGA_DIRECTORY_LIVE") != "1",
    reason="requires a live AGNTCY Directory + agntcy-dir SDK; set MIGA_DIRECTORY_LIVE=1",
)
@pytest.mark.asyncio
async def test_live_push_roundtrip():  # pragma: no cover - opt-in, needs real stack
    c = DirectoryClient()
    cid = await c.register_record(RECORD)
    assert cid not in ("standalone", "error", "unknown")
    assert await c.pull(cid) is not None
