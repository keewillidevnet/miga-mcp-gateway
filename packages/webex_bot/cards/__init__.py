"""WebEx Adaptive Card templates for rich interactive UI.

Cards are JSON templates rendered in WebEx as interactive widgets with
buttons, dropdowns, and data tables.
"""
from __future__ import annotations

import json
from typing import Any


def health_card(
    title: str,
    score: float,
    platform: str,
    details: list[dict[str, str]],
) -> dict[str, Any]:
    """Health overview card with score badge and detail rows."""
    color = "Good" if score >= 90 else "Warning" if score >= 70 else "Attention"
    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.3",
        "body": [
            {
                "type": "ColumnSet",
                "columns": [
                    {
                        "type": "Column",
                        "width": "stretch",
                        "items": [
                            {"type": "TextBlock", "text": title, "size": "Large", "weight": "Bolder"},
                            {"type": "TextBlock", "text": platform, "size": "Small", "color": "Light"},
                        ],
                    },
                    {
                        "type": "Column",
                        "width": "auto",
                        "items": [
                            {"type": "TextBlock", "text": f"{score:.0f}/100", "size": "ExtraLarge", "weight": "Bolder", "color": color},
                        ],
                    },
                ],
            },
            {"type": "Container", "items": [
                {"type": "ColumnSet", "columns": [
                    {"type": "Column", "width": "stretch", "items": [{"type": "TextBlock", "text": d["label"], "weight": "Bolder"}]},
                    {"type": "Column", "width": "auto", "items": [{"type": "TextBlock", "text": d["value"]}]},
                ]} for d in details
            ]},
        ],
    }


def alert_card(
    title: str,
    severity: str,
    source: str,
    description: str,
    actions: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Security/alert card with severity indicator and action buttons."""
    color_map = {"critical": "Attention", "high": "Warning", "medium": "Accent", "low": "Light"}
    card: dict[str, Any] = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.3",
        "body": [
            {"type": "TextBlock", "text": f"🚨 {title}", "size": "Large", "weight": "Bolder", "color": color_map.get(severity, "Default")},
            {"type": "FactSet", "facts": [
                {"title": "Severity", "value": severity.upper()},
                {"title": "Source", "value": source},
            ]},
            {"type": "TextBlock", "text": description, "wrap": True},
        ],
    }
    if actions:
        card["actions"] = [
            {"type": "Action.Submit", "title": a["label"], "data": {"action": a["action"], **a.get("data", {})}}
            for a in actions
        ]
    return card


def approval_card(
    tool_name: str,
    action_description: str,
    details: dict[str, str],
    approval_id: str,
) -> dict[str, Any]:
    """Human-in-the-loop approval card with Accept/Reject buttons."""
    facts = [{"title": k, "value": v} for k, v in details.items()]
    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.3",
        "body": [
            {"type": "TextBlock", "text": "⚠️ Approval Required", "size": "Large", "weight": "Bolder", "color": "Warning"},
            {"type": "TextBlock", "text": f"**{tool_name}**: {action_description}", "wrap": True},
            {"type": "FactSet", "facts": facts},
        ],
        "actions": [
            {"type": "Action.Submit", "title": "✅ Approve", "style": "positive", "data": {"action": "approve", "approval_id": approval_id}},
            {"type": "Action.Submit", "title": "❌ Reject", "style": "destructive", "data": {"action": "reject", "approval_id": approval_id}},
        ],
    }


def table_card(title: str, headers: list[str], rows: list[list[str]]) -> dict[str, Any]:
    """Data table card for displaying tabular results."""
    body: list[dict] = [
        {"type": "TextBlock", "text": title, "size": "Large", "weight": "Bolder"},
        # Header row
        {"type": "ColumnSet", "columns": [
            {"type": "Column", "width": "stretch", "items": [{"type": "TextBlock", "text": h, "weight": "Bolder", "size": "Small"}]}
            for h in headers
        ]},
    ]
    # Data rows
    for row in rows[:20]:
        body.append({"type": "ColumnSet", "separator": True, "columns": [
            {"type": "Column", "width": "stretch", "items": [{"type": "TextBlock", "text": str(cell), "size": "Small"}]}
            for cell in row
        ]})
    if len(rows) > 20:
        body.append({"type": "TextBlock", "text": f"_...and {len(rows) - 20} more rows._", "size": "Small", "isSubtle": True})

    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.3",
        "body": body,
    }


def wrap_card(card: dict[str, Any]) -> dict[str, Any]:
    """Wrap an Adaptive Card for the WebEx API attachment format."""
    return {
        "contentType": "application/vnd.microsoft.card.adaptive",
        "content": card,
    }
