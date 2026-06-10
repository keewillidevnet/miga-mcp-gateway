# MIGA - MCP Intelligence Gateway Architecture
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-green.svg)](https://python.org)
[![MCP](https://img.shields.io/badge/MCP-Streamable%20HTTP%20%2B%20stdio-purple.svg)](https://modelcontextprotocol.io)
[![AGNTCY](https://img.shields.io/badge/AGNTCY-aligned-orange.svg)](https://agntcy.org)
[![Servers](https://img.shields.io/badge/Registered%20Servers-9-red.svg)](#platform-coverage)
[![Code Style](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![Cisco Code Exchange](https://img.shields.io/badge/Cisco-Code%20Exchange-00bceb.svg)](https://developer.cisco.com/codeexchange/)
[![published](https://static.production.devnetcloud.com/codeexchange/assets/images/devnet-published.svg)](https://developer.cisco.com/codeexchange/github/repo/keewillidevnet/miga-mcp-gateway)
[![Run in Cisco Cloud IDE](https://static.production.devnetcloud.com/codeexchange/assets/images/devnet-runable-icon.svg)](https://developer.cisco.com/codeexchange/devenv/keewillidevnet/miga-mcp-gateway/)
[![Cisco Developed](https://static.production.devnetcloud.com/codeexchange/assets/images/cisco-developed.svg)](https://developer.cisco.com/codeexchange/github/repo/keewillidevnet/miga-mcp-gateway)



> A unified intelligence layer that **aggregates and fuses** AI/ML and operational
> data from real, published MCP servers across the network ecosystem into a single,
> consistent, role-based interface for analysis, automation, and decision support —
> with a conversational WebEx Chat interface.

---

## Overview

Modern enterprise networks span many platforms — Cisco ThousandEyes, Splunk, Cisco
Meraki, Catalyst SD-WAN, Catalyst Center, ISE, ServiceNow, NetBox, and more. Each
exposes its own MCP server, telemetry, and access model. **MIGA is the aggregation
and fusion layer over that ecosystem.** Rather than reimplementing platform
integrations, the MIGA gateway connects to each platform's *real, published MCP
server* as an MCP **client**, routes by role, and adds cross-platform reasoning that
no single platform can provide.

Users interact conversationally through a **WebEx Bot** that embeds an MCP Client,
converting natural language into structured MCP tool calls via an NLP pipeline, with
results rendered as rich Adaptive Cards.

The **INFER** (Infrastructure Network Fusion Engine for Reasoning) service — MIGA's
one original server — continuously ingests the normalized output of the registered
servers to perform predictive analysis, root cause analysis, anomaly correlation,
and risk scoring across platforms.

## Architecture

```
┌────────────────────────────────────────────────────────────────────────────┐
│                             WebEx Bot (Python)                             │
│             NLP Intent -> MCP Client -> Adaptive Cards -> HITL             │
│                     [AGNTCY Identity Badge — planned]                      │
└────────────────────────────────────────────────────────────────────────────┘
                                       │                                      
                                       │ JSON-RPC 2.0 (MCP)
                                       ▼                                      
┌────────────────────────────────────────────────────────────────────────────┐
│                        Gateway MCP Server (Python)                         │
│           Registry-driven routing  (config/server-registry.yaml)           │
│          OASF records · AGNTCY Directory publish: live (verified)          │
│               6 Roles: Observability | Security | Automation               │
│                   Configuration | Compliance | Identity                    │
│        MCP CLIENT transports: HTTP/SSE URLs + stdio (docker run -i)        │
└────────────────────────────────────────────────────────────────────────────┘
         │                   │                   │                   │        
         ▼                   ▼                   ▼                   ▼        
┌────────────────┐  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐
│  ThousandEyes  │  │     Splunk     │  │     Meraki     │  │     SD-WAN     │
│     Cisco      │  │                │  │     Cisco      │  │     Cisco      │
│  remote·http   │  │  remote·http   │  │  compose·http  │  │  docker·stdio  │
└────────────────┘  └────────────────┘  └────────────────┘  └────────────────┘

┌────────────────┐  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐
│    Catalyst    │  │   ServiceNow   │  │      ISE       │  │     NetBox     │
│     Center     │  │                │  │     Cisco      │  │   read-only    │
│  local·stdio   │  │  local·stdio   │  │  compose·http  │  │  compose·http  │
└────────────────┘  └────────────────┘  └────────────────┘  └────────────────┘

All 8 servers + INFER have authored OASF records (validated against OASF 1.0.0).
Routing is registry-driven; OASF records are published to a real AGNTCY Directory
(verified live: 9/9, CIDs, pull-by-CID at schema_version 1.0.0).
INFER consumes their normalized output:

┌────────────────────────────────────────────────────────────────────────────┐
│                   INFER — Fusion Engine (MIGA-original)                    │
│         Correlation · Root Cause · Anomaly · Predict · Risk Score          │
└────────────────────────────────────────────────────────────────────────────┘
```

The gateway never re-vendors upstream server logic. It opens an MCP client session
over each server's native transport (declared in the registry) and forwards
`tools/list` / `tools/call`. Connection details are **config-driven**, never
hardcoded.

## Quick Start

```bash
# Clone the repository
git clone https://github.com/keewillidevnet/miga-mcp-gateway.git && cd miga-mcp-gateway

# Copy environment template and add your credentials (grouped by platform)
cp .env.example .env

# Build the external community server images referenced by docker-compose
# (Meraki, ISE, NetBox, SD-WAN) from their upstream repos — see MIGRATION.md.

# Launch core + compose-deployed servers
docker compose up -d

# Check status (reachability of every registered server)
python -m packages.cli.miga_cli status

# Open WebEx and message the MIGA bot!
```

## Project Structure

```
miga-mcp-gateway/
├── config/
│   ├── server-registry.yaml         # Authoritative: how the gateway connects to each server
│   └── server-registry.schema.json  # JSON schema the registry is validated against
├── oasf/
│   ├── OASF_RECORDS.md              # OASF record authoring guide
│   └── records/*.record.json        # One OASF capability record per registered server
├── miga_shared/
│   ├── registry.py                  # Registry loader (parse, validate, resolve ${ENV})
│   ├── transport.py                 # MCP client transport: HTTP/SSE + stdio (docker run -i)
│   └── ...                          # auth, AGNTCY, models, formatters
├── packages/
│   ├── gateway/                     # Gateway MCP Server (registry-driven role routing)
│   ├── webex_bot/                   # WebEx Bot (NLP + MCP Client + Adaptive Cards)
│   └── cli/                         # miga-cli tool
├── servers/
│   └── infer_mcp/                   # INFER fusion engine — MIGA's only original server
├── helm/miga/                       # Helm chart (gateway, bot, INFER)
├── docs/                            # Documentation
├── docker-compose.yml               # Local cluster (core + compose servers)
└── .env.example                     # Environment template (every registry env var)
```

## Platform Coverage

The gateway routes to **8 real external MCP servers** plus the MIGA-original INFER
engine. Connection details for every row live in `config/server-registry.yaml`.

| Platform | Status | Source / Endpoint | Roles Served |
|----------|--------|-------------------|--------------|
| Cisco ThousandEyes | Official | `api.thousandeyes.com/mcp` (remote HTTP) | Observability |
| Splunk | Official | Splunk instance `:8089/services/mcp` (remote HTTP) | Observability, Security |
| Cisco Meraki | CiscoDevNet community | [CiscoDevNet/meraki-magic-mcp-community](https://github.com/CiscoDevNet/meraki-magic-mcp-community) | Observability, Configuration, Security |
| Cisco Catalyst SD-WAN | CiscoDevNet community | [CiscoDevNet/catalyst-sdwan-mcp-community](https://github.com/CiscoDevNet/catalyst-sdwan-mcp-community) (docker stdio) | Configuration, Automation |
| Cisco Catalyst Center | Community | [richbibby/catalyst-center-mcp](https://github.com/richbibby/catalyst-center-mcp) (stdio) | Observability, Configuration, Automation |
| Cisco ISE | Community | [pamosima/network-mcp-docker-suite](https://github.com/pamosima/network-mcp-docker-suite) (upstream [automateyournetwork/ISE_MCP](https://github.com/automateyournetwork/ISE_MCP)) | Identity, Compliance |
| ServiceNow | Community | [echelon-ai-labs/servicenow-mcp](https://github.com/echelon-ai-labs/servicenow-mcp) (stdio) | Automation, Observability |
| NetBox | Official (NetBox Labs) | [netboxlabs/netbox-mcp-server](https://github.com/netboxlabs/netbox-mcp-server) (read-only) | Configuration, Compliance |
| INFER | MIGA-original | `servers/infer_mcp` | Observability, Security, Compliance |

## Use Case Scenarios

### 🚨 NOC / Incident Response

A network engineer gets paged at 2 AM. Instead of logging into four different dashboards, they open WebEx on their phone:

> **Engineer:** `network status`

MIGA fans out across Catalyst Center, Meraki, ThousandEyes, and Splunk simultaneously, returning a single health card with scores, top issues, and active alerts. ThousandEyes is flagging packet loss on a WAN path.

> **Engineer:** `correlate events last 30 minutes`

INFER finds the ThousandEyes path loss overlaps with a Meraki VPN tunnel flap and a Catalyst Center device error, all affecting the same branch site. It returns a root cause analysis card pointing to a failing upstream switch with recommended actions.

> **Engineer:** `run show interface gi1/0/1 on switch-br-01`

The bot presents an **approval card**. The on-call lead taps ✅ **Approve**. The command executes through Catalyst Center and results render inline. Total time: **3 minutes, never left WebEx.**

---

### 🔒 Security Operations

A SOC analyst opens the Network Security WebEx space:

> **Analyst:** `critical security events`

Splunk returns active detections from the SIEM, and Meraki flags anomalous appliance traffic.

> **Analyst:** `risk score`

INFER calculates a composite **78/100** — the top contributor is an endpoint with repeated authentication failures correlated against a Splunk alert.

> **Analyst:** `quarantine endpoint AA:BB:CC:DD:EE:01`

An approval card fires to the security lead. One tap — Cisco ISE isolates the device. The entire **triage-to-containment loop** happened in a WebEx space without touching a single console.

---

### 🔧 Change Management / Maintenance Windows

> **Change Manager:** `predict failures`

INFER analyzes recent telemetry patterns and flags that three switches in Building C have incrementing CRC errors, suggesting a cascading failure risk.

> **Change Manager:** `compare network health before and after`

The bot pulls Catalyst Center health scores and ThousandEyes test baselines, showing the change improved path latency by 12ms with no new issues.

---

### ✅ Compliance Auditing

> **Auditor:** `compliance posture`

Cisco ISE returns endpoint posture stats, NetBox supplies source-of-truth inventory and change history, and INFER calculates drift from baseline. The auditor has **exportable evidence** without requesting access to any platform.

---

### 🎫 Closed-Loop Incident Management (ServiceNow)

INFER detects a correlated branch outage across ThousandEyes, Meraki, and Catalyst Center:

> **MIGA Bot:** 🔴 **Correlated incident detected:** WAN degradation at Site-A — 3 platforms affected, root cause: upstream circuit CKT-00412 packet loss.

The bot auto-creates a ServiceNow P1 incident with the full RCA attached.

> **Engineer:** `status INC0078432`

The bot pulls the live ticket: assigned to Network Operations, provider ticket open.

> **Engineer:** `resolve INC0078432 — Lumen fiber repair completed, circuit stable`

MIGA updates the ServiceNow ticket with resolution notes, INFER confirms health scores recovered, and the incident closes. **Full lifecycle — detection to resolution — in one WebEx thread.**

---

### 🗺️ Infrastructure Context & Impact Analysis (NetBox)

INFER flags an anomaly on `10.1.50.1`. Without NetBox, that's just an IP address. With NetBox:

> **Engineer:** `what is 10.1.50.1?`

NetBox resolves it: **Core Switch 3** — Catalyst 9300-48P, Rack 14, Building C, serial FCW2345L0AB, running IOS-XE 17.09.04a.

> **Engineer:** `what's the blast radius?`

NetBox maps the relationships: 3 downstream access switches serving **240 users**, upstream WAN edge on Lumen circuit CKT-00412. The engineer now knows this is a high-impact event before a single user calls the help desk.

---

## AGNTCY Integration

MIGA is built to **align with** Cisco's [AGNTCY](https://agntcy.org) Internet of
Agents framework (Linux Foundation). Honest status of each piece:

- **OASF — implemented (verified live).** Each registered server has an authored OASF
  capability record under `oasf/records/*.record.json` (all nine validate against the
  canonical OASF **1.0.0** schema server with **0 errors / 0 warnings**). At startup the
  gateway publishes all **9/9** records to a real AGNTCY Directory (`dir-apiserver`, via
  the `agntcy-dir` 1.3.0 SDK), each returning a content-addressed **CID**, and records
  **pull back by CID** at `schema_version` 1.0.0 — confirmed on a networked Docker host
  (see `VERIFY_DIRECTORY.md`).
- **Directory publication — implemented (verified live); discovery-based routing — planned.**
  The gateway publishes OASF records to the real AGNTCY **Agent Directory** via the
  `agntcy-dir` Python SDK (native gRPC; no `dirctl` at runtime); publication is
  best-effort and falls back to standalone if the directory is unreachable. **Routing is
  driven entirely by `config/server-registry.yaml`** (loaded at startup + periodically
  reloaded), so adding a server is picked up with no code change. Using the directory's
  *search/discovery* to drive routing is **planned** — routing does not yet depend on
  the directory.
- **Identity (Agent Badges) — planned.** A scaffolding `IdentityBadge` type exists,
  but it performs no cryptographic signing or verification yet (`verify()` only
  checks for field presence). Treat verifiable agent identity as planned, not built.
- **SLIM — planned (v2).** Inter-service messaging currently uses Redis pub/sub;
  quantum-safe AGNTCY SLIM is a future item.
- **Observability — planned (v2).** No OpenTelemetry tracing is wired today.

> **Verified live:** on a networked Docker host the gateway loaded 9 specs and published
> **9/9** OASF capability records to a real AGNTCY Directory (`dir-apiserver` + `zot` +
> `postgres` + `reconciler`) via the `agntcy-dir` 1.3.0 SDK, each returning a CID, with
> a pull-by-CID round-trip at `schema_version` 1.0.0 (see `VERIFY_DIRECTORY.md`). Still
> **planned**: cryptographic Agent Badges, SLIM (v2), OpenTelemetry (v2), and
> directory-search-based routing discovery.

**What is real and load-bearing:** a registry-driven gateway fronting 8 real external
MCP servers plus INFER, with a validated OASF 1.0.0 capability record per server.

## Deployment

**Local Development (Docker Compose):**
```bash
docker compose up -d
```

**Production (Kubernetes + Helm):**
```bash
helm install miga ./helm/miga --namespace miga --create-namespace
```
(The Helm chart deploys the gateway, WebEx bot, and INFER. External platform
servers are provisioned out-of-band and referenced via the registry.)

**CLI Tool:**
```bash
python -m packages.cli.miga_cli status
```

## Contributing

To add a platform: add an entry to `config/server-registry.yaml`, author its OASF
record under `oasf/records/`, and wire any env vars in `.env.example`. See
[docs/CONTRIBUTING.md](docs/CONTRIBUTING.md).

## License

Apache 2.0 — See [LICENSE](LICENSE)
