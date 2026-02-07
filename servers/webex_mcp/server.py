"""Webex MCP Server — Meeting Intelligence, AI Assistant, Messaging & Spaces.

Dual role: Managed platform AND user interface channel.
Roles: Automation, Observability
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Optional

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from miga_shared.agntcy import OASFRecord
from miga_shared.clients import CiscoAPIClient
from miga_shared.models import MIGARole, PlatformCapability, PlatformType
from miga_shared.server_base import add_health_tool, miga_lifespan
from miga_shared.utils.formatters import Fmt

OASF = OASFRecord(
    name="webex_mcp",
    description="Cisco Webex meeting intelligence, AI Assistant, and messaging",
    platform=PlatformType.WEBEX,
    roles=[MIGARole.AUTOMATION, MIGARole.OBSERVABILITY],
    skills=["meeting_analytics", "ai_assistant", "space_management", "messaging", "people_search"],
    domains=["collaboration", "meetings", "messaging"],
    endpoint=f"http://webex-mcp:{os.getenv('WEBEX_MCP_PORT', '8004')}",
    capabilities=[
        PlatformCapability(tool_name="webex_meeting_analytics", description="Meeting quality and AI summaries", roles=[MIGARole.OBSERVABILITY], platform=PlatformType.WEBEX),
        PlatformCapability(tool_name="webex_list_spaces", description="List Webex spaces/rooms", roles=[MIGARole.OBSERVABILITY], platform=PlatformType.WEBEX),
        PlatformCapability(tool_name="webex_send_message", description="Send message to a space", roles=[MIGARole.AUTOMATION], read_only=False, platform=PlatformType.WEBEX),
        PlatformCapability(tool_name="webex_people_search", description="Search for people in org", roles=[MIGARole.OBSERVABILITY], platform=PlatformType.WEBEX),
        PlatformCapability(tool_name="webex_list_recordings", description="List meeting recordings", roles=[MIGARole.OBSERVABILITY], platform=PlatformType.WEBEX),
    ],
)


@asynccontextmanager
async def lifespan():
    async with miga_lifespan(OASF, CiscoAPIClient.for_webex) as state:
        yield state

mcp = FastMCP("webex_mcp", lifespan=lifespan)
add_health_tool(mcp, PlatformType.WEBEX, "webex")


class MeetingAnalyticsIn(BaseModel):
    meeting_id: Optional[str] = None
    from_date: Optional[str] = Field(default=None, description="ISO date e.g. 2025-01-01")
    to_date: Optional[str] = None
    max_results: int = Field(default=20, ge=1, le=100)

class SpaceListIn(BaseModel):
    team_id: Optional[str] = None
    max_results: int = Field(default=30, ge=1, le=100)
    sort_by: str = Field(default="lastactivity", description="lastactivity or created")

class SendMessageIn(BaseModel):
    room_id: str = Field(..., min_length=1)
    text: Optional[str] = None
    markdown: Optional[str] = None

class PeopleSearchIn(BaseModel):
    display_name: Optional[str] = None
    email: Optional[str] = None
    max_results: int = Field(default=10, ge=1, le=50)

class RecordingsIn(BaseModel):
    from_date: Optional[str] = None
    to_date: Optional[str] = None
    max_results: int = Field(default=20, ge=1, le=100)


@mcp.tool(name="webex_meeting_analytics", annotations={"readOnlyHint": True})
async def meeting_analytics(params: MeetingAnalyticsIn, ctx=None) -> str:
    """Get meeting quality metrics and AI-generated summaries."""
    api: CiscoAPIClient = ctx.request_context.lifespan_state["api"]

    qp = {"max": params.max_results}
    if params.from_date: qp["from"] = params.from_date
    if params.to_date: qp["to"] = params.to_date

    data = await api.get("/meetings", params=qp)
    meetings = data.get("items", [])

    if not meetings:
        return "_No meetings found in the specified range._"

    lines = [f"## Meeting Analytics ({len(meetings)})\n"]
    for m in meetings[:20]:
        title = m.get("title", "Untitled")
        start = Fmt.ts(m.get("start"))
        duration = m.get("durationMinutes", "?")
        host = m.get("hostDisplayName", m.get("hostEmail", "?"))
        lines.append(f"- 📅 **{title}** — {start} ({duration} min, host: {host})")
    return "\n".join(lines)


@mcp.tool(name="webex_list_spaces", annotations={"readOnlyHint": True})
async def list_spaces(params: SpaceListIn, ctx=None) -> str:
    """List Webex spaces/rooms the bot has access to."""
    api: CiscoAPIClient = ctx.request_context.lifespan_state["api"]
    qp = {"max": params.max_results, "sortBy": params.sort_by}
    if params.team_id: qp["teamId"] = params.team_id

    data = await api.get("/rooms", params=qp)
    rooms = data.get("items", [])

    if not rooms:
        return "_No spaces found._"

    rows = [[r.get("title", "?"), r.get("type", ""), Fmt.ts(r.get("lastActivity"))] for r in rooms[:30]]
    return f"## Spaces ({len(rooms)})\n\n{Fmt.md_table(['Name', 'Type', 'Last Active'], rows)}"


@mcp.tool(name="webex_send_message", annotations={"readOnlyHint": False})
async def send_message(params: SendMessageIn, ctx=None) -> str:
    """Send a message to a Webex space."""
    api: CiscoAPIClient = ctx.request_context.lifespan_state["api"]
    payload = {"roomId": params.room_id}
    if params.markdown:
        payload["markdown"] = params.markdown
    elif params.text:
        payload["text"] = params.text
    else:
        return "Error: Provide either text or markdown content."

    data = await api.post("/messages", json_data=payload)
    return f"✅ Message sent to space `{params.room_id}` (ID: {data.get('id', '?')})"


@mcp.tool(name="webex_people_search", annotations={"readOnlyHint": True})
async def people_search(params: PeopleSearchIn, ctx=None) -> str:
    """Search for people in the Webex organization."""
    api: CiscoAPIClient = ctx.request_context.lifespan_state["api"]
    qp = {"max": params.max_results}
    if params.display_name: qp["displayName"] = params.display_name
    if params.email: qp["email"] = params.email

    data = await api.get("/people", params=qp)
    people = data.get("items", [])

    if not people:
        return "_No matching people found._"

    rows = [[p.get("displayName", "?"), ", ".join(p.get("emails", [])), p.get("orgId", "")[:12] + "…"] for p in people]
    return f"## People Search ({len(people)})\n\n{Fmt.md_table(['Name', 'Email', 'Org'], rows)}"


@mcp.tool(name="webex_list_recordings", annotations={"readOnlyHint": True})
async def list_recordings(params: RecordingsIn, ctx=None) -> str:
    """List available meeting recordings."""
    api: CiscoAPIClient = ctx.request_context.lifespan_state["api"]
    qp = {"max": params.max_results}
    if params.from_date: qp["from"] = params.from_date
    if params.to_date: qp["to"] = params.to_date

    data = await api.get("/recordings", params=qp)
    recs = data.get("items", [])

    if not recs:
        return "_No recordings found._"

    lines = [f"## Recordings ({len(recs)})\n"]
    for r in recs[:20]:
        title = r.get("topic", "Untitled")
        dur = r.get("durationSeconds", 0) / 60
        lines.append(f"- 🎥 **{title}** — {dur:.0f} min ({Fmt.ts(r.get('createTime'))})")
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="streamable_http", port=int(os.getenv("WEBEX_MCP_PORT", "8004")))
