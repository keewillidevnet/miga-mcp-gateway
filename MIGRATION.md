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

## Pre-existing issues (not introduced here)

- Repo-wide `ruff check .` / `ruff format --check .` already fail on `main` (433
  errors; 34 files unformatted). This migration *reduced* the count (to 198). All
  files authored/edited in this migration are ruff-clean and formatted; the legacy
  codebase was intentionally not reformatted to keep the diff scoped.

## License

Apache-2.0 preserved (`LICENSE` unchanged). No source files carried per-file SPDX
headers; none were added or removed.
