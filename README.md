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
└──┬──────┬──────┬──────┬──────┬──────┬───────────┬───────────────┘
   │      │      │      │      │      │           │
   ▼      ▼      ▼      ▼      ▼      ▼           ▼
┌─────┐┌─────┐┌─────┐┌─────┐┌─────┐┌──────┐ ┌─────────┐
│CatC ││Mera-││Thou-││Webex││ XDR ││SecCld│ │  INFER  │
│     ││ki   ││sand-││     ││     ││Ctrl  │ │ Fusion  │
│     ││     ││Eyes ││     ││     ││      │ │ Engine  │
└─────┘└─────┘└─────┘└─────┘└─────┘└──────┘ └─────────┘
┌─────┐┌─────┐┌─────┐┌─────┐┌─────┐┌──────┐
│AppD ││Nexus││SDWAN││ ISE ││Splnk││Hyper │  ← Stubs
│(stb)││(stb)││(stb)││(stb)││(stb)││(stb) │
└─────┘└─────┘└─────┘└─────┘└─────┘└──────┘
   All registered in ──► AGNTCY Directory (ADS)
```

## Quick Start

```bash
# Clone the repository
git clone https://github.com/your-org/miga.git && cd miga

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
miga/
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
│   └── hypershield_mcp/     # Hypershield                   [Stub]
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
