# VERIFY_DIRECTORY.md — live verification runbook for the real AGNTCY Directory

> Status: the integration on branch `feat/agntcy-directory-real` was **written but
> NOT verified** in the build sandbox — that environment has no container-registry
> egress (ghcr.io pulls return `denied`), so the directory images cannot be pulled
> and the stack cannot be brought up. Run this on a **networked Docker host**. Until
> every success criterion below passes, **leave the README AGNTCY directory/discovery
> claims at "planned."**

## What this verifies
That MIGA can publish an OASF record to a real AGNTCY Directory (`dir-apiserver` gRPC
+ `zot` OCI registry + `postgres` + `reconciler`) and read it back, and that when the
directory is **down** the gateway still runs (routing from `config/server-registry.yaml`).

## Prerequisites
- Docker + Docker Compose v2; outbound access to `ghcr.io` and `schema.oasf.outshift.com`.
- The `dirctl` CLI available to the gateway (one of):
  - install the binary on the gateway image / host and leave `DIRCTL_BIN=dirctl`, or
  - point `DIRCTL_BIN` at a mounted binary, or
  - run `dirctl` from the `ghcr.io/agntcy/dir-ctl` image.
- A populated `.env` (`cp .env.example .env`).

## ⚠️ Assumptions to confirm first (could not be checked offline)
1. **Image tags.** `docker-compose.yml` pins `ghcr.io/agntcy/dir-apiserver:1.16.0`
   and `ghcr.io/agntcy/dir-reconciler:1.16.0` (the dir chart appVersion) and
   `ghcr.io/project-zot/zot:v2.1.16`. Confirm these tags exist:
   ```bash
   docker pull ghcr.io/agntcy/dir-apiserver:1.16.0
   docker pull ghcr.io/agntcy/dir-reconciler:1.16.0
   docker pull ghcr.io/project-zot/zot:v2.1.16
   docker pull docker.io/bitnami/postgresql:16
   ```
   If a tag is wrong, check the repo's releases / `ghcr.io/agntcy/dir` packages and
   update the `image:` lines (keep them pinned — never `:latest`).
2. **`dirctl push` CID output format.** `DirectoryClient._parse_cid` expects either
   `Pushed record with CID <cid>` (human) or a JSON object with a `cid` field. Confirm
   with a real run (below) and adjust the parser if the format differs.
3. **`dirctl search` flags.** `discover()` calls a bare `dirctl search`; confirm the
   real flag names if discovery is later wired into routing (it is not today).
4. **`reconciler.env` keys.** The reconciler env here mirrors the apiserver store/db
   settings; confirm against `agntcy/dir` `install/docker/reconciler.env`.

## Step 1 — bring up the directory stack + MIGA
```bash
cp .env.example .env            # if not already present
docker compose up -d zot dir-postgres agntcy-directory dir-reconciler
# wait for the apiserver to report healthy (grpc-health-probe):
docker compose ps
docker inspect --format '{{.State.Health.Status}}' $(docker compose ps -q agntcy-directory)
# expect: healthy
docker compose up -d gateway
```

## Step 2 — confirm dirctl can reach the directory
```bash
export DIRECTORY_CLIENT_SERVER_ADDRESS=127.0.0.1:8888   # from the host
dirctl search || echo "search returned non-zero (note exit semantics)"
```
Expect a successful connection (empty result set is fine on a fresh directory).

## Step 3 — publish an OASF record and capture its CID
```bash
dirctl push oasf/records/thousandeyes.record.json
# expect output containing: Pushed record with CID <cid>
CID=$(dirctl push oasf/records/infer.record.json | grep -oE '[A-Za-z0-9][A-Za-z0-9:_./-]{15,}' | tail -1)
echo "CID=$CID"
```
Push every record:
```bash
for f in oasf/records/*.record.json; do echo "== $f =="; dirctl push "$f"; done
```
All nine should push without a validation error (records are OASF 1.0.0; the apiserver
validates against `DIRECTORY_SERVER_OASF_API_VALIDATION_SCHEMA_URL`).

## Step 4 — confirm stored + discoverable
```bash
dirctl pull "$CID"          # should return the same OASF JSON you pushed
dirctl search               # should now list the pushed record(s)
```

## Step 5 — confirm MIGA publishes via the gateway
```bash
docker compose restart gateway
docker compose logs gateway | grep -iE "published .* to AGNTCY Directory|standalone|CID"
```
Expect "Published <name> to AGNTCY Directory (CID: ...)" lines (not "standalone").

## Step 6 — confirm the standalone fallback (routing must not depend on the directory)
```bash
docker compose stop agntcy-directory zot dir-postgres dir-reconciler
docker compose restart gateway
docker compose logs gateway | grep -iE "standalone|Routing table loaded"
# expect: directory publish reports standalone, AND the routing table still loads
#         from config/server-registry.yaml (gateway healthy, tools available).
```

## Success criteria (all must hold)
- [ ] All four directory services come up; `agntcy-directory` health = `healthy`.
- [ ] `dirctl push` of all 9 records succeeds with **no validation errors**.
- [ ] `dirctl pull <CID>` returns the pushed record; `dirctl search` lists it.
- [ ] Gateway logs show "Published … (CID: …)" (real publication, not `standalone`).
- [ ] With the directory stopped, the gateway still loads its routing table from
      `config/server-registry.yaml` and serves tools (standalone fallback intact).
- [ ] The `dirctl push` CID output matched `_parse_cid` (or the parser was adjusted).

**Only after these pass, flip the README AGNTCY claims from planned to implemented.**
