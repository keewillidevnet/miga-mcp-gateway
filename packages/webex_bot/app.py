"""MIGA WebEx Bot — Conversational interface to the MCP Gateway.

Receives messages from WebEx via webhook, processes NLP intent recognition,
forwards to the Gateway MCP server, and renders results as Adaptive Cards
or Markdown in the WebEx room.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx
from aiohttp import web

from packages.webex_bot.nlp import (
    IntentCategory,
    ParsedIntent,
    format_help,
    recognize_intent,
)
from packages.webex_bot.cards import (
    alert_card,
    approval_card,
    health_card,
    wrap_card,
)

logger = logging.getLogger("miga.webex_bot")

WEBEX_API = os.getenv("WEBEX_API_BASE_URL", "https://webexapis.com/v1")
BOT_TOKEN = os.getenv("WEBEX_BOT_ACCESS_TOKEN", "")
BOT_EMAIL = os.getenv("WEBEX_BOT_EMAIL", "miga-bot@webex.bot")
GATEWAY_URL = os.getenv("MIGA_GATEWAY_URL", "http://miga-gateway:8000")
# Gateway transport: "mcp" (default, official MCP streamable-http client) or "http"
# (an internal dev convenience/fallback route on the gateway). See docs/BOT_DEMO.md.
GATEWAY_MODE = os.getenv("MIGA_BOT_GATEWAY_MODE", "mcp").strip().lower()

http_client = httpx.AsyncClient(timeout=60.0)


# ---------------------------------------------------------------------------
# WebEx API helpers
# ---------------------------------------------------------------------------

async def webex_get_message(message_id: str) -> dict[str, Any]:
    """Fetch message content from WebEx."""
    resp = await http_client.get(
        f"{WEBEX_API}/messages/{message_id}",
        headers={"Authorization": f"Bearer {BOT_TOKEN}"},
    )
    resp.raise_for_status()
    return resp.json()


async def webex_send_message(
    room_id: str,
    text: str = "",
    markdown: str = "",
    card: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Send a message (text, markdown, or Adaptive Card) to a WebEx room."""
    payload: dict[str, Any] = {"roomId": room_id}
    if card:
        payload["text"] = text or "MIGA response (card attached)"
        payload["attachments"] = [wrap_card(card)]
    elif markdown:
        payload["markdown"] = markdown
    else:
        payload["text"] = text

    resp = await http_client.post(
        f"{WEBEX_API}/messages",
        headers={
            "Authorization": f"Bearer {BOT_TOKEN}",
            "Content-Type": "application/json",
        },
        json=payload,
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Gateway MCP Client
# ---------------------------------------------------------------------------

def _extract_text(content: Any) -> str:
    """Join the text blocks out of an MCP tool result (objects with .text or
    {"type": "text", "text": ...} dicts)."""
    texts: list[str] = []
    for block in content or []:
        text = getattr(block, "text", None)
        if text is None and isinstance(block, dict):
            text = block.get("text") if block.get("type") == "text" else None
        if text:
            texts.append(text)
    return "\n".join(texts)


async def _call_gateway_mcp(tool_name: str, arguments: dict[str, Any]) -> str:
    """Primary path: call the gateway as an MCP client over streamable-http.

    TODO: confirm the exact client API against the installed ``mcp`` version. The
    streamable-http session semantics (handshake, session id, read timeout) are
    version-sensitive and MUST be live-tested in the operator's environment. The
    ``http`` fallback (MIGA_BOT_GATEWAY_MODE=http) exists for exactly that reason.
    """
    from datetime import timedelta

    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    url = f"{GATEWAY_URL}/mcp"
    async with streamablehttp_client(url) as streams:
        read, write = streams[0], streams[1]
        async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=60)) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
    return _extract_text(getattr(result, "content", None)) or "MIGA: (empty response)"


async def _call_gateway_http(tool_name: str, arguments: dict[str, Any]) -> str:
    """Fallback path: the gateway's dev-only POST /internal/call route."""
    resp = await http_client.post(
        f"{GATEWAY_URL}/internal/call",
        json={"tool": tool_name, "arguments": arguments},
    )
    resp.raise_for_status()
    body = resp.json()
    if isinstance(body, dict) and body.get("error"):
        return f"❌ Gateway error: {body['error']}"
    return _extract_text(body.get("content")) or "MIGA: (empty response)"


async def call_gateway(tool_name: str, arguments: dict[str, Any] | None = None) -> str:
    """Call a tool on the MIGA Gateway.

    Primary path is the official MCP streamable-http client (the WebEx bot embeds an MCP
    client). ``MIGA_BOT_GATEWAY_MODE=http`` selects the gateway's internal dev fallback
    route instead. Best-effort: an unreachable gateway returns a friendly message and
    never raises into the webhook handler.
    """
    arguments = arguments or {}
    try:
        if GATEWAY_MODE == "http":
            return await _call_gateway_http(tool_name, arguments)
        return await _call_gateway_mcp(tool_name, arguments)
    except httpx.ConnectError:
        return "❌ MIGA Gateway is unreachable. Please check the cluster status."
    except Exception as e:  # noqa: BLE001 - best-effort: never raise into the handler
        logger.warning("gateway call failed for %s: %r", tool_name, e)
        return f"❌ Error communicating with the MIGA Gateway: {e}"


# ---------------------------------------------------------------------------
# Intent → Gateway Tool Mapping
# ---------------------------------------------------------------------------

