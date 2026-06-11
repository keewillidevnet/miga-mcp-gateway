# BOT_DEMO.md: credential-free WebEx live demo

Goal: a WebEx message produces a real MIGA gateway response end to end, using only INFER
plus `network_status` plus `gateway_health`, with no external platform credentials and no
standing host. An ephemeral tunnel covers the webhook for the demo session.

Status: implemented, NOT live-verified in this workspace (no Docker, no WebEx token, no
tunnel here). Run the steps on a networked Mac. Dev mode bypasses Entra JWT, so no Entra
credentials are needed. The tunnel is ephemeral per demo, not hosting.

## What works without platform credentials
Commands below are the actual phrases the rule-based NLP (`packages/webex_bot/nlp`)
recognizes. "Real" means the gateway returns a genuine response with no platform creds.

| You type | Routes to | Credential-free result |
|----------|-----------|------------------------|
| `help` / `what can you do` | local `format_help()` | Capability list. No gateway call. |
| `network status` / `how's the network?` / `is the network ok?` | `network_status` | Real: reachability of all 9 registered servers (INFER reachable; external servers report unreachable until you add their creds/images). |
| `gateway health` / `gateway status` / `miga status` | `gateway_health` | Real: gateway uptime, routing table, per-server transport/roles. |
| `risk score` | `compliance` -> INFER | Real: INFER network risk score (low on a fresh start). |
| `run correlation` / `root cause analysis` / `rca` | `observability` -> INFER | Real: INFER correlation result ("no correlated events" on a fresh start). |
| `predict failures` | `observability` -> INFER | Real: INFER prediction result. |
| `any anomalies?` / `unusual traffic` | `observability` -> INFER | Real: INFER anomaly result. |
| `show me network health` | `observability` (fan out) | Partial: INFER answers; the external observability servers report unreachable. |

INFER needs no credentials, so its tools answer for real. On a fresh stack the event
buffer is empty, so INFER honestly reports "no events / low risk." That is a real
gateway response, which is the point of the credential-free demo.

## What needs credentials (will report unreachable)
These help-text examples target external platforms and only return platform data once you
add that platform's credentials (and build its image): `meraki health`,
`catalyst center issues`, `thousandeyes status`, `list devices`, `posture status`,
`active sessions`. Some help-text examples (`xdr threats`, `hypershield`, firewall) name
platforms that were dropped from the registry and are not registered servers.

## Steps

### 1. Create the WebEx bot, token, and a test space
At <https://developer.webex.com>: create a Bot, copy its access token and bot email, then
create a space (room) and add the bot to it.

### 2. Fill .env (no platform credentials)
```bash
cp .env.example .env
# set:
#   WEBEX_BOT_ACCESS_TOKEN=<bot token>
#   WEBEX_BOT_EMAIL=<bot email, e.g. miga-bot@webex.bot>
#   MIGA_ENV=development            # dev mode bypasses Entra JWT auth
#   MIGA_GATEWAY_URL=http://localhost:8000
#   MIGA_BOT_GATEWAY_MODE=mcp       # primary MCP client path; use http only if needed
# leave all 8 platform credential blocks empty.
```

### 3. Bring up the local stack
```bash
docker compose up -d            # gateway + INFER + redis (+ the directory stack if present)
curl -fsS http://localhost:8000/health   # {"status":"ok","service":"miga_gateway"}
```

### 4. Start the bot on :9000
```bash
python -m packages.webex_bot.app
curl -fsS http://localhost:9000/health   # {"service":"miga_webex_bot","status":"healthy"}
```

### 5. Run an ephemeral tunnel for the webhook
```bash
ngrok http 9000            # or: cloudflared tunnel --url http://localhost:9000
# copy the https forwarding URL, e.g. https://abc123.ngrok-free.app
```

### 6. Register the webhook
```bash
export WEBEX_PUBLIC_URL=https://abc123.ngrok-free.app
python -m packages.webex_bot.register_webhook
# idempotently deletes old MIGA webhooks and creates messages/created and
# attachmentActions/created -> <WEBEX_PUBLIC_URL>/webhooks/webex
```

### 7. Message the bot and confirm real replies
In the space, send (the bot ignores its own messages; in a group space, mention it):
```
network status
gateway status
risk score
root cause analysis
```
Expect a real reachability summary, a gateway health JSON, and INFER responses. Capture
the transcript as evidence.

## Gateway transport note
The bot calls the gateway as an MCP client over streamable-http (`MIGA_BOT_GATEWAY_MODE=mcp`,
the default). If the streamable-http handshake misbehaves in your environment, set
`MIGA_BOT_GATEWAY_MODE=http` to use the gateway's internal dev fallback route
(`POST /internal/call`, development mode and loopback/private only). The fallback is a dev
convenience for a single demo session, not a replacement for the MCP client.

## Honesty
- HITL approval release is not wired (the bot acknowledges approve/reject but no consumer
  holds and releases a pending action). The credential-free demo is read-only and does not
  exercise it. README marks automation/approval as partial.
- This demo exercises INFER plus status. A full multi-platform live run requires platform
  credentials and is a separate step. There is no all-8-platform live run here.

## Evidence (fill after running on the Mac)
- [ ] `network status` reply (paste transcript):
- [ ] `gateway status` reply:
- [ ] `risk score` / `root cause analysis` INFER reply:
- [ ] WebEx webhook ids from register_webhook:
- [ ] Tunnel URL used (ephemeral):
