# MIGA Refactor — Validation Report (post-cleanup)

**Verdict: GO — pending two environment-only gates.** All functional checklist items
A–I pass and the CLI `shell=True` sharp edge is now closed (argv form). The two
remaining gates could not be executed in this sandbox and must be run on a networked /
Docker-enabled box before publish: **Gate 1** live OASF `validate_object` (C9, still blocked here)
and **Gate 2** `docker compose config` (D10 — now schema- + interpolation-validated
with official Compose Spec tooling; only the final `docker compose config --quiet`
binary step remains). Reproducible commands are in the
"Post-cleanup: argv fix + environment gates" section below.

History:
- Audited at `main` HEAD `8798d7a` (PR #1 + PR #2 merged). Two A2 defects were found.
- Defects fixed on branch `fix/post-migration-cleanup` (off `main`): CLI now derives
  its server set from the registry; `docs/CONTRIBUTING.md` rewritten for the
  registry + OASF contribution model. This report reflects that branch.
- Method: read-only audit commands; the only repo changes are the two scoped fixes,
  README badges, MIGRATION.md tech-debt note, and this report.

---

## A. Drops

- **A1 — Six server dirs removed — PASS.** `servers/` contains only `infer_mcp`.
- **A2 — No leftover references (actionable) — PASS** *(was PARTIAL)*.
  - FIXED `packages/cli/miga_cli.py`: the hardcoded `PLATFORMS` list (which contained
    the 6 dropped platforms) was removed; the CLI now derives its server set from
    `miga_shared.registry.load_registry()` (9 servers, no dropped).
  - FIXED `docs/CONTRIBUTING.md`: removed all references to deleted
    `servers/<platform>_mcp` paths, the `for_appdynamics()` example, and
    `docker compose up -d appdynamics-mcp`; rewritten for the registry + OASF flow.
  - Remaining references are **intentional and documented as tech debt** in
    MIGRATION.md, all in do-not-touch files and not wired into routing:
    `miga_shared/models.py` `PlatformType` enum; dead `for_xdr()` /
    `for_security_cloud_control()` factories in `miga_shared/clients/__init__.py`;
    and `servers/infer_mcp/server.py` RCA template strings.

## B. Real servers wired (8) + INFER (9)
- **B3 — PASS.** Exactly 9 entries; no dropped platforms.
- **B4 — PASS.** Validates against the schema (JSON-Schema Draft-07).
- **B5 — PASS.** Gateway loads/uses the registry (`load_registry` → `load_from_registry`,
  periodic refresh); transport supports http, sse, and stdio (incl. `docker run -i`).
- **B6 — PASS.** `infer_mcp`, `webex_bot` unchanged vs pre-refactor. `packages/cli`
  now changed **only** by the authorized FIX 1. `miga_shared` changes remain
  additive (registry.py, transport.py, agntcy `register_record`).

## C. OASF records
- **C7 — PASS.** Guide present; one record per server; all 9 `oasf_record` paths resolve.
- **C8 — PASS.** No `id: 0`, no `<...>`; all ids positive ints; `schema_version` = 1.0.4.
- **C9 — PASS (catalog) / PRE-PUBLISH GATE (live endpoint).** Every skill/domain
  name+id matches the pinned OASF v1.0.4 catalog exactly. The live `validate_object`
  endpoint on `schema.oasf.outshift.com` is not reachable from the sandbox (GET-only
  web-fetch returns no content; POST/curl blocked); re-run against the live endpoint
  before production publish, especially if the directory's OASF version ≠ 1.0.4.

## D. Compose and env
- **D10 — PASS (YAML) / PRE-PUBLISH GATE (docker CLI).** Correct services; no dropped
  platforms; ThousandEyes/Splunk URL-referenced, not services. `docker` is absent in
  the sandbox, so `docker compose config` was not run — execute it in a Docker-enabled
  environment before publish.
- **D11 — PASS.** Every registry `env_required` var is in `.env.example`; no
  dropped-platform vars remain.
- **D12 — PASS.** `.env` untracked; no committed secrets; `.pytest_cache` untracked.

## E. Docs
- **E13 — PASS.** Platform Coverage table lists exactly the 9 surviving entries with
  correct status labels.
- **E14 — PASS.** Badge reads `Registered Servers-9`; no "15 platforms"; diagram/overview
  reflect the real set. (`docs/CONTRIBUTING.md` now also consistent — see A2.)
  Three Cisco Code Exchange badges (published / Run in Cisco Cloud IDE / Cisco
  Developed) added to the README badge row.

## F. Tests and lint
- **F15 — PASS.** `119 passed, 4 xfailed` (the 4 xfails are pre-existing webex_bot NLP,
  unchanged). Transport-dependent tests mock the MCP client.
- **F16 — PASS.** `ruff check .` clean; `ruff format --check .` clean.

## G. Migration artifacts
- **G17 — PASS.** MIGRATION.md states replacements, drops, the ServiceNow choice
  (`echelon-ai-labs/servicenow-mcp`), upstream discrepancies, and now a tech-debt
  section for the intentional remaining references.
- **G18 — PARTIAL.** No in-repo `PR_DESCRIPTION.md`; equivalent summaries exist
  (MIGRATION.md + merged PR bodies). A PR description for this cleanup branch is
  provided alongside the fix.

## H. Security review (PR #2) — all PASS
- **S1** TLS not disabled anywhere in MIGA code (verify defaults true; no
  `verify=False` / `NODE_TLS_REJECT_UNAUTHORIZED=0` / `_create_unverified`).
- **S2** No `shell=True` in gateway/transport/registry; stdio uses argv lists (no shell
  injection from registry values); bearer attached only over `https://` URLs.
- **S3** Bearer tokens resolved from env only, never logged, host-scoped (https-only
  guard; httpx strips auth on cross-origin redirects).
- **S4** PR #2 added least-privilege subprocess env, the https-only bearer guard, a
  forwarded-output cap, and a documented Docker-socket hardening note; it strengthened
  auth and did not weaken it; new tests cover the changed paths.
  *(Note: the CLI uses `subprocess(shell=True)` — pre-existing; the FIX-1 change did
  not introduce shell-interpolated registry values into a shell.)*

## I. License — PASS
Apache-2.0 `LICENSE` unchanged; `pyproject.toml` declares Apache-2.0.

---

## Punch list (post-cleanup)

| # | Sev | Item | Status |
|---|-----|------|--------|
| 1 | High (ops) | `packages/cli/miga_cli.py` stale platform list | **RESOLVED** — registry-derived. |
| 2 | High (docs) | `docs/CONTRIBUTING.md` stale stub flow | **RESOLVED** — rewritten. |
| 3 | Low | Dead `for_xdr()`/`for_security_cloud_control()` factories | Open (tech debt; do-not-touch). |
| 4 | Low | `PlatformType` enum retains dropped members | Open (tech debt; do-not-touch). |
| 5 | Low | INFER RCA templates reference dropped platform strings | Open (tech debt; do-not-touch). |
| 6 | Info | No in-repo PR description | Optional. |
| 7 | **Gate** | Live OASF `validate_object` (C9) not exercised | Run before publish. |
| 8 | **Gate** | `docker compose config` (D10) not run | Run before publish. |

---

## Appendix — trimmed raw output (post-cleanup)

### A2 re-grep (only intentional cases remain)
```
miga_shared/models.py: PlatformType enum entries (intentional)
miga_shared/clients/__init__.py: for_xdr / for_security_cloud_control (dead, intentional)
servers/infer_mcp/server.py: RCA template strings (intentional)
docs/CONTRIBUTING.md: CLEAN   packages/cli/miga_cli.py: CLEAN (registry-derived)
```

### CLI server set (registry-derived)
```
SERVER_NAMES = ['thousandeyes','splunk','meraki','sdwan','catalyst_center','ise','servicenow','netbox','infer']  (9)
remote_managed: thousandeyes, splunk            -> logs: vendor-hosted message
docker_compose: meraki, ise, netbox             -> logs: docker compose logs <svc>
docker_image/local_process: sdwan, catalyst_center, servicenow -> logs via gateway
local_process (compose infer-mcp): infer        -> logs: docker compose logs infer-mcp
```

### pytest / ruff
```
119 passed, 4 xfailed
ruff check .          -> All checks passed!
ruff format --check . -> all formatted
```


---

## Post-cleanup: argv fix + environment gates

### Argv fix — close the CLI `shell=True` sharp edge (security S2 follow-up)
- **File:** `packages/cli/miga_cli.py` (+ `tests/test_cli.py`). No other files touched.
- **What changed:** every `subprocess` call in the CLI was converted from an
  interpolated shell string (`shell=True`) to an **argv list with `shell=False`**.
  `_run(cmd: str)` → `_run(args: list[str])`; `_docker_compose(subcmd: str, services)`
  → `_docker_compose(args: list[str])`. All call sites updated: `deploy` (cp / build /
  up / helm), `status` (`docker compose ps`), **`logs`** (the registry-derived
  `compose_service` is now passed as a discrete argv element, never interpolated),
  `add-platform` (`up -d <svc>`), `stop` (`down`). `_run` catches `FileNotFoundError`
  and returns rc=127 to preserve the prior non-crashing behavior when a binary is
  absent. **No `shell=True` remains** (grep-verified). CLI behavior, flags, and output
  are unchanged.
- **Conversions left as-is:** none — every `shell=True` was eliminated.
- **Tests:** `tests/test_cli.py` added — asserts the `logs meraki` invocation is an
  argv list with `shell` not enabled and `meraki-mcp` as a discrete element; that a
  remote_managed server (`thousandeyes`) makes no subprocess call; and that
  `shell=True` is absent from the module.
- **Results:** `pytest` → **122 passed, 4 xfailed**; `ruff check .` → clean;
  `ruff format --check .` → clean.

### Gate 1 — Live OASF `validate_object` of the 9 records (C9): **NOT-RUN (no outbound network)**
- **Why NOT-RUN:** this sandbox has no outbound POST egress (`curl -X POST … ` →
  HTTP `000`; GET web-fetch of `…/api/version` returns no content). Not faked.
- **Authoritative endpoint** (from the OASF server source, `agntcy/oasf` router
  `server/lib/schema_web/router.ex`):
  - Validate a record: `POST /api/validate/object/record` — body is the record JSON
    (the server nests it under `_json` automatically). Optional
    `?warn_on_missing_recommended=true`.
  - Live version: `GET /api/version`.
- **Version delta:** records are pinned to **OASF schema v1.0.4** (latest stable
  release tag at the time; repo `main` is `1.1.0-dev`). The **live** server version
  could not be read here — confirm with `GET /api/version`. If it is **not** 1.0.4, do
  NOT edit the records blindly; re-validate and check whether any of these
  skill/domain ids shifted between versions (network taxonomy is stable across recent
  releases, but verify): skills `performance_monitoring(1105)`,
  `anomaly_detection(1104)`, `monitoring_alerting(1205)`, `threat_detection(801)`,
  `retrieval_of_information(601)`, `workflow_automation(1402)`,
  `api_schema_understanding(1401)`, `audit_trail_summarization(1303)`,
  `risk_classification(1304)`, `tool_use_planning(1403)`, `fact_extraction(10301)`,
  `document_or_database_question_answering(602)`,
  `information_retrieval_synthesis_search(10306)`, `analytical_reasoning(107)`,
  `hypothesis_generation(1504)`; domains `network_operations(10301)`,
  `network_management(10302)`, `network_architecture(10304)`,
  `network_security(10305)`, `wireless_communication(10802)`, `cybersecurity(10701)`,
  `identity_management(10705)`, `incident_management(10706)`,
  `workflow_automation(11002)`.
- **Reproducible commands (run from the repo root on a networked box):**
  ```bash
  # 1) Confirm the live schema version vs the pinned 1.0.4
  curl -s https://schema.oasf.outshift.com/api/version ; echo

  # 2) Validate all 9 records against the live endpoint
  for f in oasf/records/*.record.json; do
    echo "== $f =="
    curl -s -X POST \
      "https://schema.oasf.outshift.com/api/validate/object/record?warn_on_missing_recommended=true" \
      -H "Content-Type: application/json" \
      --data-binary @"$f"
    echo
  done
  ```
  A passing record returns an empty/`{}`-style result with no `errors`; failures list
  per-field messages.

### Gate 2 — `docker compose config` (D10): **PARTIAL PASS (schema + interpolation validated; docker CLI step still pending)**
- **Executed here (real tooling, not faked):**
  - Validated `docker-compose.yml` against the **official Compose Spec JSON schema**
    (`compose-spec/compose-spec` `schema/compose-spec.json`, Draft-07) → **VALID**.
  - Env-interpolation check across the file: every `${VAR}` is either defined in
    `.env.example` or carries a `:-default` → **no unresolved required variables**.
  - YAML service inventory: `agntcy-directory, gateway, infer-mcp, ise-mcp, meraki-mcp,
    netbox-mcp, redis, webex-bot` — compose-deployed servers (meraki/ise/netbox/infer)
    present, ThousandEyes/Splunk URL-only (not services), no dropped-platform services.
- **Still NOT-RUN (needs a Docker host):** the `docker` CLI is absent here, so the
  final normalize/merge step was not exercised. Run on a Docker box with a real `.env`:
  ```bash
  docker compose config --quiet   # exit 0 = valid (env interpolation + merge)
  docker compose config           # eyeball the rendered config
  ```
  Given the Compose Spec schema and interpolation already pass, this is expected to be
  a clean exit; it is the only remaining piece of D10.

## Gate closure (operator Mac, networked + Docker)
Both pre-publish gates executed and passed against live infrastructure.

Gate 1 (live OASF validate_object, C9): PASS. Server reports server_version 1.0.4 /
schema_version 1.0.0. Records corrected to schema_version 1.0.0 with full
hierarchical skill/domain names (ids unchanged, resolved by uid from the live
/api/skills and /api/domains catalogs). All 9 records return error_count 0,
warning_count 0.

Gate 2 (docker compose config, D10): PASS. `docker compose config --quiet` exit 0
on Docker 28.3.2 / Compose v2.38.2.

Verdict: GO for production. No pending gates.
