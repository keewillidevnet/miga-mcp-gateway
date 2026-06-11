# MIGA WebEx Bot, Credential-Free Demo

## What this proves

The WebEx bot talks to the MIGA gateway over MCP, and the gateway routes to INFER, with no external platform credentials. INFER and the gateway status tools return real data. The eight external platforms (ThousandEyes, Splunk, Meraki, Catalyst SD-WAN, Catalyst Center, ISE, ServiceNow, NetBox) report unreachable because they are not configured, which is the honest credential-free baseline.

## Path

```
Webex message
  -> webhook (messages/created)
  -> tunnel (public URL -> localhost:9000)
  -> bot (host process, aiohttp on :9000)
  -> MCP streamable-http client
  -> gateway (FastMCP on :8000, /mcp)
  -> INFER over HTTP (infer-mcp:8007)
```

`gateway_health`, `network_status`, and the INFER tools need no credentials.

## Prerequisites

- A Webex bot from developer.webex.com, token in `.env` as `WEBEX_BOT_ACCESS_TOKEN`.
- Docker running `gateway`, `infer-mcp`, and `redis`.
- The bot running on the host in `mcp` mode.
- A tunnel exposing the bot's `:9000`, with the webhooks registered against it.

## Run it

Bring up the gateway and INFER, and confirm the gateway can reach INFER across the Docker network:

```bash
docker compose up -d --no-deps gateway infer-mcp
docker compose exec gateway curl -sf http://infer-mcp:8007/health
# -> {"status":"ok","service":"infer_mcp"}
```

Start the bot on the host:

```bash
set -a; . ./.env; set +a
export MIGA_GATEWAY_URL=http://localhost:8000 MIGA_BOT_GATEWAY_MODE=mcp
python -m packages.webex_bot.app          # serves aiohttp on :9000
```

Expose it and register the webhooks:

```bash
cloudflared tunnel --url http://localhost:9000
export WEBEX_PUBLIC_URL=https://<your-tunnel>.trycloudflare.com
python -m packages.webex_bot.register_webhook
```

`scripts/run_demo.sh` orchestrates the stack, bot, tunnel, and webhook in one command.

## Credential-free intents

| Phrase | Tool | Needs credentials |
|---|---|---|
| `help` | local | no |
| `gateway status` | gateway_health | no |
| `network status` | network_status | no |
| `risk score` | INFER network risk score | no |
| `root cause analysis` | INFER root cause | no |
| `run correlation` | INFER event correlation | no |
| `any anomalies?` | INFER anomaly detection | no |
| `predict failures` | INFER predictive analysis | no |

The eight external platform tools require real platform credentials and report unreachable without them.

## Live evidence

Captured from a live run against the Dockerized stack with no external platform credentials. `help` returns the capability menu (omitted here for length).

### `gateway status`

```
## MIGA — Gateway Health

🟢 Healthy — miga_gateway v1.0.0
Registered servers: 9

- thousandeyes    — http  · observability
- splunk          — http  · observability, security
- meraki          — http  · observability, configuration, security
- sdwan           — stdio · configuration, automation
- catalyst_center — stdio · observability, configuration, automation
- ise             — http  · identity, compliance
- servicenow      — stdio · automation, observability
- netbox          — http  · configuration, compliance
- infer           — http  · observability, security, compliance
```

### `network status`

```
MIGA — Network Status Overview
Registered Servers: 9

🔴 Cisco ThousandEyes (thousandeyes) — unreachable
🔴 Splunk (Cisco) (splunk) — unreachable
🔴 Cisco Meraki (meraki) — unreachable
🔴 Cisco Catalyst SD-WAN (vManage) (sdwan) — unreachable
🔴 Cisco Catalyst Center (catalyst_center) — unreachable
🔴 Cisco Identity Services Engine (ise) — unreachable
🔴 ServiceNow ITSM (servicenow) — unreachable
🔴 NetBox (NetBox Labs) (netbox) — unreachable
🟢 INFER (Infrastructure Network Fusion Engine for Reasoning) (infer) — reachable
```

### `risk score`

```
## INFER — Network Risk Score

🟢 0/100 — LOW

Score Breakdown:
- Events (last 1h): 0/60 (0 events)
- Anomalies: 0/20
- Predictions: 0/20

Active Platforms: 0
Event Buffer Size: 0
Historical Incidents: 0
```

### `root cause analysis`

```
## INFER — Root Cause Analysis

✅ No correlated event groups to analyze.
```

### `any anomalies?`

```
## INFER — Anomaly Detection

✅ No anomalies detected in the last 60 minutes.
```

### `predict failures`

```
## INFER — Predictive Analysis

✅ No failure predictions based on current 30m event window.
```

The empty baselines (0/100 LOW, no anomalies, no predictions) are correct: no telemetry has been published into INFER's event buffer in this run.

## Notes and scope

- INFER runs as its own HTTP compose service (`infer-mcp:8007`), not a gateway stdio child. The gateway routes to it over the registry's `http` transport.
- `gateway depends_on infer-mcp` with `service_started`, so a slow or unhealthy INFER never blocks gateway startup; `gateway status` and `network status` respond regardless.
- The eight external platforms need real credentials for a live run. This demo proves the credential-free path: INFER plus gateway status.
- Webex ingress here uses a webhook over a tunnel. A websocket-based ingress that needs no public URL is a planned follow-up.
