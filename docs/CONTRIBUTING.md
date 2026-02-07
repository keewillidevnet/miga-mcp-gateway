# Contributing to MIGA

Thank you for your interest in contributing to MIGA! This project is designed
to make contribution easy — especially for implementing stub servers.

## Quick Start

```bash
git clone https://github.com/your-org/miga.git && cd miga
cp .env.example .env
docker compose up -d
```

## Implementing a Stub Server

The fastest way to contribute is to implement one of the 6 stubbed platform
servers. Each stub already has:

- ✅ Typed tool signatures (Pydantic input models)
- ✅ OASF capability record (auto-registers with AGNTCY Directory)
- ✅ Lifecycle management (Redis, health check, Directory registration)
- ✅ Mock response data (shows expected output format)
- ✅ Docker Compose service definition

**Available stubs:**

| Server | File | Platform Docs |
|--------|------|--------------|
| AppDynamics | `servers/appdynamics_mcp/server.py` | [AppDynamics API](https://docs.appdynamics.com/latest/en/extend-appdynamics/appdynamics-apis) |
| Nexus Dashboard | `servers/nexus_dashboard_mcp/server.py` | [ND API](https://developer.cisco.com/docs/nexus-dashboard/) |
| SD-WAN | `servers/sdwan_mcp/server.py` | [SD-WAN API](https://developer.cisco.com/docs/sdwan/) |
| ISE | `servers/ise_mcp/server.py` | [ISE ERS API](https://developer.cisco.com/docs/identity-services-engine/) |
| Splunk | `servers/splunk_mcp/server.py` | [Splunk REST API](https://docs.splunk.com/Documentation/Splunk/latest/RESTREF/) |
| Hypershield | `servers/hypershield_mcp/server.py` | [Hypershield Docs](https://www.cisco.com/c/en/us/products/security/hypershield/) |

### Step-by-Step

1. **Pick a stub** from the table above
2. **Read the existing stub** to understand the tool signatures and mock data
3. **Add the API client factory** to `miga_shared/clients/__init__.py`:
   ```python
   @classmethod
   def for_appdynamics(cls) -> CiscoAPIClient:
       return cls(
           base_url=os.getenv("APPDYNAMICS_CONTROLLER_URL", ""),
           headers={"Authorization": f"Bearer {os.getenv('APPDYNAMICS_API_KEY', '')}"},
           platform_name="appdynamics",
       )
   ```
4. **Replace mock data with real API calls** in each tool function
5. **Publish events to Redis** for INFER correlation (see existing servers for pattern)
6. **Test locally**:
   ```bash
   # Add your credentials to .env
   docker compose up -d appdynamics-mcp
   # Or include stubs: docker compose --profile stubs up -d
   ```
7. **Submit a PR** — we'll review and merge!

### Tool Implementation Pattern

Every tool follows the same pattern used by the fully-implemented servers:

```python
@mcp.tool(name="platform_get_something", annotations={"readOnlyHint": True})
async def get_something(params: SomeInput, ctx=None) -> str:
    # 1. Get API client from lifespan state
    api: CiscoAPIClient = ctx.request_context.lifespan_state["api"]
    bus: RedisPubSub = ctx.request_context.lifespan_state["bus"]

    # 2. Call the platform API
    data = await api.get("/some/endpoint", params={...})

    # 3. Publish events for INFER (if applicable)
    await bus.publish_telemetry("platform_name", {"type": "event_type", "data": data})

    # 4. Format and return Markdown response
    return f"## Result\n\n{Fmt.table(headers, rows)}"
```

## Adding a New Platform

To add an entirely new platform server (not one of the existing stubs):

1. Create `servers/your_platform_mcp/server.py`
2. Define an `OASFRecord` with capabilities, roles, and skills
3. Use `miga_lifespan()` for standard lifecycle
4. Add `add_health_tool()` for health checks
5. Add Docker Compose service in `docker-compose.yml`
6. Add the platform to `PlatformType` enum in `miga_shared/models.py`
7. Add API client factory in `miga_shared/clients/__init__.py`

The Gateway will automatically discover your new server via AGNTCY Directory
— no Gateway code changes required.

## Code Style

- Python 3.11+
- Ruff for linting and formatting (`ruff check .` and `ruff format .`)
- Type hints on all public functions
- Pydantic models for all tool inputs
- Docstrings on all tools (shown to MCP clients)

## Testing

```bash
pytest tests/ -v
```

## Commit Messages

Use conventional commits: `feat(meraki): add wireless channel utilization tool`

## License

By contributing, you agree that your contributions will be licensed under
the Apache 2.0 License.
