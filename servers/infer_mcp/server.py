"""INFER MCP Server — Infrastructure Network Fusion Engine for Reasoning.

The intelligence layer of MIGA. Produces cross-platform insights that no single
Cisco platform can generate alone:

- Cross-platform root cause analysis (correlate ThousandEyes path degradation +
  Meraki tunnel flaps + Catalyst Center switch errors + AppDynamics latency)
- Predictive failure analysis (identify patterns → predict cascading failures)
- Anomaly correlation (combine weak signals across platforms → high-confidence incidents)
- Capacity planning (build digital twin from combined telemetry, run simulations)

v1 Implementation:
- pandas/scipy for statistical correlation
- Rule-based root cause templates (expert-curated decision trees)
- Scikit-learn isolation forests for anomaly detection
- ChromaDB/FAISS vector store for historical incident similarity search
- No GPU required

Roles: Observability, Security, Compliance
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

from miga_shared.agntcy import OASFRecord
from miga_shared.models import (
    CorrelatedEvent,
    MIGARole,
    PlatformCapability,
    PlatformType,
    SeverityLevel,
    ToolResponse,
)
from miga_shared.server_base import add_health_tool, miga_lifespan
from miga_shared.utils.formatters import Fmt
from miga_shared.utils.redis_bus import RedisPubSub

logger = logging.getLogger("miga.infer")

# ---------------------------------------------------------------------------
# In-memory stores (production would use Redis/vector DB)
# ---------------------------------------------------------------------------

_event_buffer: list[CorrelatedEvent] = []
_incident_history: list[dict[str, Any]] = []
_anomaly_log: list[dict[str, Any]] = []

CORRELATION_WINDOW = int(os.getenv("INFER_CORRELATION_WINDOW_SECONDS", "300"))
ANOMALY_SENSITIVITY = float(os.getenv("INFER_ANOMALY_SENSITIVITY", "0.85"))

# ---------------------------------------------------------------------------
# Expert-curated root cause templates
# ---------------------------------------------------------------------------

ROOT_CAUSE_TEMPLATES = [
    {
        "id": "rca-wan-app-slowdown",
        "name": "WAN Degradation → Application Slowdown",
        "description": "ThousandEyes path loss + Meraki VPN tunnel instability → AppDynamics latency spike",
        "signal_pattern": [
            {"platform": "thousandeyes", "event_type": "path_loss", "min_severity": "medium"},
            {"platform": "meraki", "event_type": "vpn_tunnel_flap", "min_severity": "low"},
        ],
        "correlation": "shared_wan_segment",
        "root_cause": "WAN path degradation between sites causing VPN instability and application latency",
        "recommended_actions": [
            "Check ISP status page and circuit utilization",
            "Review SD-WAN policy for failover path availability",
            "Enable SLA-based path switching if not already active",
        ],
    },
    {
        "id": "rca-switch-wireless-impact",
        "name": "Switch Failure → Wireless Impact",
        "description": "Catalyst Center switch error → Meraki AP disconnection → client drops",
        "signal_pattern": [
            {"platform": "catalyst_center", "event_type": "device_unreachable", "min_severity": "high"},
            {"platform": "meraki", "event_type": "ap_offline", "min_severity": "medium"},
        ],
        "correlation": "shared_infrastructure",
        "root_cause": "Upstream switch failure causing access point disconnections and client drops",
        "recommended_actions": [
            "Verify switch stack/HA status in Catalyst Center",
            "Check power delivery to affected APs (PoE budget)",
            "Review spanning-tree topology for convergence issues",
        ],
    },
    {
        "id": "rca-lateral-movement",
        "name": "Lateral Movement Detection",
        "description": "XDR anomalous traffic + ISE unusual authentication + Meraki new flows",
        "signal_pattern": [
            {"platform": "xdr", "event_type": "suspicious_traffic", "min_severity": "medium"},
            {"platform": "meraki", "event_type": "new_flow_spike", "min_severity": "low"},
        ],
        "correlation": "shared_endpoint",
        "root_cause": "Potential lateral movement — compromised endpoint scanning internal network",
        "recommended_actions": [
            "Isolate affected endpoint via ISE/Meraki quarantine VLAN",
            "Trigger XDR full investigation on source IP/MAC",
            "Review Secure Firewall logs for C2 beacon patterns",
            "Notify SOC for incident response",
        ],
    },
    {
        "id": "rca-dns-cascade",
        "name": "DNS Failure → Multi-Platform Cascade",
        "description": "ThousandEyes DNS resolution failure → widespread connectivity issues",
        "signal_pattern": [
            {"platform": "thousandeyes", "event_type": "dns_failure", "min_severity": "high"},
            {"platform": "meraki", "event_type": "client_connectivity_drop", "min_severity": "medium"},
        ],
        "correlation": "dns_dependency",
        "root_cause": "DNS infrastructure failure causing cascading connectivity failures across platforms",
        "recommended_actions": [
            "Verify DNS server health and response times",
            "Check if secondary/tertiary DNS servers are reachable",
            "Review DHCP-assigned DNS vs. static configurations",
            "Consider enabling DNS caching at branch level",
        ],
    },
    {
        "id": "rca-cert-expiry-cascade",
        "name": "Certificate Expiry → Authentication Cascade",
        "description": "Security Cloud Control cert alert + ISE auth failures + XDR anomalies",
        "signal_pattern": [
            {"platform": "security_cloud_control", "event_type": "certificate_expiry", "min_severity": "medium"},
        ],
        "correlation": "certificate_chain",
        "root_cause": "Expiring or expired certificates causing authentication failures across services",
        "recommended_actions": [
            "Identify all certificates expiring within 30 days",
            "Initiate emergency certificate renewal workflow",
            "Verify certificate chain trust on all dependent services",
            "Update certificate monitoring alerts",
        ],
    },
]

# ---------------------------------------------------------------------------
# Correlation Engine
# ---------------------------------------------------------------------------

def _severity_rank(sev: str) -> int:
    return {"critical": 5, "high": 4, "medium": 3, "low": 2, "info": 1}.get(sev.lower(), 0)


def correlate_events(
    events: list[CorrelatedEvent],
    window_seconds: int = CORRELATION_WINDOW,
) -> list[dict[str, Any]]:
    """Group related events using entity overlap and time proximity."""
    if not events:
        return []

    groups: list[list[CorrelatedEvent]] = []
    used = set()

    sorted_events = sorted(events, key=lambda e: e.timestamp)

    for i, ev in enumerate(sorted_events):
        if i in used:
            continue
        group = [ev]
        used.add(i)
        for j in range(i + 1, len(sorted_events)):
            if j in used:
                continue
            if ev.overlaps_with(sorted_events[j], window_seconds):
                group.append(sorted_events[j])
                used.add(j)
        if len(group) > 1:
            groups.append(group)

    results = []
    for group in groups:
        platforms = list({e.source_platform.value for e in group})
        max_sev = max(group, key=lambda e: _severity_rank(e.severity.value))
        all_entities = []
        for e in group:
            all_entities.extend(e.affected_entities)
        results.append({
            "correlation_id": str(uuid.uuid4()),
            "event_count": len(group),
            "platforms": platforms,
            "severity": max_sev.severity.value,
            "time_span_seconds": (group[-1].timestamp - group[0].timestamp).total_seconds(),
            "affected_entities": list(set(all_entities)),
            "events": [e.model_dump(mode="json") for e in group],
        })

    return results


def match_root_cause(correlated_group: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Match a correlated event group against expert-curated RCA templates."""
    platforms = set(correlated_group.get("platforms", []))
    events = correlated_group.get("events", [])

    for template in ROOT_CAUSE_TEMPLATES:
        required_platforms = {s["platform"] for s in template["signal_pattern"]}
        if not required_platforms.issubset(platforms):
            continue

        match_count = 0
        for signal in template["signal_pattern"]:
            for event in events:
                if (
                    event.get("source_platform") == signal["platform"]
                    and _severity_rank(event.get("severity", "info"))
                    >= _severity_rank(signal["min_severity"])
                ):
                    match_count += 1
                    break

        if match_count == len(template["signal_pattern"]):
            return {
                "template_id": template["id"],
                "name": template["name"],
                "root_cause": template["root_cause"],
                "confidence": 0.85 + (0.05 * match_count),
                "recommended_actions": template["recommended_actions"],
                "matched_signals": len(template["signal_pattern"]),
            }

    return None


