[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-green.svg)](https://python.org)
[![MCP](https://img.shields.io/badge/MCP-Streamable%20HTTP-purple.svg)](https://modelcontextprotocol.io)
[![AGNTCY](https://img.shields.io/badge/AGNTCY-Native-orange.svg)](https://agntcy.org)
[![Platforms](https://img.shields.io/badge/Platforms-15-red.svg)](#platform-coverage)
[![Code Style](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![Cisco Code Exchange](https://img.shields.io/badge/Cisco-Code%20Exchange-00bceb.svg)](https://developer.cisco.com/codeexchange/)

# MIGA - MCP Intelligence Gateway Architecture

> A unified intelligence layer that consolidates AI and ML data from multiple Cisco
> operational platforms into a single, consistent interface for analysis, automation,
> and decision support with conversational WebEx Chat integration.

---

## Overview

Modern enterprise networks run across dozens of Cisco platforms; Catalyst Center,
Meraki, ThousandEyes, AppDynamics, Webex, XDR, Hypershield, and more. Each platform
produces isolated telemetry and requires custom integrations. **MIGA solves this** by
exposing every platform's AI/ML capabilities through a scalable MCP (Model Context
Protocol) server cluster, enabling AI agents and automated workflows to operate with
complete context, consistent data quality, and a governed interaction model.

Users interact with the cluster conversationally through a **WebEx Bot** that embeds
an MCP Client, converting natural language into structured MCP tool calls via an NLP
pipeline with results rendered as rich Adaptive Cards.

The **INFER** (Infrastructure Network Fusion Engine for Reasoning) service continuously
ingests cross-platform telemetry to perform predictive analysis, root cause analysis,
anomaly correlation, and capacity planning that no individual platform can achieve alone.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     WebEx Bot (Python)                          │
│        NLP Intent → MCP Client → Adaptive Cards → HITL          │
│                   [AGNTCY Identity Badge]                       │
└──────────────────────────┬──────────────────────────────────────┘
                           │ JSON RPC 2.0
┌──────────────────────────▼──────────────────────────────────────┐
│                   Gateway MCP Server (Python)                   │
│   Dynamic routing via AGNTCY Directory + OASF capability lookup │
│   6 Role Categories: Observability │ Security │ Automation      │
│                      Configuration │ Compliance │ Identity      │
└──┬──────┬──────┬──────┬──────┬──────┬───────────────────────────┘
   │      │      │      │      │      │        MCP │
   ▼      ▼      ▼      ▼      ▼      ▼            ▼
┌─────┐┌─────┐┌─────┐┌─────┐┌─────┐┌──────┐  ┌──────────────┐
│CatC ││Mera-││Thou-││Webex││ XDR ││SecCld│  │    INFER     │
│     ││ki   ││sand-││     ││     ││Ctrl  │  │   Fusion     │
│     ││     ││Eyes ││     ││     ││      │  │   Engine     │
└──┬──┘└──┬──┘└──┬──┘└──┬──┘└──┬──┘└──┬───┘  │              │
   │      │      │      │      │      │      │  Correlation │
   └──────└──────┴──────┴──────┴──────┘      │  RCA         │
                       │                     │  Anomaly Det │
                 Redis pub/sub               │  Prediction  │
                       │                     │  Risk Score  │
                       └────────────────────▶│              │
                                             └──────────────┘
┌─────┐┌─────┐┌─────┐┌─────┐┌─────┐┌──────┐┌──────┐┌──────┐
│AppD ││Nexus││SDWAN││ ISE ││Splnk││Hyper ││ Snow ││NetBx │  ← Stubs
│(stb)││(stb)││(stb)││(stb)││(stb)││(stb) ││(stb) ││(stb) │
└─────┘└─────┘└─────┘└─────┘└─────┘└──────┘└──────┘└──────┘
   All registered in ──► AGNTCY Directory (ADS)
```

## Quick Start

```bash
# Clone the repository
git clone https://github.com/keewillidevnet/miga-mcp-gateway.git && cd miga-mcp-gateway

# Copy environment template and add your API credentials
cp .env.example .env

# Launch the full cluster (core services)
docker compose up -d

# Include stub servers too
docker compose --profile stubs up -d

# Check status
python -m packages.cli.miga_cli status

# Open WebEx and message the MIGA bot!
```

## Project Structure

```
miga-mcp-gateway/
├── miga_shared/             # Shared library (auth, AGNTCY, formatters, models)
├── packages/
│   ├── gateway/             # Gateway MCP Server (role-based routing)
│   ├── webex_bot/           # WebEx Bot (NLP + MCP Client + Adaptive Cards)
│   └── cli/                 # miga-cli deployment tool
├── servers/
│   ├── catalyst_center_mcp/ # Catalyst Center AI/ML         [Full]
│   ├── meraki_mcp/          # Meraki Dashboard AI/ML        [Full]
│   ├── thousandeyes_mcp/    # ThousandEyes AI Assurance     [Full]
│   ├── webex_mcp/           # Webex AI Assistant            [Full]
│   ├── xdr_mcp/             # Cisco XDR Threat Intel        [Full]
│   ├── security_cloud_control_mcp/  # Security Cloud Ctrl   [Full]
│   ├── infer_mcp/           # INFER Intelligence Engine     [Full]
│   ├── appdynamics_mcp/     # AppDynamics                   [Stub]
│   ├── nexus_dashboard_mcp/ # Nexus Dashboard               [Stub]
│   ├── sdwan_mcp/           # SD-WAN                        [Stub]
│   ├── ise_mcp/             # ISE                           [Stub]
│   ├── splunk_mcp/          # Splunk                        [Stub]
│   ├── hypershield_mcp/     # Hypershield                   [Stub]
│   ├── servicenow_mcp/      # ServiceNow ITSM & AIOps      [Stub]
│   └── netbox_mcp/          # NetBox DCIM & IPAM            [Stub]
├── helm/miga/               # Helm charts for K8s deployment
├── k8s/                     # Raw K8s manifests
├── docs/                    # Documentation
├── docker-compose.yml       # Local development cluster
└── .env.example             # Environment template
```

## Platform Coverage

| Platform | Status | Roles Served |
|----------|--------|-------------|
| Catalyst Center | ✅ Full | Observability, Configuration, Automation |
| Meraki Dashboard | ✅ Full | Observability, Configuration, Security |
| ThousandEyes | ✅ Full | Observability |
| Webex | ✅ Full | Automation, Observability |
| Cisco XDR | ✅ Full | Security |
| Security Cloud Control | ✅ Full | Security, Configuration, Compliance |
| INFER | ✅ Full | Observability, Security, Compliance |
| AppDynamics | 🔲 Stub | Observability |
| Nexus Dashboard | 🔲 Stub | Observability, Configuration |
| SD-WAN | 🔲 Stub | Configuration, Automation |
| ISE | 🔲 Stub | Identity, Compliance |
| Splunk | 🔲 Stub | Observability, Security |
| Hypershield | 🔲 Stub | Security |
| ServiceNow | 🔲 Stub | Automation, Observability |
| NetBox | 🔲 Stub | Configuration, Compliance |


## Use Case Scenarios

### 🚨 NOC / Incident Response

A network engineer gets paged at 2 AM. Instead of logging into four different dashboards, they open WebEx on their phone:

> **Engineer:** `network status`

MIGA fans out across Catalyst Center, Meraki, ThousandEyes, and XDR simultaneously, returning a single health card with scores, top issues, and active threats. ThousandEyes is flagging packet loss on a WAN path.

> **Engineer:** `correlate events last 30 minutes`

INFER finds the ThousandEyes path loss overlaps with a Meraki VPN tunnel flap and a Catalyst Center device error, all affecting the same branch site. It returns a root cause analysis card pointing to a failing upstream switch with recommended actions.

> **Engineer:** `run show interface gi1/0/1 on switch-br-01`

The bot presents an **approval card**. The on-call lead taps ✅ **Approve**. The command executes through Catalyst Center and results render inline. Total time: **3 minutes, never left WebEx.**

---

### 🔒 Security Operations

A SOC analyst opens the Network Security WebEx space:

> **Analyst:** `critical security events`

XDR returns active threat detections, Meraki flags anomalous traffic, and Security Cloud Control shows a policy violation.

> **Analyst:** `risk score`

INFER calculates a composite **78/100** — the top contributor is an unpatched endpoint communicating with a known C2 domain.

> **Analyst:** `quarantine endpoint AA:BB:CC:DD:EE:01`

An approval card fires to the security lead. One tap — ISE isolates the device. The entire **triage-to-containment loop** happened in a WebEx space without touching a single console.

---

### 🔧 Change Management / Maintenance Windows

Before a maintenance window, the change manager checks in:

> **Change Manager:** `predict failures`

INFER analyzes recent telemetry patterns and flags that three switches in Building C have incrementing CRC errors, suggesting a cascading failure risk. The team adjusts the maintenance plan.

> **Change Manager:** `compare network health before and after`

The bot pulls Catalyst Center health scores and ThousandEyes test baselines, showing the change improved path latency by 12ms with no new issues.

---

### 📊 Executive / Management Reporting

A director drops into the NOC WebEx space:

> **Director:** `how's the network?`

They get a clean health card: **94/100**, 3 active issues (all low severity), zero security incidents. No dashboards, no VPN, no credentials. They forward the card to their VP. Done.

---

### ✅ Compliance Auditing

An auditor needs evidence for an upcoming review:

> **Auditor:** `certificate expiry status`

Security Cloud Control returns all certs expiring within 30 days, rendered as a sortable table card.

> **Auditor:** `compliance posture`

ISE returns endpoint posture stats, INFER calculates drift from baseline. The auditor has **exportable evidence** without requesting access to any platform.

---

### 👥 Multi-Team Collaboration in Shared Spaces

The bot lives in a shared "Network Operations" WebEx space. When INFER detects an anomaly, it **proactively posts an alert card**:

> 🔴 **Anomaly detected:** 3x normal auth failure rate from Building D — correlates with ISE RADIUS timeout and Catalyst Center switch CPU spike.

The network team, security team, and identity team all see it simultaneously. Someone taps **Investigate** on the card, and the bot threads the deep-dive results. Cross-functional triage happens in one place instead of three separate channels and a bridge call.

---

### 🎓 Onboarding / Self-Service

A new hire on the network team starts exploring:

> **New Engineer:** `help`

The bot returns an interactive card listing everything it can do across all 6 roles with example commands. No need to learn 6 different platform UIs on day one.

> **New Engineer:** `list devices`
>
> **New Engineer:** `meraki wireless health`

Full inventory and real-time AP status, all through natural language. The learning curve for the entire Cisco stack just collapsed to a conversation.

---

### 🎫 Closed-Loop Incident Management (ServiceNow)

INFER detects a correlated branch outage across ThousandEyes, Meraki, and Catalyst Center:

> **MIGA Bot:** 🔴 **Correlated incident detected:** WAN degradation at Site-A — 3 platforms affected, root cause: upstream circuit CKT-00412 packet loss.

The bot auto-creates a ServiceNow P1 incident with the full RCA attached. ServiceNow's Predictive Intelligence assigns it to Network Operations with 91% confidence.

> **Engineer:** `status INC0078432`

The bot pulls the live ticket: assigned to Jane Smith, Lumen NOC contacted, provider ticket LMN-98765 open.

> **Engineer:** `any changes scheduled for core-switch-03?`

ServiceNow returns two upcoming changes — an IOS-XE upgrade Saturday night and a Lumen bandwidth upgrade next week. The engineer confirms the outage isn't change-related.

After remediation, the engineer types:

> **Engineer:** `resolve INC0078432 — Lumen fiber repair completed, circuit stable`

MIGA updates the ServiceNow ticket with resolution notes, INFER confirms health scores recovered, and the incident closes. **Full lifecycle — detection to resolution — in one WebEx thread.**

---

### 🗺️ Infrastructure Context & Impact Analysis (NetBox)

INFER flags an anomaly on `10.1.50.1`. Without NetBox, that's just an IP address. With NetBox:

> **Engineer:** `what is 10.1.50.1?`

NetBox resolves it: **Core Switch 3** — Catalyst 9300-48P, Rack 14, Building C, serial FCW2345L0AB, running IOS-XE 17.09.04a.

> **Engineer:** `what's the blast radius?`

NetBox maps the relationships: 3 downstream access switches serving **240 users**, upstream WAN edge on Lumen circuit CKT-00412, supporting Branch Office VPN and VoIP services. The engineer now knows this is a high-impact event before a single user calls the help desk.

> **Engineer:** `trace the path from core-switch-03 to the WAN edge`

NetBox returns the physical cable path and circuit information. The engineer sees the handoff interface and can pinpoint exactly where to look.

During change planning, the team asks:

> **Change Manager:** `what devices are in Rack 14?`

NetBox returns the full rack elevation — power budget, available U-space, and every device with its role. The maintenance window plan now accounts for every dependency, not just the device being touched.






## AGNTCY Integration

MIGA takes full advantage of Cisco's [AGNTCY](https://agntcy.org)
Internet of Agents framework (Linux Foundation) orchestrating Cisco platform
AI/ML capabilities:

- **OASF**: Each MCP server publishes a structured capability record
- **Agent Directory**: Dynamic discovery (deploy a new server and the Gateway finds it)
- **Identity**: Cryptographically verifiable server identities via Agent Badges
- **SLIM** (v2): Quantum-safe inter-service messaging
- **Observability** (v2): OpenTelemetry distributed tracing

## Deployment

**Local Development (Docker Compose):**
```bash
docker compose up -d
```

**Production (Kubernetes + Helm):**
```bash
helm install miga ./helm/miga --namespace miga --create-namespace
```

**CLI Tool:**
```bash
python -m packages.cli.miga_cli deploy --env prod --platforms all
python -m packages.cli.miga_cli status
python -m packages.cli.miga_cli logs catalyst-center
```

## Contributing

Stubs are designed for easy community contribution. See
[docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) for a step-by-step guide.

## License

Apache 2.0 — See [LICENSE](LICENSE)
