# MIGA Architecture

## Design Principles

1. **Aggregation over reimplementation** — MIGA does not reimplement platform
   integrations. The platform layer is made of **real, published MCP servers**.
   The gateway connects to each as an MCP **client** over its native transport and
   provides role-based abstractions on top. MIGA's only original server is INFER.

2. **Config-driven, dynamic discovery** — No hardcoded routing or endpoints.
   `config/server-registry.yaml` (validated against its JSON schema) is the single
   source of truth for *how to connect*. Each server publishes an OASF record to the
   AGNTCY Directory so capabilities are discoverable; the gateway refreshes the
   registry periodically.

3. **Intelligence layer** — INFER produces cross-platform insights (root cause
   analysis, anomaly correlation, predictive failure analysis) that no single
   platform can generate alone.

4. **Conversation-first** — Webex Bot embeds NLP intent recognition to convert
   natural language into MCP tool calls, with results rendered as Adaptive Cards.

## Component Overview

### Gateway (Python / FastMCP)

The Gateway is an MCP server that exposes 6 role-based meta-tools. Each
meta-tool fans out to relevant platform servers based on AGNTCY OASF
capability records.

**Roles:**
- Observability — health, telemetry, monitoring
- Security — threats, incidents, enforcement
- Automation — command execution, remediation
- Configuration — device configs, topology, policies
- Compliance — posture, drift, audit, certificates
- Identity — sessions, authentication, profiling

### External Platform MCP Servers (the platform layer)

The 8 platform servers are **external, published MCP servers** — MIGA routes to
them; it does not host their logic. They are reached through the gateway's MCP
client transport abstraction (`miga_shared/transport.py`):

- **HTTP/SSE** — remote managed endpoints (ThousandEyes, Splunk) and compose-hosted
  servers (Meraki, ISE, NetBox) over Streamable HTTP at their `/mcp` endpoints.
- **stdio** — spawned subprocesses: the `docker run -i` pattern (SD-WAN) and bundled
  local processes (Catalyst Center via `fastmcp run`, ServiceNow via `python -m`).

`miga_shared/registry.py` loads and validates the registry, resolves `${ENV}`
placeholders, and yields typed `ServerSpec` objects. The gateway maps roles to
servers and forwards `tools/list` / `tools/call` — no upstream code is vendored.

### INFER (Intelligence Engine)

Subscribes to all platform telemetry via Redis pub/sub. Performs:
- **Event correlation** — Groups related events by entity overlap + time window
- **Root cause analysis** — Matches against expert-curated RCA templates
- **Anomaly detection** — Statistical frequency analysis (v1), isolation forests (v2)
- **Predictive analysis** — Pattern matching against historical incidents
- **Risk scoring** — Composite 0-100 network risk score

### Webex Bot

- Webhook-based: receives messages from Webex, processes NLP, calls Gateway
- Hybrid NLP: regex patterns for common commands, LLM fallback for ambiguity
- Adaptive Cards for rich interactive UI (health dashboards, approval forms)
- Human-in-the-loop: destructive actions surface approval cards before execution

## Data Flow

```
User → Webex Message → Bot Webhook → NLP Intent
  → Gateway MCP Call → role → registered servers (registry)
  → MCP client transport (HTTP/SSE or stdio) → upstream MCP servers
  → Results → Gateway aggregation → Markdown/Card → Webex Response

Normalized server output → Redis pub/sub → INFER subscription
  → Correlation/Analysis → Published insights
  → Gateway surfaces via meta-tools
```

## Security Model

| Layer | Mechanism |
|-------|-----------|
| External auth | Entra ID JWT (OAuth 2.0) |
| Inter-service | AGNTCY Identity Badges |
| Transport | TLS (mTLS in production) |
| Authorization | Role-based (RBAC) per tool |
| Destructive ops | Human-in-the-loop approval |
| Audit | Immutable log with UPN + correlation IDs |
| Secrets | K8s Secrets / Docker env vars |

## AGNTCY Integration

| Component | v1 Status | Purpose |
|-----------|-----------|---------|
| OASF | ✅ Implemented | Structured capability records |
| Agent Directory | ✅ Implemented | Dynamic peer-to-peer discovery |
| Identity | ✅ Implemented | Cryptographic server verification |
| SLIM | 🔲 v2 | Quantum-safe agent messaging |
| Observability | 🔲 v2 | OpenTelemetry distributed tracing |

## Scaling

- **Horizontal:** Each MCP server scales independently (Helm replicas)
- **Gateway:** Stateless, scale to N replicas behind load balancer
- **INFER:** CPU-bound, scale vertically or add worker pool
- **Redis:** Sentinel/Cluster for HA in production
- **Event bus:** Redis pub/sub (v1) → AGNTCY SLIM (v2) for larger scale

## Port Allocation

MIGA-owned services use fixed ports. External servers are reached per the registry:
remote servers by URL, compose servers on their internal `/mcp` ports, and stdio
servers over a spawned subprocess (no port).

| Service | Port / Reach |
|---------|--------------|
| Gateway | 8000 |
| INFER (MIGA-original) | 8007 |
| Webex Bot | 9000 |
| Redis | 6379 |
| AGNTCY Directory | 8500 |
| Cisco Meraki (compose) | 8000/mcp (internal) |
| Cisco ISE (compose) | 8005/mcp (internal) |
| NetBox (compose) | 8000/mcp (internal) |
| Cisco ThousandEyes (remote) | https://api.thousandeyes.com/mcp |
| Splunk (remote) | https://${SPLUNK_HOST}:8089/services/mcp |
| Cisco Catalyst SD-WAN | stdio — `docker run -i catalyst-sdwan-mcp:latest` |
| Cisco Catalyst Center | stdio — `fastmcp run catalyst-center-mcp.py` |
| ServiceNow | stdio — `python -m servicenow_mcp.cli` |
