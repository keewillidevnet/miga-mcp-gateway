"""Response formatting — Markdown tables, badges, timestamps for MCP output."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any


class Fmt:
    """Static formatting helpers used by all MCP servers."""

    @staticmethod
    def severity_emoji(sev: str) -> str:
        return {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵", "info": "⚪"}.get(sev.lower(), "⚪")

    @staticmethod
    def health_badge(score: float) -> str:
        if score >= 90: return f"🟢 {score:.0f}/100"
        if score >= 70: return f"🟡 {score:.0f}/100"
        if score >= 50: return f"🟠 {score:.0f}/100"
        return f"🔴 {score:.0f}/100"

    @staticmethod
    def status_dot(status: str) -> str:
        return "🟢" if status.lower() in ("reachable", "online", "healthy", "good", "active", "up") else "🔴"

    @staticmethod
    def ts(t: datetime | str | None) -> str:
        if t is None:
            return "N/A"
        if isinstance(t, str):
            try:
                t = datetime.fromisoformat(t.replace("Z", "+00:00"))
            except ValueError:
                return t
        now = datetime.now(timezone.utc)
        dt = t if t.tzinfo else t.replace(tzinfo=timezone.utc)
        delta = (now - dt).total_seconds()
        if delta < 60: return "just now"
        if delta < 3600: return f"{int(delta/60)}m ago"
        if delta < 86400: return f"{int(delta/3600)}h ago"
        return dt.strftime("%Y-%m-%d %H:%M UTC")

    @staticmethod
    def md_table(headers: list[str], rows: list[list[Any]]) -> str:
        if not rows:
            return "_No data._"
        widths = [max(len(str(h)), *(len(str(r[i])) if i < len(r) else 0 for r in rows)) for i, h in enumerate(headers)]
        hdr = "| " + " | ".join(h.ljust(widths[i]) for i, h in enumerate(headers)) + " |"
        sep = "| " + " | ".join("-" * w for w in widths) + " |"
        body = "\n".join(
            "| " + " | ".join(str(r[i]).ljust(widths[i]) if i < len(r) else " " * widths[i] for i in range(len(headers))) + " |"
            for r in rows
        )
        return f"{hdr}\n{sep}\n{body}"

    @staticmethod
    def devices_md(devices: list[dict]) -> str:
        if not devices:
            return "_No devices found._"
        lines = [f"### Network Devices ({len(devices)} total)\n"]
        for d in devices[:25]:
            name = d.get("hostname", d.get("name", "Unknown"))
            status = d.get("reachabilityStatus", d.get("status", "unknown"))
            ip = d.get("managementIpAddress", d.get("lanIp", "N/A"))
            model = d.get("platformId", d.get("model", "N/A"))
            lines.append(f"- {Fmt.status_dot(status)} **{name}** ({model}) — {ip}")
        if len(devices) > 25:
            lines.append(f"\n_…and {len(devices) - 25} more._")
        return "\n".join(lines)

    @staticmethod
    def alerts_md(alerts: list[dict]) -> str:
        if not alerts:
            return "_No active alerts._"
        lines = [f"### Alerts ({len(alerts)})\n"]
        for a in alerts[:20]:
            sev = a.get("severity", "info")
            title = a.get("title", a.get("name", "Untitled"))
            lines.append(f"- {Fmt.severity_emoji(sev)} **{title}** — {Fmt.ts(a.get('timestamp'))}")
        return "\n".join(lines)
