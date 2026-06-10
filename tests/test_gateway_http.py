"""Tests for the gateway's cosmetic HTTP/logging fixes (author-only; the live effect
under uvicorn is pending operator re-run on a networked host)."""

from __future__ import annotations

import json
import logging

import pytest

import packages.gateway.server as gw


@pytest.mark.asyncio
async def test_http_health_route_returns_ok():
    # FastMCP serves MCP at /mcp; this lightweight /health backs the container probe.
    resp = await gw._http_health(None)
    assert resp.status_code == 200
    body = json.loads(resp.body)
    assert body["status"] == "ok" and body["service"] == "miga_gateway"


def test_configure_logging_reenables_miga_loggers():
    lg = logging.getLogger("miga")
    lg.disabled = True  # simulate uvicorn disabling existing loggers
    gw._configure_logging()
    assert lg.disabled is False
    assert lg.level == logging.INFO
    assert any(getattr(h, "_miga", False) for h in lg.handlers)


def test_configure_logging_is_idempotent_no_duplicate_handlers():
    gw._configure_logging()
    before = sum(getattr(h, "_miga", False) for h in logging.getLogger("miga").handlers)
    gw._configure_logging()
    after = sum(getattr(h, "_miga", False) for h in logging.getLogger("miga").handlers)
    assert before == after == 1
