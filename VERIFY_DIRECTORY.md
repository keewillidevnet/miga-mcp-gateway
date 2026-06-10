# VERIFY_DIRECTORY.md — live verification runbook (agntcy-dir Python SDK)

> ## ✅ RESULT: PASSED (verified live on a networked Docker host)
> The publish path is verified. Evidence:
> - The gateway loaded **9 specs** and published **9/9 OASF records** to a real
>   `dir-apiserver` (agntcy-dir **1.3.0** SDK), each returning a CID. Example —
>   ThousandEyes CID `baeareib76bkxrndesmq6qwoovymkay3zfdljpxbfqunhuvab4zdv2cu4vm`
>   (matches a manual SDK push of the same record → deterministic, content-addressed).
> - Records **pull back by CID** at `schema_version` **1.0.0**.
> - Image tags resolved: `dir-apiserver:v1.3.0`, `dir-reconciler:v1.3.0`,
>   `zot:v2.1.16`, and `docker.io/bitnamilegacy/postgresql:16` (bitnami catalog
>   relocation — the digest-pinned `bitnami/postgresql` ref no longer resolves).
>
> The runbook below is retained for re-runs and regression checks. **Verified items**
> (directory publication + pull round-trip) are reflected as *implemented* in the
> README; **identity badges, SLIM, OpenTelemetry, and directory-search-based routing
> discovery remain "planned."**

## Cosmetic fixes applied AFTER the live run (author-only — re-run to confirm)
These were authored + unit-tested in the build sandbox but **not** exercised on the live
stack; re-run the relevant step to confirm:
- **apiserver healthcheck** → EXEC form `["CMD","grpc-health-probe","-addr=127.0.0.1:8888"]`
  (the dir-apiserver image is distroless — no `/bin/sh`, so the shell-form check failed
  with "/bin/sh not found"). Re-check: `docker inspect --format '{{.State.Health.Status}}'`.
- **gateway healthcheck** → added a plain-HTTP `/health` route to the gateway (FastMCP
  serves MCP at `/mcp`, so the `curl /health` probe was 404ing). Re-check: gateway health
  goes `healthy`; `curl -f localhost:8000/health` returns `{"status":"ok"}`.
- **boot-time logging** → `miga.*` loggers are (re)configured at lifespan start so the
  "Published 9/9" INFO line survives uvicorn's logging reconfiguration. Re-check:
  `docker compose logs gateway | grep "Published .* OASF records"`.

## What this verifies
That MIGA, using the official **`agntcy-dir` Python SDK** (`agntcy.dir_sdk`) natively
in the gateway, can **publish** an OASF record to a real AGNTCY Directory
(`dir-apiserver` gRPC + `zot` OCI registry + `postgres` + `reconciler`) and read it
back (positive success), and that when the directory is **down** the gateway still
serves routing from `config/server-registry.yaml` (standalone fallback). No `dirctl`
binary is required at runtime (the SDK needs it only for signing, which MIGA omits).

## Confirmed surface (agntcy-dir==1.3.0, via live `dir(Client)` + `inspect.signature`)
The client is reconciled to these — they are **confirmed**, not guessed:
- Import: `from agntcy.dir_sdk.client import Client, Config`; `from agntcy.dir_sdk.models import core_v1`.
- Construct: `Client(Config(server_address=<AGNTCY_DIRECTORY_ADDR>))`.
- `push(records: list[Record], metadata=None) -> list[RecordRef]` — **list in, list out**.
- `pull(refs: list[RecordRef]) -> list[Record]`; `delete(refs: list[RecordRef]) -> None`.
- `RecordRef` has one field `.cid`. `Record` has one field `.data`
  (`google.protobuf.Struct`) — build via `s = Struct(); ParseDict(oasf, s); core_v1.Record(data=s)`.
- `search_records(SearchRecordsRequest)` — request proto; discovery is not on MIGA's
  routing path, so it is intentionally left best-effort (`[]`).

## Still to confirm on a networked host
1. **Install** `agntcy-dir==1.3.0` from the buf.build index (pin is set, not a placeholder):
   ```bash
   uv add agntcy-dir==1.3.0 --index https://buf.build/gen/python
   # or: pip install "agntcy-dir==1.3.0" --extra-index-url https://buf.build/gen/python
   python -c "import importlib.metadata as m; print(m.version('agntcy-dir'))"   # -> 1.3.0
   ```
2. **Image tags** exist on ghcr (pinned to dir v1.3.0; zot + postgres lifted from the
   agntcy/dir quickstart):
   ```bash
   docker pull ghcr.io/agntcy/dir-apiserver:v1.3.0
   docker pull ghcr.io/agntcy/dir-reconciler:v1.3.0
   docker pull ghcr.io/project-zot/zot:v2.1.16
   docker pull docker.io/bitnami/postgresql:latest@sha256:7651d7f24aad83fe68a222f7f20eded10d325c96ebee285ca5bf8162eddcba64
   ```
   The `dir-reconciler` image name is confirmed from the dir charts; the exact `:v1.3.0`
   tag for apiserver/reconciler should be confirmed against the ghcr package list.
