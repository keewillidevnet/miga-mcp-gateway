"""Tests for directory-search discovery routing (mocked at the boundary; no SDK/network).

Covers: RoutingTable.discovered_servers_for_role resolution/dedupe/role-filter and
fallback signaling; the _fan_out gate ON (uses discovered servers) and OFF (unchanged).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import packages.gateway.server as gw
from miga_shared.models import MIGARole
from miga_shared.registry import load_registry


@pytest.fixture()
def loaded_routing():
    gw.routing.load_from_registry(load_registry())
    return gw.routing


class _FakeDirectory:
    """discover() returns preset result dicts keyed by nothing (skills ignored)."""

    def __init__(self, results):
        self._results = results
        self.calls = 0

    async def discover(self, skills=None, limit=50):
        self.calls += 1
        return list(self._results)


def _result(ref):
    return {
        "cid": f"cid-{ref}",
        "record": {"annotations": {"miga_registry_ref": ref}},
        "registry_ref": ref,
    }


class TestDiscoveredServersForRole:
    @pytest.mark.asyncio
    async def test_resolves_refs_to_specs(self, loaded_routing):
        # observability is served by thousandeyes, splunk, meraki, catalyst_center, infer
        directory = _FakeDirectory([_result("thousandeyes"), _result("splunk")])
        role_skills = {"observability": ["evaluation_monitoring/performance_monitoring"]}
        specs = await loaded_routing.discovered_servers_for_role(
            MIGARole.OBSERVABILITY, directory, role_skills
        )
        assert specs is not None
        assert {s.name for s in specs} == {"thousandeyes", "splunk"}

    @pytest.mark.asyncio
    async def test_dedupes_and_role_filters(self, loaded_routing):
        # duplicate ref + a ref whose server does NOT serve identity (thousandeyes)
        directory = _FakeDirectory([_result("ise"), _result("ise"), _result("thousandeyes")])
        role_skills = {"identity": ["governance_compliance/risk_classification"]}
        specs = await loaded_routing.discovered_servers_for_role(
            MIGARole.IDENTITY, directory, role_skills
        )
        assert [s.name for s in specs] == ["ise"]  # deduped; thousandeyes filtered (not identity)

    @pytest.mark.asyncio
    async def test_empty_discovery_returns_none(self, loaded_routing):
        directory = _FakeDirectory([])
        role_skills = {"observability": ["evaluation_monitoring/performance_monitoring"]}
        assert (
            await loaded_routing.discovered_servers_for_role(
                MIGARole.OBSERVABILITY, directory, role_skills
            )
            is None
        )

    @pytest.mark.asyncio
    async def test_no_skills_returns_none_without_calling(self, loaded_routing):
        directory = _FakeDirectory([_result("thousandeyes")])
        assert (
            await loaded_routing.discovered_servers_for_role(MIGARole.OBSERVABILITY, directory, {})
            is None
        )
        assert directory.calls == 0

    @pytest.mark.asyncio
    async def test_unknown_ref_skipped(self, loaded_routing):
        directory = _FakeDirectory([_result("does_not_exist"), _result("splunk")])
        role_skills = {"security": ["security_privacy/threat_detection"]}
        specs = await loaded_routing.discovered_servers_for_role(
            MIGARole.SECURITY, directory, role_skills
        )
        assert [s.name for s in specs] == ["splunk"]


class _FakePool:
    async def list_tools(self, spec):
        return [{"name": f"{spec.name}_health", "description": ""}]

    async def call_tool(self, spec, tool, args):
        return f"{spec.name}:ok"


def _ctx_with(directory, role_skills):
    return SimpleNamespace(
        request_context=SimpleNamespace(
            lifespan_context={"directory": directory, "role_skills": role_skills}
        )
    )


class TestFanOutGate:
    @pytest.mark.asyncio
    async def test_flag_on_uses_discovered_servers(self, loaded_routing, monkeypatch):
        monkeypatch.setenv("MIGA_DISCOVERY_ROUTING", "1")
        monkeypatch.setattr(gw, "pool", _FakePool())
        directory = _FakeDirectory([_result("splunk")])  # only splunk discovered
        ctx = _ctx_with(directory, {"security": ["security_privacy/threat_detection"]})
        out = await gw._fan_out(MIGARole.SECURITY, gw.RoleQueryInput(), ctx)
        assert directory.calls == 1
        assert "Splunk" in out  # discovered server fanned out
        assert "Meraki" not in out  # the other static security server was NOT used

    @pytest.mark.asyncio
    async def test_flag_on_empty_falls_back_to_static(self, loaded_routing, monkeypatch):
        monkeypatch.setenv("MIGA_DISCOVERY_ROUTING", "1")
        monkeypatch.setattr(gw, "pool", _FakePool())
        directory = _FakeDirectory([])  # discovery yields nothing
        ctx = _ctx_with(directory, {"identity": ["governance_compliance/risk_classification"]})
        out = await gw._fan_out(MIGARole.IDENTITY, gw.RoleQueryInput(), ctx)
        # static identity set (ise) used
        assert "Cisco Identity Services Engine" in out

    @pytest.mark.asyncio
    async def test_flag_off_is_static_and_never_searches(self, loaded_routing, monkeypatch):
        monkeypatch.delenv("MIGA_DISCOVERY_ROUTING", raising=False)
        monkeypatch.setattr(gw, "pool", _FakePool())
        directory = _FakeDirectory([_result("splunk")])
        ctx = _ctx_with(directory, {"security": ["security_privacy/threat_detection"]})
        out = await gw._fan_out(MIGARole.SECURITY, gw.RoleQueryInput(), ctx)
        assert directory.calls == 0  # discovery never invoked
        assert "Splunk" in out and "Cisco Meraki" in out  # full static security set


class TestRoleSkillsLoader:
    def test_loads_six_roles(self):
        from miga_shared.role_skills import load_role_skills

        m = load_role_skills()
        assert set(m) == {
            "observability",
            "security",
            "automation",
            "configuration",
            "compliance",
            "identity",
        }
        assert m["observability"]

    def test_missing_file_returns_empty(self):
        from miga_shared.role_skills import load_role_skills

        assert load_role_skills("/nonexistent/role-skills.yaml") == {}