INTENT_TO_TOOL: dict[IntentCategory, str] = {
    IntentCategory.OBSERVABILITY: "observability",
    IntentCategory.SECURITY: "security",
    IntentCategory.AUTOMATION: "automation",
    IntentCategory.CONFIGURATION: "configuration",
    IntentCategory.COMPLIANCE: "compliance",
    IntentCategory.IDENTITY: "identity",
    IntentCategory.STATUS: "network_status",
}


# No NLP intent maps to the gateway_health tool, so route a few explicit phrases to it
# directly. This is bot-level routing only; the NLP module is unchanged.
_GATEWAY_HEALTH_PHRASES = (
    "gateway health",
    "gateway status",
    "miga health",
    "miga status",
    "are you up",
    "are you alive",
)


def _is_gateway_health_query(text: str) -> bool:
    low = text.strip().lower()
    return any(phrase in low for phrase in _GATEWAY_HEALTH_PHRASES)


async def handle_intent(intent: ParsedIntent, room_id: str) -> None:
    """Route a parsed intent to the Gateway and send the response."""
    if intent.category == IntentCategory.HELP:
        await webex_send_message(room_id, markdown=format_help())
        return

    if intent.category == IntentCategory.UNKNOWN:
        if intent.confidence < 0.5:
            await webex_send_message(
                room_id,
                markdown="🤔 I'm not sure what you're asking. Try **help** to see what I can do, or rephrase your question.",
            )
            return
        # Fallback: send to observability as a general query
        tool_name = "observability"
    else:
        tool_name = INTENT_TO_TOOL.get(intent.category, "observability")

    arguments: dict[str, Any] = {}
    if intent.platform:
        arguments["platforms"] = [intent.platform]
    if intent.tool_name:
        arguments["tool_name"] = intent.tool_name
    arguments.update(intent.arguments)

    # Send thinking indicator
    await webex_send_message(room_id, text="🔍 Checking...")

    result = await call_gateway(tool_name, arguments)
    await webex_send_message(room_id, markdown=result)


# ---------------------------------------------------------------------------
# Webhook Handler
# ---------------------------------------------------------------------------

async def handle_webhook(request: web.Request) -> web.Response:
    """Handle incoming WebEx webhook events."""
    try:
        data = await request.json()
    except Exception:
        return web.Response(status=400, text="Invalid JSON")

    resource = data.get("resource", "")
    event = data.get("event", "")
    webhook_data = data.get("data", {})

    # Handle message created events
    if resource == "messages" and event == "created":
        person_email = webhook_data.get("personEmail", "")
        if person_email == BOT_EMAIL:
            return web.Response(status=200)  # Ignore bot's own messages

        message_id = webhook_data.get("id", "")
        room_id = webhook_data.get("roomId", "")

        try:
            message = await webex_get_message(message_id)
            text = message.get("text", "").strip()
            # Remove bot mention prefix in group rooms
            if text.startswith("MIGA"):
                text = text[4:].strip()
            if not text:
                return web.Response(status=200)

            # Direct gateway_health phrasing (no NLP intent maps to gateway_health).
            if _is_gateway_health_query(text):
                await webex_send_message(room_id, text="🔍 Checking...")
                await webex_send_message(room_id, markdown=await call_gateway("gateway_health"))
                return web.Response(status=200)

            intent = recognize_intent(text)
            logger.info(
                "Intent: %s (%.0f%%) platform=%s from=%s",
                intent.category.value, intent.confidence * 100,
                intent.platform, person_email,
            )
            await handle_intent(intent, room_id)

        except Exception as e:
            logger.error("Error processing message: %s", e)
            await webex_send_message(room_id, text=f"❌ Internal error: {e}")

    # Handle Adaptive Card submissions (approval responses)
    elif resource == "attachmentActions" and event == "created":
        action_id = webhook_data.get("id", "")
        try:
            resp = await http_client.get(
                f"{WEBEX_API}/attachment/actions/{action_id}",
                headers={"Authorization": f"Bearer {BOT_TOKEN}"},
            )
            resp.raise_for_status()
            action_data = resp.json()
            inputs = action_data.get("inputs", {})
            room_id = action_data.get("roomId", webhook_data.get("roomId", ""))

            action = inputs.get("action", "")
            approval_id = inputs.get("approval_id", "")

            if action in ("approve", "reject"):
                status = "✅ Approved" if action == "approve" else "❌ Rejected"
                await webex_send_message(room_id, markdown=f"**{status}** — Approval `{approval_id[:8]}...`")
                # NOTE: HITL release is NOT yet wired. The bot acknowledges the decision,
                # but there is no consumer that holds a pending action and releases it on
                # this decision (redis_bus has request_approval() to publish a request,
                # but no approval-response subscriber). The credential-free demo is
                # read-only and does not exercise this path. README marks
                # automation/approval as partial. Do not present this as a closed loop.

        except Exception as e:
            logger.error("Error processing card action: %s", e)

    return web.Response(status=200)


# ---------------------------------------------------------------------------
# Health Endpoint
# ---------------------------------------------------------------------------

async def handle_health(request: web.Request) -> web.Response:
    return web.json_response({"service": "miga_webex_bot", "status": "healthy"})


# ---------------------------------------------------------------------------
# App Factory
# ---------------------------------------------------------------------------

def create_app() -> web.Application:
    app = web.Application()
    app.router.add_post("/webhooks/webex", handle_webhook)
    app.router.add_get("/health", handle_health)
    return app


if __name__ == "__main__":
    port = int(os.getenv("WEBEX_BOT_PORT", "9000"))
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=port)
