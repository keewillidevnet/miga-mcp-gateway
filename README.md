# MIGA — MCP Intelligence Gateway Architecture

> A unified intelligence layer that consolidates AI and ML data from multiple Cisco
> operational platforms into a single, consistent interface for analysis, automation,
> and decision support — with conversational WebEx Chat integration.

**Author:** Keenan Williams | Network Engineer II
**License:** Apache 2.0 | **Cisco Code Exchange Compatible**

---

## Overview

Modern enterprise networks run across dozens of Cisco platforms — Catalyst Center,
Meraki, ThousandEyes, AppDynamics, Webex, XDR, Hypershield, and more. Each platform
produces isolated telemetry and requires custom integrations. **MIGA solves this** by
exposing every platform's AI/ML capabilities through a scalable MCP (Model Context
Protocol) server cluster, enabling AI agents and automated workflows to operate with
complete context, consistent data quality, and a governed interaction model.

Users interact with the cluster conversationally through a **WebEx Bot** that embeds
an MCP Client, converting natural language into structured MCP tool calls via an NLP
pipeline — with results rendered as rich Adaptive Cards.

The **INFER** (Infrastructure Network Fusion Engine for Reasoning) service continuously
ingests cross-platform telemetry to perform predictive analysis, root cause analysis,
anomaly correlation, and capacity planning that no individual platform can achieve alone.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     WebEx Bot (Python)                           │
│        NLP Intent → MCP Client → Adaptive Cards → HITL          │
│                   [AGNTCY Identity Badge]                        │
└──────────────────────────┬──────────────────────────────────────┘
                           │ JSON RPC 2.0
┌──────────────────────────▼──────────────────────────────────────┐
│                   Gateway MCP Server (Python)                    │
│   Dynamic routing via AGNTCY Directory + OASF capability lookup  │
│   6 Role Categories: Observability │ Security │ Automation       │
│                      Configuration │ Compliance │ Identity       │
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

## AGNTCY Integration

MIGA is the first project demonstrating Cisco's [AGNTCY](https://agntcy.org)
Internet of Agents framework (Linux Foundation) orchestrating Cisco platform
AI/ML capabilities:

- **OASF**: Each MCP server publishes a structured capability record
- **Agent Directory**: Dynamic discovery — deploy a new server and the Gateway finds it
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
