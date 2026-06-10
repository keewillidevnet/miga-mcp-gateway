"""Tests for the dirctl-based AGNTCY DirectoryClient.

The real directory (dir-apiserver gRPC + zot OCI + postgres) cannot run in CI or
the dev sandbox, so the `dirctl` subprocess is mocked here. A live end-to-end test
is gated behind MIGA_DIRECTORY_LIVE and skipped by default. These tests lock in the
two things that matter regardless of the live API: CID parsing and the best-effort /
standalone fallback (routing must never depend on the directory).
"""

from __future__ import annotations

import os

import pytest

from miga_shared.agntcy import DirectoryClient, DirectoryError

RECORD = {"name": "Cisco ThousandEyes MCP Server", "schema_version": "1.0.0", "skills": []}


def _client_with_run(monkeypatch, *, rc=0, out="", err="", raise_exc=None):
    c = DirectoryClient(addr="agntcy-directory:8888", dirctl_bin="dirctl")

    async def fake_run(args, stdin=None):
        if raise_exc is not None:
            raise raise_exc
        return rc, out, err

    monkeypatch.setattr(c, "_run", fake_run)
    return c


# -- CID parsing (pure) -------------------------------------------------------


class TestParseCid:
    def test_human_format(self):
        assert (
            DirectoryClient._parse_cid("Pushed record with CID baguqeerabc123def456ghi789")
            == "baguqeerabc123def456ghi789"
        )

    def test_json_format(self):
        assert (
            DirectoryClient._parse_cid('{"cid": "sha256:deadbeefcafebabe1234"}')
            == "sha256:deadbeefcafebabe1234"
        )

    def test_fallback_last_token(self):
        assert (
            DirectoryClient._parse_cid("noise\nbaguqeeraXYZ0123456789") == "baguqeeraXYZ0123456789"
        )

    def test_empty(self):
        assert DirectoryClient._parse_cid("") == "unknown"


# -- register_record: success + best-effort fallbacks -------------------------


class TestRegisterRecord:
    @pytest.mark.asyncio
    async def test_success_returns_cid(self, monkeypatch):
        c = _client_with_run(monkeypatch, rc=0, out="Pushed record with CID baguqeeratest0001abcd")
        assert await c.register_record(RECORD) == "baguqeeratest0001abcd"

    @pytest.mark.asyncio
    async def test_dirctl_missing_is_standalone(self, monkeypatch):
        c = _client_with_run(monkeypatch, raise_exc=FileNotFoundError("dirctl"))
        assert await c.register_record(RECORD) == "standalone"

    @pytest.mark.asyncio
    async def test_timeout_is_standalone(self, monkeypatch):
        c = _client_with_run(monkeypatch, raise_exc=DirectoryError("timed out"))
        assert await c.register_record(RECORD) == "standalone"

    @pytest.mark.asyncio
    async def test_connection_refused_is_standalone(self, monkeypatch):
        c = _client_with_run(
            monkeypatch, rc=1, err="rpc error: connection refused dialing 127.0.0.1:8888"
        )
        assert await c.register_record(RECORD) == "standalone"

    @pytest.mark.asyncio
    async def test_validation_error_is_error(self, monkeypatch):
        c = _client_with_run(monkeypatch, rc=1, err="record validation failed: bad skill id")
        assert await c.register_record(RECORD) == "error"


# -- other ops ----------------------------------------------------------------


class TestOtherOps:
    @pytest.mark.asyncio
    async def test_discover_is_best_effort_empty(self, monkeypatch):
        c = _client_with_run(monkeypatch, raise_exc=FileNotFoundError("dirctl"))
        assert await c.discover(skills=["x"]) == []

    @pytest.mark.asyncio
    async def test_pull_parses_json(self, monkeypatch):
        c = _client_with_run(monkeypatch, rc=0, out='{"name": "x", "schema_version": "1.0.0"}')
        rec = await c.pull("baguqeera123")
        assert rec and rec["schema_version"] == "1.0.0"

    @pytest.mark.asyncio
    async def test_pull_missing_returns_none(self, monkeypatch):
        c = _client_with_run(monkeypatch, rc=1, err="not found")
        assert await c.pull("nope") is None

    @pytest.mark.asyncio
    async def test_deregister(self, monkeypatch):
        c = _client_with_run(monkeypatch, rc=0)
        assert await c.deregister("baguqeera123") is True

    @pytest.mark.asyncio
    async def test_health_false_when_dirctl_absent(self, monkeypatch):
        import miga_shared.agntcy as a

        monkeypatch.setattr(a.shutil, "which", lambda _b: None)
        c = DirectoryClient(dirctl_bin="dirctl")
        assert await c.health() is False

    def test_default_addr_is_grpc_not_http(self):
        c = DirectoryClient()
        assert c.addr == "agntcy-directory:8888"
        assert "http" not in c.addr  # gRPC host:port, not a REST URL


# -- live integration (opt-in only) -------------------------------------------


@pytest.mark.skipif(
    os.getenv("MIGA_DIRECTORY_LIVE") != "1",
    reason="requires a live AGNTCY Directory; set MIGA_DIRECTORY_LIVE=1 to run",
)
@pytest.mark.asyncio
async def test_live_push_roundtrip():  # pragma: no cover - opt-in, needs real stack
    c = DirectoryClient()
    cid = await c.register_record(RECORD)
    assert cid not in ("standalone", "error", "unknown")
    pulled = await c.pull(cid)
    assert pulled is not None
