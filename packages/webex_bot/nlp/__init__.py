"""NLP Intent Recognition — hybrid pattern matching + LLM fallback.

v1 uses regex pattern matching for common commands and optional spaCy
for entity extraction. LLM fallback for ambiguous queries.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger("miga.nlp")


class IntentCategory(str, Enum):
    """Mapped to gateway role-based meta-tools."""
    OBSERVABILITY = "observability"
    SECURITY = "security"
    AUTOMATION = "automation"
    CONFIGURATION = "configuration"
    COMPLIANCE = "compliance"
    IDENTITY = "identity"
    STATUS = "network_status"
    HELP = "help"
    UNKNOWN = "unknown"


@dataclass
class ParsedIntent:
    """Result of intent recognition."""
    category: IntentCategory
    tool_name: Optional[str] = None
    platform: Optional[str] = None
    arguments: dict = field(default_factory=dict)
    confidence: float = 0.0
    raw_text: str = ""


# ---------------------------------------------------------------------------
# Pattern matching rules (ordered by specificity)
# ---------------------------------------------------------------------------

INTENT_PATTERNS: list[tuple[str, IntentCategory, Optional[str], float]] = [
    # Status / health
    (r"(?:network|overall)\s*(?:status|health|overview)", IntentCategory.STATUS, None, 0.95),
    (r"(?:is|are)\s+(?:the\s+)?(?:network|things)\s+(?:ok|healthy|up|down)", IntentCategory.STATUS, None, 0.90),
    (r"how(?:'s| is)\s+(?:the\s+)?network", IntentCategory.STATUS, None, 0.90),

    # Platform-specific health
    (r"(?:meraki|dashboard)\s+(?:health|status|overview|devices)", IntentCategory.OBSERVABILITY, "meraki", 0.90),
    (r"(?:catalyst|dnac?|catalyst.center)\s+(?:health|status|issues?|devices?)", IntentCategory.OBSERVABILITY, "catalyst_center", 0.90),
    (r"(?:thousandeyes|te|path)\s+(?:health|status|tests?|alerts?)", IntentCategory.OBSERVABILITY, "thousandeyes", 0.90),
    (r"(?:wireless|wifi|wi-fi)\s+(?:health|status|clients?)", IntentCategory.OBSERVABILITY, "meraki", 0.85),

    # Security
    (r"(?:security|threat|xdr)\s+(?:events?|incidents?|alerts?|threats?)", IntentCategory.SECURITY, "xdr", 0.90),
    (r"(?:malware|amp|ids|ips)\s+(?:events?|detections?|alerts?)", IntentCategory.SECURITY, None, 0.90),
    (r"(?:lateral\s+movement|suspicious|anomal)", IntentCategory.SECURITY, None, 0.85),
    (r"(?:firewall|fw)\s+(?:rules?|policies?|status)", IntentCategory.SECURITY, "security_cloud_control", 0.85),
    (r"(?:hypershield|ebpf)\s+(?:status|enforcement|flows?)", IntentCategory.SECURITY, "hypershield", 0.85),

    # INFER-specific
    (r"(?:correlat|root.cause|rca)", IntentCategory.OBSERVABILITY, "infer", 0.90),
    (r"(?:predict|forecast)\s+(?:fail|outage|incident)", IntentCategory.OBSERVABILITY, "infer", 0.90),
    (r"(?:anomal|unusual|abnormal)\s+(?:pattern|behavior|traffic)", IntentCategory.OBSERVABILITY, "infer", 0.85),
    (r"risk\s+score", IntentCategory.COMPLIANCE, "infer", 0.90),

    # Automation
    (r"(?:run|execute)\s+(?:command|cli|show)", IntentCategory.AUTOMATION, "catalyst_center", 0.90),
    (r"(?:remediat|fix|restart|reboot)", IntentCategory.AUTOMATION, None, 0.80),
    (r"quarantine\s+(?:endpoint|device|mac)", IntentCategory.AUTOMATION, "ise", 0.90),

    # Configuration
    (r"(?:show|get)\s+(?:config|configuration|running)", IntentCategory.CONFIGURATION, None, 0.85),
    (r"(?:topology|site.hierarchy|fabric)", IntentCategory.CONFIGURATION, None, 0.80),
    (r"(?:list|show)\s+(?:networks?|devices?|inventory)", IntentCategory.CONFIGURATION, None, 0.80),

    # Compliance
    (r"(?:compliance|posture|audit|certificate)", IntentCategory.COMPLIANCE, None, 0.85),
    (r"(?:policy\s+drift|regulatory)", IntentCategory.COMPLIANCE, None, 0.80),

    # Identity
    (r"(?:who|session|authentication|radius|dot1x)", IntentCategory.IDENTITY, "ise", 0.85),
    (r"(?:profil|endpoint\s+type|device\s+type)", IntentCategory.IDENTITY, "ise", 0.80),

    # Help
    (r"(?:help|what\s+can\s+you|capabilities|tools?|commands?)", IntentCategory.HELP, None, 0.95),
]

# Entity extraction patterns
ENTITY_PATTERNS = {
    "ip_address": re.compile(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b"),
    "mac_address": re.compile(r"\b([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b"),
    "hostname": re.compile(r"\b(switch|router|ap|wlc|fw|leaf|spine)[-_][\w-]+\b", re.IGNORECASE),
    "network_id": re.compile(r"\b[LN]_\d+\b"),
    "device_id": re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"),
    "severity": re.compile(r"\b(critical|high|medium|low|p[1-4])\b", re.IGNORECASE),
}


def recognize_intent(text: str) -> ParsedIntent:
    """Parse user message into a structured intent.

    Uses ordered regex patterns for common commands. Falls back to UNKNOWN
    for ambiguous queries (caller can then invoke LLM fallback).
    """
    normalized = text.strip().lower()

    best: Optional[ParsedIntent] = None
    for pattern, category, platform, confidence in INTENT_PATTERNS:
        if re.search(pattern, normalized, re.IGNORECASE):
            intent = ParsedIntent(
                category=category,
                platform=platform,
                confidence=confidence,
                raw_text=text,
            )
            if best is None or confidence > best.confidence:
                best = intent

    if best is None:
        best = ParsedIntent(category=IntentCategory.UNKNOWN, confidence=0.0, raw_text=text)

    # Extract entities
    for entity_type, pattern in ENTITY_PATTERNS.items():
        matches = pattern.findall(normalized)
        if matches:
            # Flatten MAC matches (they come as tuples from group captures)
            if entity_type == "mac_address":
                best.arguments[entity_type] = [text[m.start():m.end()] for m in pattern.finditer(text)]
            else:
                best.arguments[entity_type] = matches

    return best


def format_help() -> str:
    """Generate help text for the WebEx Bot."""
    return """## MIGA — What can I do?

**Quick Status:**
- "How's the network?" — Cross-platform health overview
- "Network status" — All servers connectivity check

**Observability:**
- "Meraki health" / "Catalyst Center issues" / "ThousandEyes status"
- "Wireless client health" / "Show me network health"
- "Any anomalies?" / "Run correlation" / "Root cause analysis"

**Security:**
- "Security events" / "XDR threats" / "Malware detections"
- "Firewall policy status" / "Hypershield enforcement"
- "Risk score" — INFER network-wide risk assessment

**Configuration:**
- "List devices" / "Show topology" / "Get device config"
- "List Meraki networks"

**Automation:**
- "Run show version on [device]" ⚠️ _Requires approval_
- "Quarantine endpoint [MAC]" ⚠️ _Requires approval_

**Compliance:**
- "Posture status" / "Certificate expiry" / "Compliance audit"

**Identity:**
- "Active sessions" / "Auth failures" / "Profiled endpoints"
"""