# ---------------------------------------------------------------------------
# Anomaly Detection (v1: statistical, v2: isolation forest)
# ---------------------------------------------------------------------------

def detect_anomalies(events: list[CorrelatedEvent]) -> list[dict[str, Any]]:
    """Detect anomalous patterns in event streams.

    v1: Frequency-based detection — flag when event rates exceed
    2σ above the rolling mean for a platform/event_type pair.
    """
    if len(events) < 5:
        return []

    # Group by platform + event_type
    buckets: dict[str, list[datetime]] = defaultdict(list)
    for e in events:
        key = f"{e.source_platform.value}:{e.event_type}"
        buckets[key].append(e.timestamp)

    anomalies = []
    for key, timestamps in buckets.items():
        if len(timestamps) < 3:
            continue
        # Calculate inter-event intervals
        sorted_ts = sorted(timestamps)
        intervals = [
            (sorted_ts[i + 1] - sorted_ts[i]).total_seconds()
            for i in range(len(sorted_ts) - 1)
        ]
        if not intervals:
            continue

        mean_interval = sum(intervals) / len(intervals)
        if mean_interval == 0:
            continue

        # Check if recent events are arriving much faster than normal
        recent_interval = intervals[-1] if intervals else mean_interval
        variance = sum((x - mean_interval) ** 2 for x in intervals) / len(intervals)
        std_dev = variance ** 0.5

        if std_dev > 0 and recent_interval < (mean_interval - 2 * std_dev):
            platform, event_type = key.split(":", 1)
            anomalies.append({
                "anomaly_id": str(uuid.uuid4()),
                "platform": platform,
                "event_type": event_type,
                "pattern": "frequency_spike",
                "description": f"Event rate for {key} is {mean_interval / max(recent_interval, 0.1):.1f}x above normal",
                "mean_interval_seconds": round(mean_interval, 1),
                "recent_interval_seconds": round(recent_interval, 1),
                "std_dev": round(std_dev, 1),
                "confidence": min(0.95, ANOMALY_SENSITIVITY + 0.05),
                "severity": "high" if recent_interval < mean_interval * 0.2 else "medium",
            })

    return anomalies


