"""Tests for the agntcy-dir SDK (1.3.0) based DirectoryClient.

The real SDK and a live directory cannot run in CI / the sandbox, so the SDK is
mocked at the boundary (the real SDK is never imported here). These lock in the
1.3.0 surface MIGA depends on — push is list-in/list-out, the CID comes from
RecordRef.cid, and the OASF record is carried in Record.data — plus the best-effort
standalone fallback (routing never depends on the directory). A live roundtrip is
gated behind MIGA_DIRECTORY_LIVE and skipped by default.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

import miga_shared.agntcy as agntcy
from miga_shared.agntcy import DirectoryClient

RECORD = {"name": "Cisco ThousandEyes MCP Server", "schema_version": "1.0.0", "skills": []}


class _FakeClient:
    """Mimics the 1.3.0 Client: push/pull take LISTS and return LISTS; delete -> None."""

    def __init__(self, *, push_refs=None, push_exc=None, pull_recs=None):
        self._push_refs = push_refs if push_refs is not None else []
        self._push_exc = push_exc
        self._pull_recs = pull_recs if pull_recs is not None else []
        self.deleted: list = []

    def push(self, records):
        assert isinstance(records, list)  # list-in
        if self._push_exc is not None:
            raise self._push_exc
        return self._push_refs  # list-out

    def pull(self, refs):
        assert isinstance(refs, list)
        return self._pull_recs

    def delete(self, refs):
        assert isinstance(refs, list)
        self.deleted.extend(refs)
        return None


def _ready_client(monkeypatch, fake):
    """A DirectoryClient wired to a fake SDK client, with the SDK marked available and
    record construction bypassed (so no real protobuf/SDK objects are needed)."""
    monkeypatch.setattr(agntcy, "_SDK_AVAILABLE", True)
    c = DirectoryClient(addr="agntcy-directory:8888")
    monkeypatch.setattr(c, "_sdk", lambda: fake)
    monkeypatch.setattr(c, "_to_record", lambda d: d)  # bypass Struct/ParseDict/core_v1
    return c


# -- register_record: list-in/list-out + structured CID ----------------------


class TestRegisterRecord:
    @pytest.mark.asyncio
    async def test_success_reads_first_recordref_cid(self, monkeypatch):
        fake = _FakeClient(push_refs=[SimpleNamespace(cid="baguqeeratest0001")])
        c = _ready_client(monkeypatch, fake)
        assert await c.register_record(RECORD) == "baguqeeratest0001"

    @pytest.mark.asyncio
    async def test_empty_refs_is_error(self, monkeypatch):
        c = _ready_client(monkeypatch, _FakeClient(push_refs=[]))
        assert await c.register_record(RECORD) == "error"

    @pytest.mark.asyncio
    async def test_unreachable_is_standalone(self, monkeypatch):
        c = _ready_client(
            monkeypatch, _FakeClient(push_exc=RuntimeError("rpc error: connection refused"))
        )
        assert await c.register_record(RECORD) == "standalone"

    @pytest.mark.asyncio
    async def test_validation_error_is_error(self, monkeypatch):
        c = _ready_client(monkeypatch, _FakeClient(push_exc=ValueError("record validation failed")))
        assert await c.register_record(RECORD) == "error"

    @pytest.mark.asyncio
    async def test_register_oasfrecord_delegates(self, monkeypatch):
        from miga_shared.agntcy import OASFRecord

        fake = _FakeClient(push_refs=[SimpleNamespace(cid="baguqeeraXYZ")])
        c = _ready_client(monkeypatch, fake)
        assert await c.register(OASFRecord(name="infer_mcp")) == "baguqeeraXYZ"


# -- pull / delete via list APIs ---------------------------------------------


class TestPullDelete:
    @pytest.mark.asyncio
    async def test_pull_returns_record_data_dict(self, monkeypatch):
        rec = SimpleNamespace(data={"schema_version": "1.0.0", "name": "x"})
        c = _ready_client(monkeypatch, _FakeClient(pull_recs=[rec]))
        # Record.data is a protobuf Struct in reality; MessageToDict converts it.
        monkeypatch.setattr(agntcy, "MessageToDict", lambda d, **k: d)
        monkeypatch.setattr(
            agntcy, "core_v1", SimpleNamespace(RecordRef=lambda cid: SimpleNamespace(cid=cid))
        )
        out = await c.pull("baguqeera0001")
        assert out and out["schema_version"] == "1.0.0"

    @pytest.mark.asyncio
    async def test_pull_empty_list_returns_none(self, monkeypatch):
        c = _ready_client(monkeypatch, _FakeClient(pull_recs=[]))
        monkeypatch.setattr(
            agntcy, "core_v1", SimpleNamespace(RecordRef=lambda cid: SimpleNamespace(cid=cid))
        )
        assert await c.pull("nope") is None

    @pytest.mark.asyncio
    async def test_deregister_calls_delete_with_list(self, monkeypatch):
        fake = _FakeClient()
        c = _ready_client(monkeypatch, fake)
        monkeypatch.setattr(
            agntcy, "core_v1", SimpleNamespace(RecordRef=lambda cid: SimpleNamespace(cid=cid))
        )
        assert await c.deregister("baguqeera0001") is True
        assert len(fake.deleted) == 1 and fake.deleted[0].cid == "baguqeera0001"


# -- SDK-absent standalone path (the sandbox's natural state) -----------------


class TestSdkAbsentStandalone:
    @pytest.mark.asyncio
    async def test_register_record_standalone(self, monkeypatch):
        monkeypatch.setattr(agntcy, "_SDK_AVAILABLE", False)
        assert await DirectoryClient().register_record(RECORD) == "standalone"

    @pytest.mark.asyncio
    async def test_pull_none(self, monkeypatch):
        monkeypatch.setattr(agntcy, "_SDK_AVAILABLE", False)
        assert await DirectoryClient().pull("x") is None

    @pytest.mark.asyncio
    async def test_deregister_false(self, monkeypatch):
        monkeypatch.setattr(agntcy, "_SDK_AVAILABLE", False)
        assert await DirectoryClient().deregister("x") is False

    @pytest.mark.asyncio
    async def test_health_false(self, monkeypatch):
        monkeypatch.setattr(agntcy, "_SDK_AVAILABLE", False)
        assert await DirectoryClient().health() is False

    @pytest.mark.asyncio
    async def test_discover_empty(self, monkeypatch):
        monkeypatch.setattr(agntcy, "_SDK_AVAILABLE", False)
        assert await DirectoryClient().discover(skills=["x"]) == []


class TestHealthReady:
    @pytest.mark.asyncio
    async def test_health_true_when_client_constructs(self, monkeypatch):
        monkeypatch.setattr(agntcy, "_SDK_AVAILABLE", True)
        c = DirectoryClient()
        monkeypatch.setattr(c, "_sdk", lambda: _FakeClient())
        assert await c.health() is True

    def test_default_addr_is_grpc_not_http(self):
        c = DirectoryClient()
        assert c.addr == "agntcy-directory:8888" and "http" not in c.addr

    def test_old_string_parser_is_gone(self):
        assert not hasattr(DirectoryClient, "_parse_cid")


class TestFallbackLogging:
    @pytest.mark.asyncio
    async def test_unreachable_push_logs_warning_with_exc_and_kind(self, monkeypatch, caplog):
        import logging

        c = _ready_client(
            monkeypatch, _FakeClient(push_exc=RuntimeError("rpc error: connection refused"))
        )
        with caplog.at_level(logging.WARNING, logger="miga.agntcy"):
            res = await c.register_record(RECORD)
        assert res == "standalone"
        msgs = [r.getMessage() for r in caplog.records]
        assert any(
            "directory push failed" in m and "connection refused" in m and "unreachable" in m
            for m in msgs
        ), msgs

    @pytest.mark.asyncio
    async def test_rejected_push_logs_rejected_and_returns_error(self, monkeypatch, caplog):
        import logging

        class _RejectedError(Exception):
            def code(self):
                return SimpleNamespace(name="INVALID_ARGUMENT")

        fake = _FakeClient(push_exc=_RejectedError("record validation failed"))
        c = _ready_client(monkeypatch, fake)
        with caplog.at_level(logging.WARNING, logger="miga.agntcy"):
            res = await c.register_record(RECORD)
        # A REJECTED record must NOT be masked as a down directory:
        assert res == "error"
        assert any(
            "directory push failed" in r.getMessage() and "rejected" in r.getMessage()
            for r in caplog.records
        )

    @pytest.mark.asyncio
    async def test_pull_failure_logs_warning(self, monkeypatch, caplog):
        import logging

        monkeypatch.setattr(agntcy, "_SDK_AVAILABLE", True)
        c = DirectoryClient()

        class _Boom:
            def pull(self, refs):
                raise RuntimeError("connection refused")

        monkeypatch.setattr(c, "_sdk", lambda: _Boom())
        monkeypatch.setattr(
            agntcy, "core_v1", SimpleNamespace(RecordRef=lambda cid: SimpleNamespace(cid=cid))
        )
        with caplog.at_level(logging.WARNING, logger="miga.agntcy"):
            assert await c.pull("baguqeera0001") is None
        assert any("directory pull failed" in r.getMessage() for r in caplog.records)


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
