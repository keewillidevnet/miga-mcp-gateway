#!/usr/bin/env bash
#
# run_demo.sh: one-command orchestrator for the credential-free Webex demo.
#
# Collapses the manual steps in docs/BOT_DEMO.md into a single command. It brings up the
# local stack, starts the bot, opens an ephemeral tunnel, registers the Webex webhook, and
# prints the messages to send. You then type five messages to the bot.
#
# Requires (on the Mac): docker running, a tunnel tool (cloudflared preferred, else ngrok),
# a populated .env (Webex bot token + email, MIGA_ENV=development, no platform creds), and
# the bot deps (aiohttp, httpx, mcp). It does not need platform credentials.
#
# Usage: ./scripts/run_demo.sh [--mode mcp|http] [--down] [--help]
set -euo pipefail

MODE=""
DOWN="false"

usage() {
  cat <<'USAGE'
Usage: ./scripts/run_demo.sh [--mode mcp|http] [--down] [--help]

  --mode mcp|http  Bot -> gateway transport. mcp (default) uses the MCP streamable-http
                   client; http uses the gateway's internal dev fallback route. Re-run with
                   --mode http if the streamable-http handshake misbehaves.
  --down           Run 'docker compose down' at teardown (default leaves the stack up).
  --help           Show this help.

After it prints READY, send these to the bot in a direct 1:1 message:
  help
  gateway status
  network status
  risk score
  root cause analysis
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --mode)
      MODE="${2:-}"
      shift 2
      ;;
    --down)
      DOWN="true"
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [ -n "${MODE}" ] && [ "${MODE}" != "mcp" ] && [ "${MODE}" != "http" ]; then
  echo "ERROR: --mode must be mcp or http" >&2
  exit 2
fi

# Run from the repository root regardless of where the script is invoked from.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}/.."

TS="$(date +%Y%m%d-%H%M%S)"
EVID="demo-evidence/${TS}"
mkdir -p "${EVID}"

BOT_PID=""
TUNNEL_PID=""

log() { printf '\n=== %s ===\n' "$*"; }
err() { printf 'ERROR: %s\n' "$*" >&2; }

