"""Tests for the registry-driven gateway routing and fan-out.

The downstream MCP client transport is mocked via a fake pool — no live servers
or credentials are required.
"""

from __future__ import annotations

import pytest

import packages.gateway.server as gw
from miga_shared.models import MIGARole
from miga_shared.registry import load_registry
from packages.gateway.server import RoleQueryInput, _fan_out


@pytest.fixture()
def loaded_routing():
    gw.routing.load_from_registry(load_registry())
    return gw.routing


class FakePool:
    """Stand-in for MCPClientPool with deterministic tools/results."""

    def __init__(self, tools_by_server=None, results=None, unreachable=()):
        self._tools = tools_by_server or {}
        self._results = results or {}
        self._unreachable = set(unreachable)

    async def list_tools(self, spec):
        if spec.name in self._unreachable:
            from miga_shared.transport import MCPTransportError

            raise MCPTransportError(f"{spec.name} down")
        return [
            {"name": n, "description": ""}
            for n in self._tools.get(spec.name, [f"{spec.name}_health"])
        ]

    async def call_tool(self, spec, tool_name, arguments):
        return self._results.get((spec.name, tool_name), f"{spec.name}:{tool_name}:ok")

    async def close(self):
        return None


class TestRoutingTable:
    def test_roles_mapped(self, loaded_routing):
        obs = {s.name for s in loaded_routing.servers_for_role(MIGARole.OBSERVABILITY)}
        assert {"thousandeyes", "splunk", "meraki", "catalyst_center", "infer"} <= obs
        ident = {s.name for s in loaded_routing.servers_for_role(MIGARole.IDENTITY)}
        assert ident == {"ise"}

    def test_get_and_all(self, loaded_routing):
        assert loaded_routing.get("netbox").display_name.startswith("NetBox")
        assert len(loaded_routing.all()) == 9

    def test_dropped_platforms_absent(self, loaded_routing):
        all_names = set(loaded_routing.all())
        assert not ({"xdr", "hypershield", "webex"} & all_names)


class TestFanOut:
    @pytest.mark.asyncio
    async def test_summary_sweep_aggregates(self, loaded_routing, monkeypatch):
        monkeypatch.setattr(gw, "pool", FakePool())
        out = await _fan_out(MIGARole.IDENTITY, RoleQueryInput(), None)
        assert "Cisco Identity Services Engine" in out

    @pytest.mark.asyncio
    async def test_named_tool_dispatch(self, loaded_routing, monkeypatch):
        pool = FakePool(
            tools_by_server={"netbox": ["get_objects", "get_changelogs"]},
            results={("netbox", "get_objects"): "device list"},
        )
        monkeypatch.setattr(gw, "pool", pool)
        params = RoleQueryInput(tool_name="get_objects", platforms=["netbox"], arguments={})
        out = await _fan_out(MIGARole.CONFIGURATION, params, None)
        assert "device list" in out

    @pytest.mark.asyncio
    async def test_unknown_tool_reported(self, loaded_routing, monkeypatch):
        monkeypatch.setattr(gw, "pool", FakePool(tools_by_server={"netbox": ["get_objects"]}))
        params = RoleQueryInput(tool_name="does_not_exist", platforms=["netbox"])
        out = await _fan_out(MIGARole.CONFIGURATION, params, None)
        assert "not found" in out.lower()

    @pytest.mark.asyncio
    async def test_no_servers_for_filtered_role(self, loaded_routing, monkeypatch):
        monkeypatch.setattr(gw, "pool", FakePool())
        params = RoleQueryInput(platforms=["nonexistent"])
        out = await _fan_out(MIGARole.SECURITY, params, None)
        assert "No servers registered" in out

    @pytest.mark.asyncio
    async def test_unreachable_server_marked(self, loaded_routing, monkeypatch):
        monkeypatch.setattr(gw, "pool", FakePool(unreachable=["ise"]))
        out = await _fan_out(MIGARole.IDENTITY, RoleQueryInput(), None)
        assert "unreachable" in out.lower()
