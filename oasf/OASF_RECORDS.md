# MIGA OASF Capability Records

Every server in `config/server-registry.yaml` publishes one OASF capability record so the
gateway's AGNTCY directory can discover and route to it. This file defines the shape the
agent must follow. Place one record per server at the path named in the registry's
`oasf_record` field, for example `oasf/records/thousandeyes.record.json`.

## Division of responsibility

- **Registry (`server-registry.yaml`)** is authoritative for *how to connect*: transport,
  endpoint, auth, deployment, env vars.
- **OASF record** is authoritative for *how to discover and describe*: name, version,
  skills, domains, locators. It links back to the registry entry by `name`.

Keep connection secrets and endpoints out of the OASF record. The record is metadata.

## Field reference (from the AGNTCY OASF Record Guide)

- `name`: descriptive name of the server record.
- `description`: what telemetry/capabilities the server exposes through MCP.
- `version`: semver of this record.
- `schema_version`: the OASF schema version to validate against (semver). Pin it to the
  version your AGNTCY directory runs. Confirm the current released version on the schema
  server before finalizing.
- `authors`: list in `Name <email>` format. Email optional.
- `created_at`: RFC 3339 timestamp.
- `skills`: array of `{ "name", "id" }`. Names are hierarchical taxonomy paths.
- `domains`: array of `{ "name", "id" }`. Same taxonomy treatment.
- `modules`: array of extension modules. Optional. See note below.
- `locators`: array of `{ "type", "urls" }`, e.g. `source_code`, `docker_image`.

### Hard requirement on skills, domains, and modules

The `name` and numeric `id` for every skill, domain, and module **must** be copied from the
live OASF catalogs. Do not invent ids; an invalid id fails schema validation.

- Skills catalog:   https://schema.oasf.outshift.com/skill_categories
- Domains catalog:  https://schema.oasf.outshift.com/domain_categories
- Modules catalog:  https://schema.oasf.outshift.com/module_categories
- Record schema (Draft-07): https://schema.oasf.outshift.com/schema/objects/record
- Validation endpoint: the `validate_object` route on the OASF schema server.

In the template and examples below, every `id` is set to `0` as a placeholder. Replace each
with the real catalog id and confirm the matching `name` path, then run the record through
the validation endpoint before committing.

### Modules note

If the modules catalog has an MCP-oriented module, use it to carry the `registry_ref` (the
server's `name` in `server-registry.yaml`) so discovery and routing stay linked. If no
standard module fits, register a MIGA private schema extension per the OASF contributing
guide rather than stuffing connection details into the record ad hoc. Leaving `modules`
empty is valid if you do not need it.

### Identity is separate

Cryptographic server identity (the "Agent Badge" in the MIGA README) is handled by AGNTCY
Identity as a verifiable credential (the MCP Server Badge), not by the OASF record. Keep
that as a separate step; do not try to embed the badge in the capability record.

## Template

```json
{
  "name": "<Server display name>",
  "description": "<What this MCP server exposes: platform, data, and the kinds of questions it answers>",
  "version": "1.0.0",
  "schema_version": "<current OASF schema version, e.g. 1.0.0>",
  "authors": ["Keenan Williams <you@example.com>"],
  "created_at": "2026-06-10T00:00:00Z",
  "skills": [
    { "name": "<skill/hierarchy/path from skills catalog>", "id": 0 }
  ],
  "domains": [
    { "name": "technology/network_operations", "id": 0 }
  ],
  "modules": [],
  "locators": [
    { "type": "source_code", "urls": ["<upstream repo or hosted endpoint>"] }
  ]
}
```

## Worked example: ThousandEyes (official, remote HTTP)

Maps to registry `name: thousandeyes`. Replace the `0` ids with real catalog values.

```json
{
  "name": "Cisco ThousandEyes MCP Server",
  "description": "Queries ThousandEyes v7 network and application assurance data: tests, agents, alerts, dashboards, widgets, and test results across network, page-load, web-transaction, and path-visualization tests.",
  "version": "1.0.0",
  "schema_version": "1.0.0",
  "authors": ["Keenan Williams <you@example.com>"],
  "created_at": "2026-06-10T00:00:00Z",
  "skills": [
    { "name": "<network performance monitoring skill path>", "id": 0 },
    { "name": "<anomaly detection skill path>", "id": 0 }
  ],
  "domains": [
    { "name": "technology/network_operations", "id": 0 }
  ],
  "modules": [],
  "locators": [
    { "type": "source_code", "urls": ["https://github.com/CiscoDevNet/ThousandEyes-MCP-Server-official"] }
  ]
}
```

## Worked example: NetBox (vendor official, read-only)

Maps to registry `name: netbox`.

```json
{
  "name": "NetBox MCP Server",
  "description": "Read-only access to NetBox source-of-truth infrastructure data: devices, sites, racks, IPAM, circuits, virtualization, and change history, for impact analysis and inventory context.",
  "version": "1.0.0",
  "schema_version": "1.0.0",
  "authors": ["Keenan Williams <you@example.com>"],
  "created_at": "2026-06-10T00:00:00Z",
  "skills": [
    { "name": "<infrastructure data retrieval skill path>", "id": 0 }
  ],
  "domains": [
    { "name": "technology/network_operations", "id": 0 }
  ],
  "modules": [],
  "locators": [
    { "type": "source_code", "urls": ["https://github.com/netboxlabs/netbox-mcp-server"] }
  ]
}
```

## Checklist before committing each record

1. Every skill/domain/module `name` and `id` copied from the live catalog.
2. `schema_version` matches the directory's OASF version.
3. Record passes the OASF validation endpoint.
4. `locators` point to the real upstream repo or endpoint.
5. The registry entry's `oasf_record` path points to this file.
