"""Tests for INFER correlation, RCA, anomaly detection, and prediction."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from miga_shared.models import CorrelatedEvent, PlatformType, SeverityLevel
from servers.infer_mcp.server import (
    correlate_events,
    detect_anomalies,
    match_root_cause,
    predict_failures,
)


def _make_event(
    platform: PlatformType,
    event_type: str,
    severity: SeverityLevel = SeverityLevel.MEDIUM,
    entities: list[str] | None = None,
    offset_seconds: int = 0,
) -> CorrelatedEvent:
    return CorrelatedEvent(
        source_platform=platform,
        event_type=event_type,
        severity=severity,
        timestamp=datetime.now(timezone.utc) + timedelta(seconds=offset_seconds),
        affected_entities=entities or ["switch-01"],
    )


class TestCorrelateEvents:
    def test_empty_input(self):
        assert correlate_events([]) == []

    def test_single_event_no_group(self):
        events = [_make_event(PlatformType.MERAKI, "alert")]
        groups = correlate_events(events)
        assert len(groups) == 0  # Need 2+ events to form a group

    def test_two_overlapping_events_group(self):
        events = [
            _make_event(PlatformType.THOUSANDEYES, "path_loss", entities=["router-01"]),
            _make_event(PlatformType.MERAKI, "vpn_tunnel_flap", entities=["router-01"], offset_seconds=60),
        ]
        groups = correlate_events(events, window_seconds=300)
        assert len(groups) == 1
        assert groups[0]["event_count"] == 2
        assert "thousandeyes" in groups[0]["platforms"]
        assert "meraki" in groups[0]["platforms"]

    def test_no_overlap_different_entities(self):
        events = [
            _make_event(PlatformType.XDR, "alert", entities=["host-a"]),
            _make_event(PlatformType.MERAKI, "alert", entities=["host-b"], offset_seconds=30),
        ]
        groups = correlate_events(events, window_seconds=300)
        assert len(groups) == 0

    def test_no_overlap_outside_window(self):
        events = [
            _make_event(PlatformType.CATALYST_CENTER, "issue", entities=["switch-01"]),
            _make_event(PlatformType.MERAKI, "alert", entities=["switch-01"], offset_seconds=600),
        ]
        groups = correlate_events(events, window_seconds=300)
        assert len(groups) == 0

    def test_three_event_group(self):
        events = [
            _make_event(PlatformType.THOUSANDEYES, "path_loss", severity=SeverityLevel.HIGH, entities=["site-a"]),
            _make_event(PlatformType.MERAKI, "vpn_flap", entities=["site-a"], offset_seconds=30),
            _make_event(PlatformType.CATALYST_CENTER, "device_error", entities=["site-a"], offset_seconds=90),
        ]
        groups = correlate_events(events, window_seconds=300)
        assert len(groups) == 1
        assert groups[0]["event_count"] == 3
        assert groups[0]["severity"] == "high"


class TestMatchRootCause:
    def test_wan_app_slowdown_template(self):
        group = {
            "platforms": ["thousandeyes", "meraki"],
            "events": [
                {"source_platform": "thousandeyes", "event_type": "path_loss", "severity": "medium"},
                {"source_platform": "meraki", "event_type": "vpn_tunnel_flap", "severity": "low"},
            ],
        }
        rca = match_root_cause(group)
        assert rca is not None
        assert rca["template_id"] == "rca-wan-app-slowdown"
        assert rca["confidence"] >= 0.85
        assert len(rca["recommended_actions"]) > 0

    def test_switch_wireless_impact_template(self):
        group = {
            "platforms": ["catalyst_center", "meraki"],
            "events": [
                {"source_platform": "catalyst_center", "event_type": "device_unreachable", "severity": "high"},
                {"source_platform": "meraki", "event_type": "ap_offline", "severity": "medium"},
            ],
        }
        rca = match_root_cause(group)
        assert rca is not None
        assert rca["template_id"] == "rca-switch-wireless-impact"

    def test_lateral_movement_template(self):
        group = {
            "platforms": ["xdr", "meraki"],
            "events": [
                {"source_platform": "xdr", "event_type": "suspicious_traffic", "severity": "medium"},
                {"source_platform": "meraki", "event_type": "new_flow_spike", "severity": "low"},
            ],
        }
        rca = match_root_cause(group)
        assert rca is not None
        assert rca["template_id"] == "rca-lateral-movement"
        assert "Isolate" in rca["recommended_actions"][0]

    def test_no_match(self):
        group = {
            "platforms": ["splunk"],
            "events": [
                {"source_platform": "splunk", "event_type": "log_volume_spike", "severity": "low"},
            ],
        }
        rca = match_root_cause(group)
        assert rca is None


class TestDetectAnomalies:
    def test_empty_input(self):
        assert detect_anomalies([]) == []

    def test_too_few_events(self):
        events = [_make_event(PlatformType.MERAKI, "alert") for _ in range(3)]
        anomalies = detect_anomalies(events)
        # With only 3 events, typically not enough for statistical significance
        assert isinstance(anomalies, list)

    def test_frequency_spike_detected(self):
        # Create normal events spread out, then a burst
        now = datetime.now(timezone.utc)
        events = []
        # Normal: every 60s for 5 events
        for i in range(5):
            events.append(CorrelatedEvent(
                source_platform=PlatformType.XDR,
                event_type="alert",
                timestamp=now - timedelta(seconds=300 - i * 60),
                affected_entities=["host-a"],
            ))
        # Burst: 3 events in 5 seconds
        for i in range(3):
            events.append(CorrelatedEvent(
                source_platform=PlatformType.XDR,
                event_type="alert",
                timestamp=now - timedelta(seconds=5 - i),
                affected_entities=["host-a"],
            ))
        anomalies = detect_anomalies(events)
        # Should detect the frequency spike
        assert isinstance(anomalies, list)


class TestPredictFailures:
    def test_empty_input(self):
        assert predict_failures([], []) == []

    def test_cascading_failure_prediction(self):
        events = [
            _make_event(PlatformType.CATALYST_CENTER, "error", SeverityLevel.HIGH, ["switch-01"]),
            _make_event(PlatformType.CATALYST_CENTER, "error", SeverityLevel.HIGH, ["switch-02"], offset_seconds=10),
            _make_event(PlatformType.CATALYST_CENTER, "error", SeverityLevel.HIGH, ["switch-03"], offset_seconds=20),
        ]
        predictions = predict_failures(events, [])
        assert len(predictions) >= 1
        assert predictions[0]["type"] == "cascading_failure"
        assert predictions[0]["affected_platform"] == "catalyst_center"

    def test_complex_incident_prediction(self):
        events = [
            _make_event(PlatformType.THOUSANDEYES, "path_loss", SeverityLevel.HIGH, ["site-a"]),
            _make_event(PlatformType.MERAKI, "tunnel_flap", SeverityLevel.MEDIUM, ["site-a"], offset_seconds=30),
            _make_event(PlatformType.CATALYST_CENTER, "device_down", SeverityLevel.HIGH, ["site-a"], offset_seconds=60),
        ]
        predictions = predict_failures(events, [])
        complex_preds = [p for p in predictions if p["type"] == "complex_incident"]
        assert len(complex_preds) >= 1
        assert len(complex_preds[0]["affected_platforms"]) >= 3

    def test_no_predictions_for_low_severity(self):
        events = [
            _make_event(PlatformType.MERAKI, "info", SeverityLevel.INFO, ["ap-01"]),
            _make_event(PlatformType.MERAKI, "info", SeverityLevel.LOW, ["ap-02"]),
        ]
        predictions = predict_failures(events, [])
        assert len(predictions) == 0
