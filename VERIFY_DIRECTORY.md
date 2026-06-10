# VERIFY_DIRECTORY.md — live verification runbook (agntcy-dir Python SDK)

> Status: the integration on branch `feat/agntcy-directory-real` was **written but
> NOT verified**. The build sandbox has no container-registry egress (ghcr.io pulls
> return `denied`) and likely no access to the buf.build Python index, so the
> `agntcy-dir` SDK could not be installed and the directory could not be brought up.
> Run this on a **networked Docker host**. Until every success criterion passes,
> **leave the README AGNTCY directory/discovery claims at "planned."**

## What this verifies
That MIGA, using the official **`agntcy-dir` Python SDK** (`agntcy.dir_sdk`) natively
in the gateway, can **publish** an OASF record to a real AGNTCY Directory
(`dir-apiserver` gRPC + `zot` OCI registry + `postgres` + `reconciler`) and read it
back (positive success), and that when the directory is **down** the gateway still
serves routing from `config/server-registry.yaml` (standalone fallback). No `dirctl`
binary is required at runtime (the SDK needs it only for signing, which MIGA omits).

## ⚠️ Assumptions to confirm first (could not be checked offline)
1. **SDK install + version.** `requirements.txt`/`pyproject.toml` pin `agntcy-dir==1.0.0`
   as a **placeholder**. Install and pin the real version:
   ```bash
   uv add agntcy-dir --index https://buf.build/gen/python
   # or: pip install agntcy-dir --extra-index-url https://buf.build/gen/python
   python -c "import agntcy.dir_sdk, importlib.metadata as m; print(m.version('agntcy-dir'))"
   ```
   Update the pin in `requirements.txt` and `pyproject.toml` to the printed version.
2. **SDK method names / casing.** `DirectoryClient` calls `push`/`Push`, `pull`/`Pull`,
   `delete`/`Delete` (resolved defensively) and reads the **structured** `RecordRef.cid`.
   Confirm the real Python method names and the CID attribute:
   ```bash
   python - <<'PY'
   from agntcy.dir_sdk.client import Client, Config
   print([m for m in dir(Client) if not m.startswith('_')])
   PY
   ```
3. **Record construction.** `_to_record()` builds `core_v1.Record` from the OASF JSON
   via `google.protobuf.json_format.ParseDict`. Confirm the model module path
   (`agntcy.dir_sdk.models.core_v1`) and that `ParseDict` accepts the OASF 1.0.0 fields.
4. **Image tags.** Compose pins `ghcr.io/agntcy/dir-apiserver:1.16.0`,
   `ghcr.io/agntcy/dir-reconciler:1.16.0`, `ghcr.io/project-zot/zot:v2.1.16`,
   `docker.io/bitnami/postgresql:16`. Confirm they exist:
   ```bash
   docker pull ghcr.io/agntcy/dir-apiserver:1.16.0
   docker pull ghcr.io/agntcy/dir-reconciler:1.16.0
   docker pull ghcr.io/project-zot/zot:v2.1.16
   docker pull docker.io/bitnami/postgresql:16
   ```
5. **`server_address` wiring.** The gateway sets `AGNTCY_DIRECTORY_ADDR` (compose);
   `DirectoryClient` passes it to `Config(server_address=...)` and also exports
   `DIRECTORY_CLIENT_SERVER_ADDRESS`. Confirm the SDK honors one of these.

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
— NOT "standalone". Capture one CID:
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
- [ ] `agntcy-dir` installs from the buf.build index; the pin is updated to the real version.
- [ ] All four directory services come up; `agntcy-directory` health = `healthy`.
- [ ] Gateway logs show "Published … (CID: …)" — real publication via the SDK, not `standalone`.
- [ ] The published record is retrievable by CID (SDK `pull` or `dirctl pull`) and appears in search.
- [ ] With the directory stopped, the gateway still loads routing from `config/server-registry.yaml`.
- [ ] The SDK method names, `core_v1.Record` construction, and `RecordRef.cid` matched the client (or the client was adjusted to the confirmed API).

**Only after these pass, flip the README AGNTCY claims from planned to implemented.**