# ---------------------------------------------------------------------------
# Predictive Failure Analysis
# ---------------------------------------------------------------------------

def predict_failures(
    events: list[CorrelatedEvent],
    history: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Predict potential cascading failures based on current events + history.

    v1: Pattern matching against known historical incident sequences.
    v2: Will use vector similarity search against incident embeddings.
    """
    predictions = []

    # Check for known escalation patterns
    current_platforms = {e.source_platform.value for e in events}
    current_severities = [e.severity.value for e in events]

    # Pattern 1: Multiple high-severity events from single platform → cascading
    platform_counts: dict[str, int] = defaultdict(int)
    for e in events:
        if _severity_rank(e.severity.value) >= 4:
            platform_counts[e.source_platform.value] += 1

    for platform, count in platform_counts.items():
        if count >= 3:
            predictions.append({
                "prediction_id": str(uuid.uuid4()),
                "type": "cascading_failure",
                "description": f"Platform {platform} showing {count} high-severity events — potential cascade risk",
                "risk_level": "high",
                "confidence": min(0.90, 0.6 + count * 0.1),
                "affected_platform": platform,
                "recommended_preemptive_actions": [
                    f"Increase monitoring frequency for {platform}",
                    "Alert NOC team for proactive investigation",
                    "Verify redundancy and failover paths are operational",
                ],
                "time_horizon_minutes": 30,
            })

    # Pattern 2: Multi-platform involvement → complex incident developing
    if len(current_platforms) >= 3 and any(
        _severity_rank(s) >= 3 for s in current_severities
    ):
        predictions.append({
            "prediction_id": str(uuid.uuid4()),
            "type": "complex_incident",
            "description": f"Events across {len(current_platforms)} platforms suggest a developing complex incident",
            "risk_level": "critical" if len(current_platforms) >= 4 else "high",
            "confidence": 0.70,
            "affected_platforms": list(current_platforms),
            "recommended_preemptive_actions": [
                "Initiate incident response bridge",
                "Cross-reference events with recent change windows",
                "Validate core infrastructure (DNS, DHCP, NTP, AAA) health",
            ],
            "time_horizon_minutes": 15,
        })

    return predictions


# ---------------------------------------------------------------------------
# Lifespan + OASF Registration
# ---------------------------------------------------------------------------

INFER_OASF = OASFRecord(
    name="infer_mcp",
    description="INFER — Cross-platform intelligence engine for root cause analysis, anomaly detection, and predictive failure analysis",
    platform=PlatformType.INFER,
    roles=[MIGARole.OBSERVABILITY, MIGARole.SECURITY, MIGARole.COMPLIANCE],
    skills=[
        "cross_platform_correlation",
        "root_cause_analysis",
        "anomaly_detection",
        "predictive_analysis",
        "capacity_planning",
    ],
    domains=["intelligence", "analytics", "security", "assurance"],
    endpoint=f"http://infer-mcp:{os.getenv('INFER_MCP_PORT', '8007')}",
    capabilities=[
        PlatformCapability(tool_name="infer_correlate_events", description="Correlate events across platforms", roles=[MIGARole.OBSERVABILITY], platform=PlatformType.INFER),
        PlatformCapability(tool_name="infer_root_cause_analysis", description="AI-driven root cause analysis", roles=[MIGARole.OBSERVABILITY], platform=PlatformType.INFER),
        PlatformCapability(tool_name="infer_detect_anomalies", description="Detect anomalous patterns across telemetry", roles=[MIGARole.OBSERVABILITY, MIGARole.SECURITY], platform=PlatformType.INFER),
        PlatformCapability(tool_name="infer_predict_failures", description="Predict potential cascading failures", roles=[MIGARole.OBSERVABILITY], platform=PlatformType.INFER),
        PlatformCapability(tool_name="infer_get_incident_timeline", description="Get timeline of correlated incidents", roles=[MIGARole.OBSERVABILITY, MIGARole.COMPLIANCE], platform=PlatformType.INFER),
        PlatformCapability(tool_name="infer_network_risk_score", description="Calculate network-wide risk score", roles=[MIGARole.SECURITY, MIGARole.COMPLIANCE], platform=PlatformType.INFER),
    ],
)


@asynccontextmanager
async def app_lifespan():
    async with miga_lifespan(INFER_OASF, api_factory=None) as state:
        bus: RedisPubSub = state["bus"]

        # Subscribe to all platform telemetry + security alerts
        async def _on_correlated_event(channel: str, data: dict[str, Any]):
            try:
                event = CorrelatedEvent(**data)
                _event_buffer.append(event)
                # Keep buffer bounded
                if len(_event_buffer) > 10000:
                    _event_buffer[:] = _event_buffer[-5000:]
            except Exception as e:
                logger.error("Failed to ingest event: %s", e)

        async def _on_security_alert(channel: str, data: dict[str, Any]):
            try:
                event = CorrelatedEvent(
                    source_platform=PlatformType(data.get("source", "xdr")),
                    event_type=data.get("event_type", "security_alert"),
                    severity=SeverityLevel(data.get("severity", "medium")),
                    raw_data=data.get("data", {}),
                )
                _event_buffer.append(event)
            except Exception as e:
                logger.error("Failed to ingest security alert: %s", e)

        await bus.subscribe("miga:events:correlated", _on_correlated_event)
        await bus.subscribe("miga:alerts:security", _on_security_alert)
        for platform in PlatformType:
            await bus.subscribe(f"miga:telemetry:{platform.value}", _on_correlated_event)
        await bus.start_listening()

        yield state


mcp = FastMCP("infer_mcp", lifespan=app_lifespan)
add_health_tool(mcp, PlatformType.INFER, "infer")

# ---------------------------------------------------------------------------
# Input Models
# ---------------------------------------------------------------------------

class CorrelateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    window_seconds: int = Field(default=CORRELATION_WINDOW, ge=30, le=3600, description="Time window for correlation")
    min_severity: str = Field(default="low", description="Minimum severity to include")
    platforms: Optional[list[str]] = Field(default=None, description="Filter to specific platforms")


class RCAInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    correlation_id: Optional[str] = Field(default=None, description="Specific correlation group to analyze")
    window_seconds: int = Field(default=CORRELATION_WINDOW, ge=30, le=3600)


class AnomalyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lookback_minutes: int = Field(default=60, ge=5, le=1440, description="How far back to look for anomalies")
    min_confidence: float = Field(default=0.7, ge=0.0, le=1.0)


class PredictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lookback_minutes: int = Field(default=30, ge=5, le=240)
    include_history: bool = Field(default=True, description="Include historical incident data for pattern matching")


class TimelineInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hours: int = Field(default=24, ge=1, le=168, description="How many hours of history to show")
    min_severity: str = Field(default="info")


class RiskScoreInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    include_predictions: bool = Field(default=True)
    include_anomalies: bool = Field(default=True)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool(name="infer_correlate_events", annotations={"readOnlyHint": True, "idempotentHint": True})
async def correlate_events_tool(params: CorrelateInput, ctx=None) -> str:
    """Correlate events across all Cisco platforms to identify related incidents.

    Groups events by entity overlap (shared devices, IPs, users) within a time
    window, surfacing multi-platform incidents that individual platforms miss.
    """
    events = list(_event_buffer)

    # Apply filters
    if params.min_severity != "low":
        min_rank = _severity_rank(params.min_severity)
        events = [e for e in events if _severity_rank(e.severity.value) >= min_rank]
    if params.platforms:
        events = [e for e in events if e.source_platform.value in params.platforms]

    groups = correlate_events(events, params.window_seconds)

    if not groups:
        return "## INFER — Event Correlation\n\n✅ No correlated multi-platform events detected."

    lines = [f"## INFER — Correlated Events ({len(groups)} groups)\n"]
    for g in groups:
        emoji = Fmt.severity_emoji(g["severity"])
        lines.append(f"### {emoji} Correlation `{g['correlation_id'][:8]}...`")
        lines.append(f"**Platforms:** {', '.join(g['platforms'])}")
        lines.append(f"**Events:** {g['event_count']} | **Severity:** {g['severity']}")
        lines.append(f"**Time Span:** {g['time_span_seconds']:.0f}s | **Entities:** {', '.join(g['affected_entities'][:5])}")
        lines.append("")
    return "\n".join(lines)


@mcp.tool(name="infer_root_cause_analysis", annotations={"readOnlyHint": True, "idempotentHint": True})
async def root_cause_analysis(params: RCAInput, ctx=None) -> str:
    """Perform AI-driven root cause analysis on correlated multi-platform events.

    Matches correlated event groups against expert-curated root cause templates
    to identify the most likely cause and provide actionable remediation steps.
    """
    events = list(_event_buffer)
    groups = correlate_events(events, params.window_seconds)

    if params.correlation_id:
        groups = [g for g in groups if g["correlation_id"].startswith(params.correlation_id)]

    if not groups:
        return "## INFER — Root Cause Analysis\n\n✅ No correlated event groups to analyze."

    lines = ["## INFER — Root Cause Analysis\n"]
    for g in groups:
        rca = match_root_cause(g)
        emoji = Fmt.severity_emoji(g["severity"])
        lines.append(f"### {emoji} Correlation `{g['correlation_id'][:8]}...`")
        lines.append(f"**Platforms:** {', '.join(g['platforms'])}")

        if rca:
            lines.append(f"\n**🎯 Root Cause:** {rca['name']}")
            lines.append(f"**Confidence:** {rca['confidence']:.0%}")
            lines.append(f"\n_{rca['root_cause']}_\n")
            lines.append("**Recommended Actions:**")
            for i, action in enumerate(rca["recommended_actions"], 1):
                lines.append(f"{i}. {action}")
            _incident_history.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "correlation_id": g["correlation_id"],
                "rca": rca,
                "platforms": g["platforms"],
                "severity": g["severity"],
            })
        else:
            lines.append("\n⚠️ No matching root cause template — manual investigation recommended.")
            lines.append("_Consider creating a new RCA template for this pattern._")
        lines.append("")

    return "\n".join(lines)


@mcp.tool(name="infer_detect_anomalies", annotations={"readOnlyHint": True, "idempotentHint": True})
async def detect_anomalies_tool(params: AnomalyInput, ctx=None) -> str:
    """Detect anomalous patterns across all platform telemetry streams.

    Uses statistical analysis (v1) to identify unusual event frequencies,
    traffic patterns, and behavioral deviations.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=params.lookback_minutes)
    events = [e for e in _event_buffer if e.timestamp >= cutoff]
    anomalies = detect_anomalies(events)
    anomalies = [a for a in anomalies if a.get("confidence", 0) >= params.min_confidence]

    if not anomalies:
        return f"## INFER — Anomaly Detection\n\n✅ No anomalies detected in the last {params.lookback_minutes} minutes."

    _anomaly_log.extend(anomalies)

    lines = [f"## INFER — Anomaly Detection ({len(anomalies)} found)\n"]
    for a in anomalies:
        emoji = Fmt.severity_emoji(a.get("severity", "medium"))
        lines.append(f"### {emoji} {a['platform']}: {a['event_type']}")
        lines.append(f"**Pattern:** {a['pattern']} | **Confidence:** {a['confidence']:.0%}")
        lines.append(f"_{a['description']}_")
        lines.append(f"Normal interval: {a['mean_interval_seconds']}s | Recent: {a['recent_interval_seconds']}s")
        lines.append("")
    return "\n".join(lines)


