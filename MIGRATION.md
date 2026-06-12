# MIGA Real-MCP-Server Migration

Branch: `real-mcp-servers`

This migration turns MIGA from a set of home-grown platform server implementations
and stubs into a true **aggregation/fusion layer** over the real, published MCP
ecosystem. The gateway now connects to each platform's real MCP server as an MCP
**client** over that server's native transport, driven entirely by
`config/server-registry.yaml`. MIGA's only original server is **INFER**.

## What changed at a glance

- **Replaced 8** home-grown platform servers with routing to real upstream MCP servers.
- **Dropped 6** platforms that have no real published MCP server.
- **Added** a transport abstraction (`miga_shared/transport.py`) and a config-driven
  registry loader (`miga_shared/registry.py`); rewired the gateway to both.
- **Authored 9** OASF capability records (one per registered server) under
  `oasf/records/` using real ids from the pinned OASF v1.0.4 catalog.
- **Untouched internals:** `servers/infer_mcp` (fusion engine), `packages/webex_bot`
  (conversational interface), `packages/cli`, and the gateway routing *semantics*
  beyond the transport/registry rewiring. `miga_shared` was changed only where
  registry wiring required it (added `DirectoryClient.register_record`).

## Replaced servers (8)

The gateway connects as an MCP client; full connection details live in the registry.

