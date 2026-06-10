# MIGA Refactor — Validation Report (post-cleanup)

**Verdict: GO for production** — pending two environment-only pre-publish gates that
could not be exercised in the audit sandbox (live OASF endpoint validation C9, and
`docker compose config` D10). All functional checklist items A–I pass.

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