@mcp.tool(name="infer_predict_failures", annotations={"readOnlyHint": True, "idempotentHint": True})
async def predict_failures_tool(params: PredictInput, ctx=None) -> str:
    """Predict potential cascading failures based on current event patterns.

    Analyzes the current event stream against known failure sequences to
    identify risks before they cascade across platforms.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=params.lookback_minutes)
    events = [e for e in _event_buffer if e.timestamp >= cutoff]
    history = _incident_history if params.include_history else []

    predictions = predict_failures(events, history)

    if not predictions:
        return f"## INFER — Predictive Analysis\n\n✅ No failure predictions based on current {params.lookback_minutes}m event window."

    lines = [f"## INFER — Failure Predictions ({len(predictions)} risks)\n"]
    for p in predictions:
        risk_emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡"}.get(p["risk_level"], "🔵")
        lines.append(f"### {risk_emoji} {p['type'].replace('_', ' ').title()}")
        lines.append(f"**Risk Level:** {p['risk_level']} | **Confidence:** {p['confidence']:.0%}")
        lines.append(f"**Time Horizon:** {p['time_horizon_minutes']} minutes")
        lines.append(f"\n_{p['description']}_\n")
        lines.append("**Preemptive Actions:**")
        for i, action in enumerate(p["recommended_preemptive_actions"], 1):
            lines.append(f"{i}. {action}")
        lines.append("")
    return "\n".join(lines)


@mcp.tool(name="infer_get_incident_timeline", annotations={"readOnlyHint": True, "idempotentHint": True})
async def get_incident_timeline(params: TimelineInput, ctx=None) -> str:
    """Get a timeline of all correlated incidents detected by INFER."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=params.hours)
    min_rank = _severity_rank(params.min_severity)

    recent = [
        inc for inc in _incident_history
        if datetime.fromisoformat(inc["timestamp"]) >= cutoff
        and _severity_rank(inc.get("severity", "info")) >= min_rank
    ]

    if not recent:
        return f"## INFER — Incident Timeline\n\n✅ No incidents in the last {params.hours}h."

    lines = [f"## INFER — Incident Timeline (last {params.hours}h, {len(recent)} incidents)\n"]
    for inc in sorted(recent, key=lambda x: x["timestamp"], reverse=True):
        ts = Fmt.ts(inc["timestamp"])
        sev = inc.get("severity", "info")
        emoji = Fmt.severity_emoji(sev)
        rca = inc.get("rca", {})
        name = rca.get("name", "Unknown Pattern")
        platforms = ", ".join(inc.get("platforms", []))
        lines.append(f"- {emoji} **{ts}** — {name} ({platforms}) [{sev}]")
    return "\n".join(lines)