3. **`server_address` wiring.** The gateway sets `AGNTCY_DIRECTORY_ADDR` (compose);
   `DirectoryClient` passes it explicitly to `Config(server_address=...)`.

**Pinned in compose (confirmed from upstream agntcy/dir source):**
- OASF validation: `DIRECTORY_SERVER_OASF_API_VALIDATION_SCHEMA_URL=https://schema.oasf.outshift.com`
  (var name from `install/docker/apiserver.env`). It MUST point at the same service the
  records are conformed to (1.0.0); a mismatch makes the apiserver reject pushes — which
  Step 0 catches up front.
- Healthcheck: `grpc-health-probe -addr=127.0.0.1:8888` (matches the upstream quickstart;
  the probe binary `v0.4.48` is COPY'd into the image per upstream `server/Dockerfile`).

## Step 0 — preflight (run first; require GREEN before Step 1)
This catches the failure modes the gateway's standalone fallback would otherwise mask
— most importantly a record **rejected** by the apiserver (OASF schema/version
mismatch), surfaced here instead of as a silent "standalone" later.
```bash
bash scripts/preflight_directory.sh
# checks: the 4 pinned images exist (docker manifest inspect); GET /api/version;
# POSTs every oasf/records/*.record.json to /api/validate/object/record and FAILS
# loudly on any error_count > 0. Exits non-zero on any failure.
```
Do not proceed unless it prints **PREFLIGHT PASS**.

## Step 1 — bring up the directory stack + MIGA
```bash
cp .env.example .env     # if not present
docker compose up -d zot dir-postgres agntcy-directory dir-reconciler
docker compose ps
docker inspect --format '{{.State.Health.Status}}' "$(docker compose ps -q agntcy-directory)"
# expect: healthy   (grpc-health-probe on :8888)
docker compose up -d gateway
```

## Step 2 — confirm the gateway publishes via the SDK (positive success)
```bash
docker compose restart gateway
docker compose logs gateway | grep -iE "Published .* to AGNTCY Directory \(CID:|standalone"
```
Expect "Published <name> to AGNTCY Directory (CID: <cid>)" for the registered servers
— NOT "standalone". If you see "standalone" or no "Published" line, the fallback is now
**legible** — grep the classified WARNING to tell *unreachable* from *rejected*:
```bash
docker compose logs gateway | grep -iE "directory (push|pull|delete) failed"
#   ... (unreachable)  -> directory is down / wrong AGNTCY_DIRECTORY_ADDR
#   ... (rejected)     -> apiserver refused the record (OASF schema/version mismatch);
#                         re-run Step 0 preflight to see which record + why
```
Capture one CID:
```bash
CID=$(docker compose logs gateway | grep -oE 'CID: [^)]+' | head -1 | awk '{print $2}')
echo "CID=$CID"
```

## Step 3 — confirm the record is retrievable (stored + discoverable)
Optionally install `dirctl` on the host as a manual checker (not needed by MIGA):
```bash
brew tap agntcy/dir https://github.com/agntcy/dir/ && brew install dirctl
export DIRECTORY_CLIENT_SERVER_ADDRESS=127.0.0.1:8888
dirctl pull "$CID"     # should return the OASF record JSON you published
dirctl search          # should list the published record(s)
```
Or verify in-process via the SDK:
```bash
python - <<PY
import asyncio, os
os.environ["AGNTCY_DIRECTORY_ADDR"]="127.0.0.1:8888"
from miga_shared.agntcy import DirectoryClient
async def main():
    c=DirectoryClient()
    rec=await c.pull("$CID")
    print("pulled:", bool(rec), (rec or {}).get("schema_version"))
asyncio.run(main())
PY
```

## Step 4 — confirm the standalone fallback (routing must NOT depend on the directory)
```bash
docker compose stop agntcy-directory zot dir-postgres dir-reconciler
docker compose restart gateway
docker compose logs gateway | grep -iE "standalone|Routing table loaded"
# expect: publish reports standalone, AND the routing table still loads from
#         config/server-registry.yaml (gateway healthy, tools available).
```

## Success criteria (all must hold)
- [ ] `agntcy-dir==1.3.0` installs from the buf.build index.
- [ ] All four directory services come up; `agntcy-directory` health = `healthy`.
- [ ] Gateway logs show "Published … (CID: …)" — real publication via the SDK, not `standalone`.
- [ ] The published record is retrievable by CID (SDK `pull` or `dirctl pull`) and appears in search.
- [ ] With the directory stopped, the gateway still loads routing from `config/server-registry.yaml`.
- [ ] The SDK method names, `core_v1.Record` construction, and `RecordRef.cid` matched the client (or the client was adjusted to the confirmed API).

**Only after these pass, flip the README AGNTCY claims from planned to implemented.**
