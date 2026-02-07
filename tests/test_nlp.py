"""Tests for WebEx Bot NLP intent recognition."""
from __future__ import annotations

import pytest

from packages.webex_bot.nlp import (
    IntentCategory,
    ParsedIntent,
    format_help,
    recognize_intent,
)


class TestIntentRecognition:
    # -- Status / Health --
    def test_network_status(self):
        intent = recognize_intent("network status")
        assert intent.category == IntentCategory.STATUS
        assert intent.confidence >= 0.9

    def test_how_is_network(self):
        intent = recognize_intent("how's the network?")
        assert intent.category == IntentCategory.STATUS

    def test_is_network_healthy(self):
        intent = recognize_intent("is the network ok?")
        assert intent.category == IntentCategory.STATUS

    # -- Platform-specific observability --
    def test_meraki_health(self):
        intent = recognize_intent("meraki health")
        assert intent.category == IntentCategory.OBSERVABILITY
        assert intent.platform == "meraki"

    def test_catalyst_center_issues(self):
        intent = recognize_intent("catalyst center issues")
        assert intent.category == IntentCategory.OBSERVABILITY
        assert intent.platform == "catalyst_center"

    def test_thousandeyes_status(self):
        intent = recognize_intent("thousandeyes status")
        assert intent.category == IntentCategory.OBSERVABILITY
        assert intent.platform == "thousandeyes"

    def test_wireless_health(self):
        intent = recognize_intent("wireless client health")
        assert intent.category == IntentCategory.OBSERVABILITY

    # -- Security --
    def test_security_events(self):
        intent = recognize_intent("show me security events")
        assert intent.category == IntentCategory.SECURITY

    def test_xdr_threats(self):
        intent = recognize_intent("xdr threat detections")
        assert intent.category == IntentCategory.SECURITY
        assert intent.platform == "xdr"

    def test_malware(self):
        intent = recognize_intent("any malware detections?")
        assert intent.category == IntentCategory.SECURITY

    def test_firewall_rules(self):
        intent = recognize_intent("firewall policy status")
        assert intent.category == IntentCategory.SECURITY
        assert intent.platform == "security_cloud_control"

    def test_hypershield_enforcement(self):
        intent = recognize_intent("hypershield enforcement status")
        assert intent.category == IntentCategory.SECURITY
        assert intent.platform == "hypershield"

    # -- INFER --
    def test_correlation(self):
        intent = recognize_intent("run correlation analysis")
        assert intent.category == IntentCategory.OBSERVABILITY
        assert intent.platform == "infer"

    def test_root_cause(self):
        intent = recognize_intent("root cause analysis")
        assert intent.category == IntentCategory.OBSERVABILITY
        assert intent.platform == "infer"

    def test_anomaly_detection(self):
        intent = recognize_intent("any anomalous patterns?")
        assert intent.category == IntentCategory.OBSERVABILITY
        assert intent.platform == "infer"

    def test_risk_score(self):
        intent = recognize_intent("what's the risk score?")
        assert intent.category == IntentCategory.COMPLIANCE
        assert intent.platform == "infer"

    def test_predict_failures(self):
        intent = recognize_intent("predict any failures?")
        assert intent.category == IntentCategory.OBSERVABILITY
        assert intent.platform == "infer"

    # -- Automation --
    def test_run_command(self):
        intent = recognize_intent("run show version on the switch")
        assert intent.category == IntentCategory.AUTOMATION

    def test_quarantine(self):
        intent = recognize_intent("quarantine endpoint AA:BB:CC:DD:EE:01")
        assert intent.category == IntentCategory.AUTOMATION
        assert intent.platform == "ise"

    # -- Configuration --
    def test_show_config(self):
        intent = recognize_intent("show running configuration")
        assert intent.category == IntentCategory.CONFIGURATION

    def test_list_devices(self):
        intent = recognize_intent("list all devices")
        assert intent.category == IntentCategory.CONFIGURATION

    # -- Compliance --
    def test_compliance(self):
        intent = recognize_intent("compliance posture status")
        assert intent.category == IntentCategory.COMPLIANCE

    def test_certificates(self):
        intent = recognize_intent("check certificate expiry")
        assert intent.category == IntentCategory.COMPLIANCE

    # -- Identity --
    def test_sessions(self):
        intent = recognize_intent("who is authenticated?")
        assert intent.category == IntentCategory.IDENTITY
        assert intent.platform == "ise"

    def test_auth_failures(self):
        intent = recognize_intent("authentication failures")
        assert intent.category == IntentCategory.IDENTITY

    # -- Help --
    def test_help(self):
        intent = recognize_intent("help")
        assert intent.category == IntentCategory.HELP
        assert intent.confidence >= 0.9

    def test_what_can_you_do(self):
        intent = recognize_intent("what can you do?")
        assert intent.category == IntentCategory.HELP

    # -- Unknown --
    def test_completely_unrelated(self):
        intent = recognize_intent("what's the weather today?")
        assert intent.category == IntentCategory.UNKNOWN

    # -- Entity extraction --
    def test_ip_extraction(self):
        intent = recognize_intent("check device 10.1.1.50")
        assert "ip_address" in intent.arguments
        assert "10.1.1.50" in intent.arguments["ip_address"]

    def test_severity_extraction(self):
        intent = recognize_intent("show critical security events")
        assert "severity" in intent.arguments
        assert "critical" in intent.arguments["severity"]

    # -- Help text --
    def test_help_format(self):
        text = format_help()
        assert "MIGA" in text
        assert "Observability" in text
        assert "Security" in text
        assert "help" in text.lower()