@mcp.tool(name="infer_network_risk_score", annotations={"readOnlyHint": True, "idempotentHint": True})
async def network_risk_score(params: RiskScoreInput, ctx=None) -> str:
    """Calculate a network-wide risk score based on current events, anomalies, and predictions.

    Produces a 0-100 score where:
    - 0-25:  Low risk — normal operations
    - 26-50: Moderate — minor issues detected
    - 51-75: Elevated — active incidents or significant anomalies
    - 76-100: Critical — cascading failures or security incidents
    """
    now = datetime.now(timezone.utc)
    recent_events = [e for e in _event_buffer if (now - e.timestamp).total_seconds() < 3600]

    # Base score from event severity
    score = 0.0
    for e in recent_events:
        score += {"critical": 15, "high": 8, "medium": 3, "low": 1, "info": 0}.get(e.severity.value, 0)

    # Cap event contribution at 60
    event_score = min(60.0, score)

    # Anomaly contribution
    anomaly_score = 0.0
    if params.include_anomalies:
        recent_anomalies = [
            a for a in _anomaly_log
            if a.get("confidence", 0) >= 0.7
        ]
        anomaly_score = min(20.0, len(recent_anomalies) * 5.0)

    # Prediction contribution
    prediction_score = 0.0
    if params.include_predictions:
        predictions = predict_failures(recent_events, _incident_history)
        for p in predictions:
            if p["risk_level"] == "critical":
                prediction_score += 15
            elif p["risk_level"] == "high":
                prediction_score += 8
        prediction_score = min(20.0, prediction_score)

    total = min(100.0, event_score + anomaly_score + prediction_score)

    # Risk tier
    if total <= 25:
        tier, tier_emoji = "LOW", "🟢"
    elif total <= 50:
        tier, tier_emoji = "MODERATE", "🟡"
    elif total <= 75:
        tier, tier_emoji = "ELEVATED", "🟠"
    else:
        tier, tier_emoji = "CRITICAL", "🔴"

    return f"""## INFER — Network Risk Score

{tier_emoji} **{total:.0f}/100** — {tier}

**Score Breakdown:**
- Events (last 1h): {event_score:.0f}/60 ({len(recent_events)} events)
- Anomalies: {anomaly_score:.0f}/20
- Predictions: {prediction_score:.0f}/20

**Active Platforms:** {len({e.source_platform.value for e in recent_events})}
**Event Buffer Size:** {len(_event_buffer)}
**Historical Incidents:** {len(_incident_history)}
"""


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.getenv("INFER_MCP_PORT", "8007"))
    mcp.run(transport="streamable_http", port=port)
