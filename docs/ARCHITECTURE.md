# MIGA Architecture

## Design Principles

1. **Platform-based decomposition** — Each Cisco platform gets a dedicated MCP
   server handling all operational roles for that platform. The Gateway provides
   role-based abstractions on top.

2. **Dynamic discovery** — No hardcoded routing. Servers register OASF records
   with the AGNTCY Directory; the Gateway discovers capabilities at startup
   and refreshes periodically.

3. **Intelligence layer** — INFER produces cross-platform insights (root cause
   analysis, anomaly correlation, predictive failure analysis) that no single
   platform can generate alone.

4. **Conversation-first** — WebEx Bot embeds NLP intent recognition to convert
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

### Platform MCP Servers

Each server wraps a single Cisco platform's REST API, exposing tools via
FastMCP with Pydantic-typed inputs and Markdown-formatted outputs.

**Shared infrastructure per server:**
- `miga_lifespan()` — Redis connect, AGNTCY register, health tool
- `CiscoAPIClient` — Retry, rate-limit, auth injection
- Event publishing to Redis for INFER consumption

### INFER (Intelligence Engine)

Subscribes to all platform telemetry via Redis pub/sub. Performs:
- **Event correlation** — Groups related events by entity overlap + time window
- **Root cause analysis** — Matches against expert-curated RCA templates
- **Anomaly detection** — Statistical frequency analysis (v1), isolation forests (v2)
- **Predictive analysis** — Pattern matching against historical incidents
- **Risk scoring** — Composite 0-100 network risk score

### WebEx Bot

- Webhook-based: receives messages from WebEx, processes NLP, calls Gateway
- Hybrid NLP: regex patterns for common commands, LLM fallback for ambiguity
- Adaptive Cards for rich interactive UI (health dashboards, approval forms)
- Human-in-the-loop: destructive actions surface approval cards before execution

## Data Flow

```
User → WebEx Message → Bot Webhook → NLP Intent
  → Gateway MCP Call → Fan out to Platform Servers
  → Platform API calls → Results → Gateway aggregation
  → Markdown/Card → WebEx Response

Platform Events → Redis pub/sub → INFER subscription
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

| Service | Port |
|---------|------|
| Gateway | 8000 |
| Catalyst Center | 8001 |
| Meraki | 8002 |
| ThousandEyes | 8003 |
| Webex | 8004 |
| XDR | 8005 |
| Security Cloud Control | 8006 |
| INFER | 8007 |
| AppDynamics (stub) | 8008 |
| Nexus Dashboard (stub) | 8009 |
| SD-WAN (stub) | 8010 |
| ISE (stub) | 8011 |
| Splunk (stub) | 8012 |
| Hypershield (stub) | 8013 |
| WebEx Bot | 9000 |
| Redis | 6379 |
| AGNTCY Directory | 8500 |