cleanup() {
  if [ -n "${BOT_PID}" ]; then
    kill "${BOT_PID}" >/dev/null 2>&1 || true
  fi
  if [ -n "${TUNNEL_PID}" ]; then
    kill "${TUNNEL_PID}" >/dev/null 2>&1 || true
  fi
  if [ "${DOWN}" = "true" ]; then
    docker compose down >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT INT TERM

wait_for_url() {
  local url="$1" timeout="$2" elapsed=0
  while ! curl -fsS "${url}" >/dev/null 2>&1; do
    sleep 2
    elapsed=$((elapsed + 2))
    if [ "${elapsed}" -ge "${timeout}" ]; then
      return 1
    fi
  done
  return 0
}

# ---------------------------------------------------------------------------
# 1. Preflight
# ---------------------------------------------------------------------------
log "Preflight"

if ! docker info >/dev/null 2>&1; then
  err "Docker is not running. Start Docker Desktop and re-run."
  exit 1
fi

TUNNEL_TOOL=""
if command -v cloudflared >/dev/null 2>&1; then
  TUNNEL_TOOL="cloudflared"
elif command -v ngrok >/dev/null 2>&1; then
  TUNNEL_TOOL="ngrok"
else
  err "No tunnel tool found. Install cloudflared (preferred) or ngrok."
  exit 1
fi
echo "tunnel tool: ${TUNNEL_TOOL}"

if [ ! -f ".env" ]; then
  err ".env not found. Copy .env.example to .env and set the Webex bot token and email."
  exit 1
fi

set -a
# shellcheck disable=SC1091
. ./.env
set +a

if [ -z "${WEBEX_BOT_ACCESS_TOKEN:-}" ]; then
  err "WEBEX_BOT_ACCESS_TOKEN is empty in .env"
  exit 1
fi
if [ -z "${WEBEX_BOT_EMAIL:-}" ]; then
  err "WEBEX_BOT_EMAIL is empty in .env"
  exit 1
fi

: "${MIGA_GATEWAY_URL:=http://localhost:8000}"
: "${MIGA_BOT_GATEWAY_MODE:=mcp}"
if [ -n "${MODE}" ]; then
  MIGA_BOT_GATEWAY_MODE="${MODE}"
fi
export MIGA_GATEWAY_URL MIGA_BOT_GATEWAY_MODE

if ! python -c "import aiohttp, httpx, mcp" >/dev/null 2>&1; then
  err "Bot dependencies missing. Install with: pip install aiohttp httpx mcp"
  exit 1
fi
echo "gateway url: ${MIGA_GATEWAY_URL}   bot->gateway mode: ${MIGA_BOT_GATEWAY_MODE}"

# ---------------------------------------------------------------------------
# 2. Stack
# ---------------------------------------------------------------------------
log "Bringing up the local stack (docker compose up -d)"
docker compose up -d
if ! wait_for_url "http://localhost:8000/health" 60; then
  err "Gateway not reachable on http://localhost:8000 within 60s. Check that compose publishes the gateway port 8000."
  exit 1
fi
curl -fsS "http://localhost:8000/health" | tee "${EVID}/gateway-health.json"
printf '\n'

# ---------------------------------------------------------------------------
# 3. Bot
# ---------------------------------------------------------------------------
log "Starting the bot on :9000"
python -m packages.webex_bot.app >"${EVID}/bot.log" 2>&1 &
BOT_PID="$!"
if ! wait_for_url "http://localhost:9000/health" 30; then
  err "Bot did not become healthy on :9000 within 30s. See ${EVID}/bot.log"
  exit 1
fi
curl -fsS "http://localhost:9000/health" | tee "${EVID}/bot-health.json"
printf '\n'

# ---------------------------------------------------------------------------
# 4. Tunnel
# ---------------------------------------------------------------------------
log "Opening an ephemeral tunnel to :9000 (${TUNNEL_TOOL})"
TUNNEL_URL=""
if [ "${TUNNEL_TOOL}" = "cloudflared" ]; then
  cloudflared tunnel --url http://localhost:9000 >"${EVID}/tunnel.log" 2>&1 &
  TUNNEL_PID="$!"
  elapsed=0
  while :; do
    TUNNEL_URL="$(grep -oE 'https://[a-z0-9.-]+\.trycloudflare\.com' "${EVID}/tunnel.log" | head -1 || true)"
    if [ -n "${TUNNEL_URL}" ]; then
      break
    fi
    sleep 2
    elapsed=$((elapsed + 2))
    if [ "${elapsed}" -ge 40 ]; then
      err "cloudflared tunnel URL not detected within 40s. See ${EVID}/tunnel.log"
      exit 1
    fi
  done
else
  ngrok http 9000 --log=stdout >"${EVID}/tunnel.log" 2>&1 &
  TUNNEL_PID="$!"
  elapsed=0
  while :; do
    TUNNEL_URL="$(curl -fsS http://127.0.0.1:4040/api/tunnels 2>/dev/null | python -c '
import json
import sys

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
for t in data.get("tunnels", []):
    url = t.get("public_url", "")
    if url.startswith("https"):
        print(url)
        break
' || true)"
    if [ -n "${TUNNEL_URL}" ]; then
      break
    fi
    sleep 2
    elapsed=$((elapsed + 2))
    if [ "${elapsed}" -ge 40 ]; then
      err "ngrok public URL not detected within 40s. See ${EVID}/tunnel.log"
      exit 1
    fi
  done
fi
echo "tunnel url: ${TUNNEL_URL}"

# ---------------------------------------------------------------------------
# 5. Webhook registration
# ---------------------------------------------------------------------------
log "Registering the Webex webhook"
export WEBEX_PUBLIC_URL="${TUNNEL_URL}"
python -m packages.webex_bot.register_webhook 2>&1 | tee "${EVID}/webhook-register.txt"

# ---------------------------------------------------------------------------
# 6. READY
# ---------------------------------------------------------------------------
cat <<BANNER

============================================================
READY. Send a direct 1:1 message to the bot (no mention needed):
  Bot email:    ${WEBEX_BOT_EMAIL}
  Tunnel URL:   ${TUNNEL_URL}
  Gateway mode: ${MIGA_BOT_GATEWAY_MODE}

Type these five messages to the bot:
  help
  gateway status
  network status
  risk score
  root cause analysis

Use a direct 1:1 message to the bot email above, not a group space.
If the streamable-http handshake misbehaves, stop (Ctrl-C) and re-run with: --mode http
Evidence is being written to ${EVID}/
Press Ctrl-C to stop the bot and the tunnel.
============================================================

BANNER

# ---------------------------------------------------------------------------
# 7. Tail the bot log so intent recognition and gateway calls are visible live
# ---------------------------------------------------------------------------
log "Tailing ${EVID}/bot.log (Ctrl-C to stop)"
echo "evidence saved to ${EVID}/"
tail -f "${EVID}/bot.log"
