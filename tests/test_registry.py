"""Tests for the config-driven server registry loader."""

from __future__ import annotations

from pathlib import Path

from miga_shared.registry import (
    DEFAULT_REGISTRY_PATH,
    DEFAULT_SCHEMA_PATH,
    ServerSpec,
    _resolve_env,
    load_registry,
    validate_registry,
)

EXPECTED = {
    "thousandeyes",
    "splunk",
    "meraki",
    "sdwan",
    "catalyst_center",
    "ise",
    "servicenow",
    "netbox",
    "infer",
}


class TestLoadRegistry:
    def test_loads_all_enabled_servers(self):
        specs = load_registry()
        names = {s.name for s in specs}
        assert names == EXPECTED
        assert all(isinstance(s, ServerSpec) for s in specs)

    def test_registry_validates_against_schema(self):
        import yaml

        with open(DEFAULT_REGISTRY_PATH) as fh:
            raw = yaml.safe_load(fh)
        # Should not raise.
        validate_registry(raw, DEFAULT_SCHEMA_PATH)

    def test_no_dropped_platforms_present(self):
        names = {s.name for s in load_registry()}
        for dropped in (
            "appdynamics",
            "nexus_dashboard",
            "hypershield",
            "webex",
            "xdr",
            "security_cloud_control",
        ):
            assert dropped not in names

    def test_every_server_has_oasf_record_file(self):
        root = Path(DEFAULT_REGISTRY_PATH).parent.parent
        for spec in load_registry():
            assert (root / spec.oasf_record).exists(), spec.oasf_record

    def test_transport_types_are_supported(self):
        for spec in load_registry():
            assert spec.transport_type in ("http", "sse", "stdio")

    def test_catalyst_center_uses_ccc_env(self):
        spec = next(s for s in load_registry() if s.name == "catalyst_center")
        assert spec.env_required == ["CCC_HOST", "CCC_USER", "CCC_PWD"]

    def test_servicenow_source_is_chosen_repo(self):
        spec = next(s for s in load_registry() if s.name == "servicenow")
        assert "echelon-ai-labs/servicenow-mcp" in spec.source


class TestEnvResolution:
    def test_resolves_placeholder(self):
        out = _resolve_env(
            "https://${SPLUNK_HOST}:8089/services/mcp", environ={"SPLUNK_HOST": "splunk.local"}
        )
        assert out == "https://splunk.local:8089/services/mcp"

    def test_unset_placeholder_left_literal(self):
        out = _resolve_env("https://${MISSING}/x", environ={})
        assert out == "https://${MISSING}/x"

    def test_splunk_url_resolved_on_load(self):
        specs = load_registry(environ={"SPLUNK_HOST": "splunk.example.net"})
        splunk = next(s for s in specs if s.name == "splunk")
        assert splunk.url == "https://splunk.example.net:8089/services/mcp"


class TestAuthHeaders:
    def test_bearer_header_injected(self):
        spec = next(s for s in load_registry() if s.name == "thousandeyes")
        headers = spec.auth_headers(environ={"TE_TOKEN": "secret-token"})
        assert headers["Authorization"] == "Bearer secret-token"

    def test_no_header_when_token_unset(self):
        spec = next(s for s in load_registry() if s.name == "thousandeyes")
        headers = spec.auth_headers(environ={})
        assert "Authorization" not in headers


class TestMissingEnv:
    def test_reports_missing(self):
        spec = next(s for s in load_registry() if s.name == "meraki")
        missing = spec.missing_env(environ={})
        assert "MERAKI_API_KEY" in missing and "MERAKI_ORG_ID" in missing

    def test_none_missing_when_present(self):
        spec = next(s for s in load_registry() if s.name == "meraki")
        env = {"MERAKI_API_KEY": "k", "MERAKI_ORG_ID": "o"}
        assert spec.missing_env(environ=env) == []
