#!/usr/bin/env bash
#
# preflight_directory.sh — AGNTCY Directory integration preflight.
#
# REQUIRES NETWORK + Docker. NOT run in the MIGA build sandbox (no container-registry
# egress, no buf.build, no schema endpoint). Run this on the networked host BEFORE
# `docker compose up` of the gateway. It surfaces the failure modes that the gateway's
# best-effort standalone fallback would otherwise mask — specifically a record REJECTED
# by the apiserver (schema/version mismatch), which must be caught here, not silently.
#
# Exit code: 0 = PASS, non-zero = FAIL.
set -uo pipefail

SCHEMA_BASE="${OASF_SCHEMA_URL:-https://schema.oasf.outshift.com}"
RECORDS_DIR="${RECORDS_DIR:-oasf/records}"

# Keep these in sync with docker-compose.yml (the pinned directory stack).
IMAGES=(
  "ghcr.io/agntcy/dir-apiserver:v1.3.0"
  "ghcr.io/agntcy/dir-reconciler:v1.3.0"
  "ghcr.io/project-zot/zot:v2.1.16"
  "docker.io/bitnami/postgresql:latest@sha256:7651d7f24aad83fe68a222f7f20eded10d325c96ebee285ca5bf8162eddcba64"
)

fail=0

echo "== 1) Image availability (docker manifest inspect) =="
for img in "${IMAGES[@]}"; do
  if docker manifest inspect "$img" >/dev/null 2>&1; then
    echo "  OK       $img"
  else
    echo "  MISSING  $img"
    fail=1
  fi
done

echo "== 2) OASF schema service version =="
ver="$(curl -fsS "$SCHEMA_BASE/api/version" 2>/dev/null || true)"
if [ -n "$ver" ]; then
  echo "  $SCHEMA_BASE/api/version -> $ver"
else
  echo "  WARN: could not GET $SCHEMA_BASE/api/version"
fi

echo "== 3) Validate records against OASF (error_count MUST be 0) =="
shopt -s nullglob
records=("$RECORDS_DIR"/*.record.json)
if [ "${#records[@]}" -eq 0 ]; then
  echo "  FAIL: no records found in $RECORDS_DIR"
  fail=1
fi
for f in "${records[@]}"; do
  resp="$(curl -fsS -X POST \
    "$SCHEMA_BASE/api/validate/object/record?warn_on_missing_recommended=true" \
    -H "Content-Type: application/json" --data-binary @"$f" 2>/dev/null || true)"
  ec="$(printf '%s' "$resp" | python3 -c '
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get("error_count", d.get("errorCount", "?")))
except Exception:
    print("?")' 2>/dev/null)"
  if [ "$ec" = "0" ]; then
    echo "  OK     $(basename "$f")  error_count=0"
  else
    echo "  FAIL   $(basename "$f")  error_count=$ec  (record REJECTED — would have shown as 'standalone')"
    printf '%s\n' "$resp" | head -c 500 | sed 's/^/           /'
    fail=1
  fi
done

echo "== SUMMARY =="
if [ "$fail" -eq 0 ]; then
  echo "PREFLIGHT PASS — images present, records validate at the live OASF version."
  exit 0
fi
echo "PREFLIGHT FAIL — fix the items above BEFORE bringing up the gateway."
exit 1