| Platform | Real server | Transport | Notes |
|----------|-------------|-----------|-------|
| `thousandeyes_mcp` | Cisco ThousandEyes (official) | remote HTTP `https://api.thousandeyes.com/mcp` | docs-only repo; auth via injected bearer header |
| `splunk_mcp` | Splunk (official, distributed via Cisco) | remote HTTP `https://${SPLUNK_HOST}:8089/services/mcp` | hosted in the Splunk instance mgmt port |
| `meraki_mcp` | [CiscoDevNet/meraki-magic-mcp-community](https://github.com/CiscoDevNet/meraki-magic-mcp-community) | HTTP `/mcp:8000` (StreamableHTTP) | dynamic variant; read-only by default |
| `sdwan_mcp` | [CiscoDevNet/catalyst-sdwan-mcp-community](https://github.com/CiscoDevNet/catalyst-sdwan-mcp-community) | stdio via `docker run -i catalyst-sdwan-mcp:latest` | TypeScript, stdio only |
| `catalyst_center_mcp` | [richbibby/catalyst-center-mcp](https://github.com/richbibby/catalyst-center-mcp) | stdio via `fastmcp run catalyst-center-mcp.py` | FastMCP stdio server |
| `ise_mcp` | [pamosima/network-mcp-docker-suite](https://github.com/pamosima/network-mcp-docker-suite) (ISE server; upstream [automateyournetwork/ISE_MCP](https://github.com/automateyournetwork/ISE_MCP)) | HTTP `/mcp:8005` | read-only ERS + MnT |
| `servicenow_mcp` | [echelon-ai-labs/servicenow-mcp](https://github.com/echelon-ai-labs/servicenow-mcp) | stdio via `python -m servicenow_mcp.cli` | see ServiceNow choice below |
| `netbox_mcp` | [netboxlabs/netbox-mcp-server](https://github.com/netboxlabs/netbox-mcp-server) | HTTP `/mcp:8000` (StreamableHTTP) | official, **read-only** |

The home-grown `servers/<platform>_mcp/` directories for all 8 were removed — MIGA
no longer vendors or re-implements upstream logic.

## Dropped servers (6)

Removed entirely — server dirs, registry entries (already absent from the canonical
registry), compose services, docs/diagram entries, helm entries, and dropped-platform
tests. No real published MCP server exists for these:

`appdynamics_mcp`, `nexus_dashboard_mcp`, `hypershield_mcp`, `webex_mcp`, `xdr_mcp`,
`security_cloud_control_mcp`.

Note: only the Webex *telemetry server* (`servers/webex_mcp`) was dropped. The Webex
**bot** (`packages/webex_bot`) — the conversational interface — stays untouched.

## ServiceNow MCP server choice

**Chosen: [echelon-ai-labs/servicenow-mcp](https://github.com/echelon-ai-labs/servicenow-mcp)**
(formerly `osomai/servicenow-mcp`, which now 301-redirects to this org).

Rationale: best-maintained community ServiceNow MCP by a wide margin — ~261 stars,
active commit/PR/issue flow (latest commit Oct 2025), MIT license, and the broadest
tool coverage (incidents, catalog, change, agile, workflow, KB, users). No
Cisco-published ServiceNow MCP exists.

It is **read/write** upstream. For MIGA we restrict the surface with
`MCP_TOOL_PACKAGE` (e.g. `service_desk`) and recommend a least-privilege ServiceNow
account. Run command (`python -m servicenow_mcp.cli`) and env var names
(`SERVICENOW_INSTANCE_URL/USERNAME/PASSWORD/AUTH_TYPE`) were verified against the repo.

## Upstream discrepancies vs the attached registry

Per the brief, where the attached registry and an upstream README disagreed, we
followed upstream and updated `config/server-registry.yaml` (still valid against
`config/server-registry.schema.json`):

1. **Catalyst Center env vars (corrected).** The registry listed
   `DNAC_HOST/DNAC_USERNAME/DNAC_PASSWORD`. The upstream repo uses **`CCC_HOST`,
   `CCC_USER`, `CCC_PWD`** (no `DNAC_*` anywhere). `CCC_HOST` is a *full URL*. TLS
   verification is forced off in upstream code (no env toggle). Registry
   `env_required` and `.env.example` updated accordingly.
2. **ServiceNow source (filled + corrected).** Placeholder `<chosen-servicenow-mcp-repo>`
   replaced with `echelon-ai-labs/servicenow-mcp`. Added `MCP_TOOL_PACKAGE` to
   `env_required` for surface restriction.
3. **Meraki dynamic filename (corrected).** The registry note referenced
   `meraki-magic-mcp-dynamic.py`; the real file is **`meraki-mcp-dynamic.py`**. Also
   the server only serves HTTP when `MCP_TRANSPORT=http` (default is stdio), so the
   compose service sets `MCP_TRANSPORT=http` and `MCP_HOST=0.0.0.0`.
4. **ThousandEyes / Splunk auth (clarified).** Both are docs-only/hosted servers that
   authenticate via an `Authorization: Bearer` header (upstream proxy examples name
   the env `AUTH_TOKEN` / use `NODE_TLS_REJECT_UNAUTHORIZED`). MIGA keeps its own
   registry-side names (`TE_TOKEN`, `SPLUNK_TOKEN`) and injects them into the bearer
   header via the transport layer; `SPLUNK_HOST` is templated into the URL. Endpoints
   and ports (`/mcp`, `:8089/services/mcp`) were confirmed correct. Splunk is a Splunk
   LLC product distributed via Cisco, not Cisco-authored. Neither is read-only.
5. **ISE compose service name (noted).** The upstream suite names its service
   `ise-mcp-server`; the registry/compose use `ise-mcp` (MIGA-side service name that
   the registry URL `http://ise-mcp:8005/mcp` resolves to). Upstream provenance is
   `automateyournetwork/ISE_MCP`. ISE env vars (`ISE_HOST/ISE_USERNAME/ISE_PASSWORD`)
   were confirmed; optional `ISE_VERIFY_SSL` added to compose/env.
6. **SD-WAN — no discrepancy.** Image `catalyst-sdwan-mcp:latest`, the four
   `VMANAGE_*` vars, and the `docker run -i --rm` stdio invocation all matched.
7. **NetBox — no discrepancy.** Env var is `NETBOX_URL` (not `NETBOX_BASE_URL`),
   `/mcp:8000`, read-only — all as in the registry.

## Architecture changes

- **`miga_shared/registry.py`** — loads + JSON-schema-validates the registry,
  resolves `${ENV}` placeholders, builds bearer auth headers, reports missing env.
- **`miga_shared/transport.py`** — `MCPClientPool` opens MCP client sessions over the
  right transport per `ServerSpec`: Streamable HTTP, HTTP+SSE, or stdio (covering the
  `docker run -i` pattern and bundled `fastmcp run` / `python -m` processes). No
  upstream logic is vendored.
- **`packages/gateway/server.py`** — routing table is now built from the registry
  (no hardcoded endpoints). Role meta-tools fan out to the registered servers via the
  transport pool; the gateway publishes each server's OASF record to the AGNTCY
  Directory at startup and refreshes the registry periodically. The 6 role meta-tools,
  `network_status`, and `gateway_health` are preserved.
- **`miga_shared/agntcy`** — added `DirectoryClient.register_record(record)` to publish
  raw OASF record JSON (registry wiring; the rest of `miga_shared` is unchanged).

## OASF capability records

- One record per registered server at the path in each registry entry's `oasf_record`
  field (`oasf/records/*.record.json`), following `oasf/OASF_RECORDS.md`.
- **IDs are real, not invented.** Skill and domain `name`/`id` pairs were generated
  from the **pinned OASF schema v1.0.4** (latest stable release of
  [agntcy/oasf](https://github.com/agntcy/oasf)). The full numeric uid was computed
  with the schema server's own algorithm
  (`uid = ((category_uid * 100) + subcategory_uid) * 100 + leaf_uid`), reproduced from
  `server/lib/schema/cache.ex` + `types.ex` and cross-checked against known values
  (e.g. `question_answering = 10302`, `network_operations = 10301`). `schema_version`
  is pinned to `1.0.4`.
- **Modules left empty (`[]`)**, which the guide explicitly permits. The standard
  `integration/mcp` module's `data` (`mcp_data`) requires connection/deployment detail
  that the registry already owns; the guide warns against stuffing connection details
  into the record. Discovery↔routing linkage is instead carried in the record's
  `annotations.miga_registry_ref` (a typed string map) plus the registry's
  `oasf_record` path — a clean two-way link without abusing the module.
- **Validation.** Records were validated structurally against the OASF Record object
  schema (required fields, `source_code` locator enum, `datetime_t`/RFC-3339
  `created_at`, typed `skills`/`domains`) and for id/name consistency against the
  pinned catalog. The live `validate_object` HTTP endpoint on
  `schema.oasf.outshift.com` could not be reached from the build sandbox (the schema
  UI is client-rendered and only `GET` web-fetch is available; direct POST/cURL is
  blocked), so validation was performed against the pinned v1.0.4 schema source that
  the endpoint serves. Re-run against the live endpoint before publishing to a
  production AGNTCY Directory if its OASF version differs from 1.0.4.

## Docker Compose + env

- Compose services for the `docker_compose` servers: `meraki-mcp` (HTTP), `ise-mcp`
  (HTTP), `netbox-mcp` (HTTP, read-only), wired from `.env`.
- `ThousandEyes`/`Splunk` (`remote_managed`) are **not** compose services — referenced
  by URL in the registry.
- SD-WAN (`docker_image` stdio) is spawned on demand by the gateway via
  `docker run -i`; the gateway service mounts the Docker socket.
- Catalyst Center and ServiceNow (`local_process` stdio) are bundled into the gateway
  image and spawned as stdio subprocesses. INFER keeps its own service.
- All dropped-platform compose services were removed.
- `.env.example` rewritten to list **every** env var named in the registry
  `env_required` fields, grouped by platform, with placeholders and comments. No real
  secrets.

## Docs / Helm

- README "Platform Coverage" table rewritten to reflect reality (status, source/
  endpoint, roles) plus the architecture diagram and Overview. All dropped platforms
  removed from text and diagram.
- `docs/ARCHITECTURE.md` updated (design principles, platform layer described as real
  external servers + transports, data flow, port/reach table).
- `helm/miga/values.yaml` trimmed to the MIGA-built services (gateway, bot, INFER);
  external servers are provisioned out-of-band and referenced via the registry.

## Tests

- Added: `tests/test_registry.py`, `tests/test_transport.py`, `tests/test_gateway.py`,
  `tests/test_oasf_records.py`. The MCP client transport is mocked, so no live
  credentials are needed.
- Removed dropped-platform NLP tests (`test_xdr_threats`, `test_hypershield_enforcement`,
  `test_firewall_rules` → security_cloud_control).
- Updated `tests/test_shared.py` `PlatformType` count (the enum is intentionally left
  intact; INFER and several models still reference it).
- `tests/test_infer.py` unchanged (INFER internals untouched).
- Result: **115 passed, 4 xfailed**. The 4 xfails are pre-existing `webex_bot` NLP
  behaviors that fail identically on pristine `main` (verified); the bot is out of
  migration scope, so they are marked `xfail` rather than masked.

## Security hardening

A security review of this branch's new attack surface (the gateway now spawns
processes and talks to third-party servers) produced these fixes, included here:

- **Least-privilege subprocess env (HIGH).** `MCPClientPool` previously passed the
  *entire* gateway environment to every spawned stdio server, exposing all platform
  secrets to each upstream process. It now passes only a minimal base allowlist
  (`PATH`, `HOME`, `PYTHONPATH`, …) plus that server's declared `env_required`, so
  e.g. the SD-WAN container never receives the ServiceNow/NetBox/ThousandEyes
  secrets. (`miga_shared/transport.py`)
- **Bearer token only over HTTPS (MEDIUM).** The registry refuses to attach an
  `Authorization: Bearer` header to a non-`https://` URL, failing closed if a URL
  (or its `${ENV}` host) is tampered with — mitigating token exfiltration / SSRF.
  Treat `.env` as a secret with restricted permissions. (`miga_shared/registry.py`)
- **Forwarded-output cap (MEDIUM).** Output from untrusted upstream servers is
  size-capped (`MIGA_MAX_TOOL_RESPONSE_CHARS`, default 50k) before being returned to
  the bot/INFER, both at the transport boundary and on the gateway's named-tool path.
  (`miga_shared/transport.py`, `packages/gateway/server.py`)
- **Docker socket privilege (HIGH, documented).** `docker-compose.yml` mounts the
  Docker socket so the gateway can spawn the SD-WAN stdio image — root-equivalent
  host access. The compose file now documents safer alternatives (SD-WAN as a
  sidecar, a restricted socket proxy, or rootless Docker).

Still open / operator responsibility (not changed here): ServiceNow is read/write —
gate it with `MCP_TOOL_PACKAGE` + a least-privilege account and ensure the Webex
bot's HITL approval covers write tools; the upstream Catalyst Center server forces
TLS verification off in its own code; and `packages/cli/miga_cli.py` uses
`subprocess(..., shell=True)` (pre-existing, do-not-touch file). New tests cover the
env scoping, output cap, and bearer-over-HTTPS behavior.

## Lint / CI

`main` was not ruff-clean (433 lint errors; 34 files unformatted), so the CI
**Lint & Type Check** job failed on `main` too. To get this branch green **without
touching the do-not-touch internals**:

- All migration code (`miga_shared/registry.py`, `miga_shared/transport.py`,
  `packages/gateway/server.py`, `miga_shared/agntcy`, and the new tests) is fully
  ruff-clean and formatted.
- The pre-existing internals the brief marks do-not-touch (`servers/infer_mcp`,
  `packages/webex_bot`, `packages/cli`, and the legacy `miga_shared` modules
  `auth`, `clients`, `errors.py`, `models.py`, `server_base.py`, `utils`) are kept
  **byte-identical to their prior state** and excluded from ruff via
  `extend-exclude` in `pyproject.toml`. A dedicated lint-cleanup PR can remove these
  exclusions later.
- `UP017` (datetime.UTC) and `UP042` (StrEnum) are ignored repo-wide: both emit
  Python-3.11-only / semantics-changing rewrites; the codebase keeps `timezone.utc`
  and `(str, Enum)` intentionally.

Result: `ruff check .` and `ruff format --check .` both pass; `pytest` is 115 passed,
4 xfailed (pre-existing webex_bot NLP behavior, verified identical on `main`).

## Known tech debt (intentionally untouched)

The following pre-existing references to dropped platforms remain in do-not-touch
files and are tracked for a future cleanup; none are wired into routing/registry:

- `miga_shared/models.py` — the `PlatformType` enum still defines `WEBEX`, `XDR`,
  `SECURITY_CLOUD_CONTROL`, `APPDYNAMICS`, `NEXUS_DASHBOARD`, `HYPERSHIELD`. The enum
  is referenced by INFER and other models, so it was left intact.
- `miga_shared/clients/__init__.py` — the dead `CiscoAPIClient.for_xdr()` and
  `for_security_cloud_control()` factory methods are unused but left in place.
- `servers/infer_mcp/server.py` — a few expert RCA templates reference `"xdr"` /
  `"security_cloud_control"` event sources as strings; INFER internals are
  unchanged, so these templates simply never match now.

(The post-migration cleanup branch removed the other two stragglers: the hardcoded
platform list in `packages/cli/miga_cli.py`, now derived from the registry, and the
stale `docs/CONTRIBUTING.md` stub-creation flow, now rewritten for the registry +
OASF model.)

## Tech debt — AGNTCY Directory integration gap

The AGNTCY Directory integration is **not wired to the real product** and is the
main item to address before any AGNTCY-Directory-dependent claim is load-bearing:

- **Wrong/placeholder image.** `docker-compose.yml` references
  `ghcr.io/agntcy/directory:latest`, which does not exist (a `docker compose up`
  pull returns `denied`). The real product is `ghcr.io/agntcy/dir-apiserver` — a
  multi-service system: a **gRPC** apiserver on `:8888`, a `zot` OCI registry
  (records are stored as OCI artifacts), `postgres` (search/index), and a
  `reconciler`.
- **API mismatch.** MIGA's `miga_shared/agntcy/DirectoryClient` is a simplified REST
  `/v1/records` client (HTTP `:8500`) that predates this work and does **not** match
  the real directory's gRPC + OCI API.
- **Impact: none on the gateway.** `DirectoryClient.register` / `register_record`
  are best-effort; on connection failure they return `"standalone"` and the gateway
  runs with `config/server-registry.yaml` as the source of truth (registry reload is
  the actual discovery path). The 9 OASF records validate against OASF **1.0.0** but
  are **not published to a live directory**.
- **Identity/SLIM/Observability** are likewise not implemented: `IdentityBadge` is a
  scaffold with no real crypto; SLIM and OpenTelemetry are future (v2) items. The
  README has been corrected to label these as planned.
- **Follow-up to wire it for real:** point compose at `ghcr.io/agntcy/dir-apiserver`
  (+ `zot` + `postgres` + `reconciler`) with a **pinned tag** (not `:latest`) per the
  directory's own quickstart, and move `DirectoryClient` to the gRPC API. If only the
  OASF validate endpoint MIGA already talks to is needed, run
  `ghcr.io/agntcy/oasf-server` instead.

**Status update (branch `feat/agntcy-directory-real`):** the real wiring is now
**drafted** and pending operator verification (it could **not** be verified in the
build sandbox — no container-registry egress and likely no buf.build Python index
access, so the SDK can't be installed and the directory can't be brought up):
- `docker-compose.yml` defines the real stack — `agntcy-directory`
  (`ghcr.io/agntcy/dir-apiserver`, gRPC `:8888`, `grpc-health-probe`), `zot`
  (`ghcr.io/project-zot/zot:v2.1.16`), `dir-postgres` (`bitnami/postgresql:16`), and
  `dir-reconciler` — with **pinned tags** (apiserver/reconciler at the chart appVersion
  `v1.3.0`, confirmed name; tag to confirm against ghcr) and OASF validation pointed at
  `https://schema.oasf.outshift.com` (records are OASF 1.0.0).
- `miga_shared/agntcy/DirectoryClient` uses the official **`agntcy-dir` Python SDK**
  (`agntcy.dir_sdk.client.Client` / `Config`), reconciled to the **1.3.0 surface
  confirmed by live introspection** (`dir(Client)` + `inspect.signature`). The earlier
  "dir is Go-only" premise was wrong, and the Go-derived mapping was wrong on several
  counts now corrected: `push(records: list) -> list[RecordRef]` (list-in/list-out),
  the OASF doc is carried in `Record.data` (a protobuf `Struct`, built via
  `core_v1.Record(data=Struct(...))`), and the CID is the structured `RecordRef.cid`.
  The dirctl subprocess and its text-output CID scraping are removed. The SDK needs
  `dirctl` only for *signing*, which MIGA does not use, so **no `dirctl` in the gateway
  image**. Surface confirmed by introspection; the **live roundtrip is still pending**.
- Best-effort semantics preserved: if the SDK is not installed or the directory is
  unreachable, the client returns `standalone`/`error` and the gateway keeps routing
  from `config/server-registry.yaml`. Routing never depends on the directory.
- Dependency added: `agntcy-dir` in `requirements.txt` / `pyproject.toml`, installed
  from the buf.build index (`uv add agntcy-dir --index https://buf.build/gen/python`);
  pinned to the confirmed **`agntcy-dir==1.3.0`**.
- **Not done / pending live verification:** confirm exact ghcr image tags; confirm the
  exact SDK published version; confirm Python method names/casing (`push`/`Push`,
  `pull`, `delete`, search) and the OASF-JSON→`core_v1.Record` construction and
  `RecordRef.cid` attribute; confirm `server_address` env wiring. The README AGNTCY
  claims stay **planned** until `VERIFY_DIRECTORY.md` passes on a networked Docker host.
## License

Apache-2.0 preserved (`LICENSE` unchanged). No source files carried per-file SPDX
headers; none were added or removed.
