"""Tests for WebEx Bot Adaptive Card templates."""
from __future__ import annotations

from packages.webex_bot.cards import (
    alert_card,
    approval_card,
    health_card,
    table_card,
    wrap_card,
)


class TestHealthCard:
    def test_structure(self):
        card = health_card(
            title="Network Health",
            score=92.0,
            platform="Catalyst Center",
            details=[
                {"label": "Devices", "value": "42"},
                {"label": "Issues", "value": "3"},
            ],
        )
        assert card["type"] == "AdaptiveCard"
        assert card["version"] == "1.3"
        assert len(card["body"]) == 2  # ColumnSet + Container

    def test_good_score_color(self):
        card = health_card("Test", 95.0, "Meraki", [])
        cols = card["body"][0]["columns"]
        score_text = cols[-1]["items"][0]
        assert score_text["color"] == "Good"

    def test_warning_score_color(self):
        card = health_card("Test", 75.0, "Meraki", [])
        cols = card["body"][0]["columns"]
        score_text = cols[-1]["items"][0]
        assert score_text["color"] == "Warning"


class TestAlertCard:
    def test_with_actions(self):
        card = alert_card(
            title="Security Alert",
            severity="critical",
            source="XDR",
            description="Suspicious traffic detected",
            actions=[{"label": "Investigate", "action": "investigate"}],
        )
        assert "actions" in card
        assert len(card["actions"]) == 1

    def test_without_actions(self):
        card = alert_card("Alert", "low", "Meraki", "Minor issue")
        assert "actions" not in card


class TestApprovalCard:
    def test_has_approve_reject(self):
        card = approval_card(
            tool_name="catalyst_run_command",
            action_description="show version on switch-01",
            details={"Device": "switch-01", "Command": "show version"},
            approval_id="abc-123",
        )
        assert len(card["actions"]) == 2
        labels = [a["title"] for a in card["actions"]]
        assert "✅ Approve" in labels
        assert "❌ Reject" in labels
        # Verify approval_id in action data
        assert card["actions"][0]["data"]["approval_id"] == "abc-123"


class TestTableCard:
    def test_basic_table(self):
        card = table_card(
            title="Devices",
            headers=["Name", "Status"],
            rows=[["switch-01", "online"], ["switch-02", "offline"]],
        )
        assert card["body"][0]["text"] == "Devices"
        # Header row + 2 data rows = 3 ColumnSets after title
        assert len(card["body"]) == 4

    def test_truncates_over_20_rows(self):
        rows = [[f"device-{i}", "online"] for i in range(30)]
        card = table_card("Many Devices", ["Name", "Status"], rows)
        last_item = card["body"][-1]
        assert "more" in last_item["text"].lower()


class TestWrapCard:
    def test_wraps_for_webex(self):
        card = {"type": "AdaptiveCard", "body": []}
        wrapped = wrap_card(card)
        assert wrapped["contentType"] == "application/vnd.microsoft.card.adaptive"
        assert wrapped["content"] is card
