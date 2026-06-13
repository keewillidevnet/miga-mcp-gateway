# Phase A (Collate) — Adapter Notes

> Status: **authored and tested against REAL captured sample responses, NOT
> validated against live/production APIs.** Three platforms in scope: NetBox,
> Catalyst Center, Cisco ISE. Samples captured 2026-06-13 from free DevNet
> sandboxes and the public NetBox demo, with no production credentials.

---

## What's in this drop

- `miga_shared/canonical.py` — the canonical schema: `CanonicalEvent`,
  `CanonicalEntity`, `NativeIdentifiers`, `EntityType`, `ObservationPoint`.
  Extends, does not fork: it reuses `PlatformType` / `SeverityLevel` from
  `miga_shared/models.py` and bridges to INFER's existing `CorrelatedEvent` via
  `CanonicalEvent.to_correlated_event()`.
- `miga_shared/adapters/{netbox,catalyst_center,ise}.py` — one adapter per
  platform.
- `tests/test_canonical_schema.py` and
  `tests/test_{netbox,catalyst_center,ise}_adapter.py` — round-trip tests using
  the real samples as fixtures in `tests/fixtures/*.json`.
- Run: `pytest tests/` — **31 passing.**

New package marker needed in the repo: `miga_shared/adapters/__init__.py`
(empty) so the adapters subpackage imports.

---

## Shared decisions (all three adapters)

- `canonical_id` is **provisional and platform-scoped** at Phase A:
  `platform:nativekey` (e.g. `netbox:device:138`, `catalyst_center:<uuid>`,
  `ise:<uuid>`). Phase B is what collapses these across platforms onto one id.
- **No identifier-format coercion.** MACs are kept exactly as each source
  emitted them. Canonicalizing identifier formats is a Phase B resolution
  concern; doing it now, before seeing how formats differ, would be guessing.
- **Flow fields** (`protocol` / ports / `app_classification` / `dscp` /
  `observation_point`) are declared on `CanonicalEvent` but stay null for all
  three platforms — none is a flow exporter. They are there for the later
  flow-bearing platforms (Meraki / ThousandEyes / SD-WAN), not invented here.
- **Grounding rule.** Every populated field is mapped from a real captured
  response. Anything not observed is left null or flagged — never forced.

---

## NetBox — demo.netbox.dev (Community v4.6.2)

Entities: `GET /api/dcim/devices/`, `GET /api/ipam/ip-addresses/`.
Event: `GET /api/core/object-changes/`.

- **device → entity:** `hostname←name`, `serial←serial` (empty string → None),
  `extra.netbox_id`, `extra.asset_tag` (omitted when null), `extra.site_slug`.
  `mac` / `uuid` / `ci` are null — NetBox holds MACs on interface records,
  devices use an integer id (not a UUID), and NetBox is not a CMDB.
- **ip → entity:** `ip←address` with the prefix stripped (`172.16.0.1/24` →
  `172.16.0.1`), full CIDR preserved in `extra.cidr`; `extra.vrf`,
  `extra.assigned_device` / `assigned_interface` (omitted when unassigned).
- **change-log → event:** `type` is `"{changed_object_type}:{action}"` (e.g.
  `dcim.device:update`); `attributes.changed_fields` / `changes` is a real diff
  of `prechange_data` vs `postchange_data`; `entity_ref` is built with the same
  provisional-id scheme the entity adapter uses, so a device change resolves to
  the same id as the device entity (the Phase B join). `severity` defaults to
  INFO — NetBox change-log has no severity field.
- **FLAG (unverified):** the device→`ip` path reads `primary_ip4.address`, but
  both sample devices had null primary IPs, so that path is implemented from the
  field name and is not exercised by real data. Capture a device with a primary
  IP to validate the nested brief-IP shape.
- **FLAG (defensive):** change-log create/delete actions are handled (empty diff
  when one side is absent) but unexercised — the sample held only `update`.

## Catalyst Center — DevNet always-on (sandboxdnac.cisco.com)

Entity: `GET /dna/intent/api/v1/network-device`.
Event: `GET /dna/intent/api/v1/issues`.

- **device → entity:** every identifier slot populated from real data —
  `hostname←hostname`, `serial←serialNumber`, `ip←managementIpAddress`,
  `mac←macAddress`, `uuid←instanceUuid`. `ci` null (not a CMDB).
  `source_record_ref` is the device's `instanceUuid`, because the inventory
  response carries no per-record URL field (used the id the platform gave rather
  than constructing a URL we never observed).
- **PENDING event:** `/issues` returned empty (`{"response":[],"totalCount":"0"}`).
  The envelope is verified (empty → `[]`), but `catalyst_issue_to_event` raises
  `NotImplementedError` until a non-empty sample exists — needs a sandbox with an
  open assurance issue. The per-issue field shape must not be guessed.

## Cisco ISE — DevNet reservable (ISE 3.x, OpenAPI on port 443)

Entity: `GET /api/v1/endpoint` (a bare JSON array — **not** the ERS
`SearchResult` wrapper; ERS on port 9060 was disabled on the sandbox).

- **endpoint → entity:** `mac←mac`, `uuid←id` (ISE endpoint id is a UUID),
  `ip←ipAddress`, `serial←serialNumber`, `extra.group_id←groupId`. `hostname`
  null — ISE's `name` equals the MAC for an endpoint, so mapping it to hostname
  would mislead; the raw name is preserved in `attributes`. `ci` null.
  The endpoint object has a `protocol` field, but it is an endpoint attribute,
  **not** a flow protocol, and is not mapped onto any flow field.
- **PENDING event:** ISE auth/session events come from the MnT (Monitoring) API,
  which returns XML on a separate path, and an idle lab had no live sessions.
  `ise_session_to_event` raises until a real MnT sample exists.

---

## Pending backlog (honest)

- Catalyst Center issues → event: needs a non-empty `/issues` sample.
- ISE sessions → event: needs a real MnT (XML) session sample.
- NetBox device→`ip` path: needs a device with a primary IP assigned.
- **Phase B (entity resolution):** not started. The adapters set it up by
  attaching native identifiers and emitting consistent `platform:nativekey`
  provisional ids.

## Honesty markers

- Authored and tested against samples; NOT live/production-validated.
- Sandboxes prove ingestion, normalization, and round-trip — not production
  scale, and not real cross-platform overlap: the seeded ISE endpoint MAC
  (`AA:BB:CC:00:11:22`) does not match the Catalyst Center switch MACs
  (`52:54:00:...`). That non-overlap is exactly the case Phase B's
  constructed-overlap test is designed for.
- Every pending item raises `NotImplementedError` naming the specific sample it
  needs, and tests assert those paths stay blocked.
