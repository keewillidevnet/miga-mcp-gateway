# DISCOVERY_VERIFY.md: verify directory-search discovery routing on the Mac

Status: **implemented, opt-in, pending live verification.** Directory-search routing is
authored and unit-tested with the SDK mocked. It was NOT run against a live directory
(the build workspace has no agntcy-dir SDK, no Docker, no buf.build egress). Default is
OFF (`MIGA_DISCOVERY_ROUTING` unset), and the static `config/server-registry.yaml` is
the guaranteed fallback. Run the steps below on the Mac, then flip the README note from
"pending live verification" to "verified".

## What it does
With `MIGA_DISCOVERY_ROUTING=1`, each role meta-tool resolves its servers by searching
the AGNTCY Directory for the role's OASF skills (`config/role-skills.yaml`), mapping each
matched record back to a registry server via `annotations.miga_registry_ref`, then
fanning out to those servers' transports. If the search returns nothing or the directory
is unavailable, the gateway uses the static registry exactly as before.

## One open item: confirm the search request shape
`DirectoryClient._search_sync` builds the search request from assumed field names and is
marked with a `TODO`. Confirm the real shape against agntcy-dir 1.3.0 before relying on
it. Until confirmed, a wrong shape is caught and `discover()` returns `[]`, so routing
falls back to static (no breakage, just no discovery).

### (a) Introspect the real request/query types
In the agntcy-dir 1.3.0 venv (e.g. `/tmp/dirsdk`):
```bash
# find the search model module name
python -c "import agntcy.dir_sdk.models as m; print([n for n in dir(m) if 'search' in n.lower()])"

# print the request + query fields and the query-type enum (adjust 'search_v1' if needed)
python -c "
from agntcy.dir_sdk.models import search_v1 as sv
print('SearchRecordsRequest fields:', [f.name for f in sv.SearchRecordsRequest.DESCRIPTOR.fields])
print('RecordQuery fields:', [f.name for f in sv.RecordQuery.DESCRIPTOR.fields])
print('RecordQueryType values:', list(sv.RecordQueryType.keys()))
"
```

### (b) Finalize the construction
If the printed fields differ from the assumed ones in `_search_sync` (currently
`SearchRecordsRequest(queries=[RecordQuery(type=RECORD_QUERY_TYPE_SKILL, value=...)],
limit=...)`), update `_search_sync` to match:
- the actual request field that holds queries (and `limit`),
- the actual `RecordQuery` field names (type/value or key/value),
- the actual enum member for a skill query (the `RecordQueryType` value that matches by
  skill name).
Also confirm what `search_records` returns (records with `.data`, or refs/CIDs). The
code handles both: it decodes `.data` if present, otherwise pulls by CID.

## (c) Bring up the stack with discovery ON
```bash
docker compose up -d            # full dir stack + gateway (see VERIFY_DIRECTORY.md)
# enable discovery routing for the gateway:
MIGA_DISCOVERY_ROUTING=1 docker compose up -d gateway
# (or set MIGA_DISCOVERY_ROUTING=1 in .env / the gateway service environment)
```

## (d) Confirm discovery drives routing
Issue a role query (via the Webex bot or a direct MCP call to a role meta-tool, e.g.
`observability`), then check the logs:
```bash
docker compose logs gateway | grep -iE "resolved via directory search|using static registry"
```
Expected on success: `role observability resolved via directory search: ['thousandeyes', ...]`,
and the role query still fans out and returns results. If you see "using static registry",
discovery returned nothing (likely the request-shape TODO) and the fallback engaged.

Optional negative check (fallback is intact): stop the directory and re-issue the query;
the gateway must still answer from the static registry.

## (e) Flip the README only after the above pass
When (a)-(d) succeed, change the README "Directory-search routing discovery" row from
"Implemented (opt-in; pending live verification)" to "Implemented (opt-in; verified live)"
and note the evidence here.

## Success criteria
- [ ] `_search_sync` request shape confirmed against agntcy-dir 1.3.0 (TODO resolved).
- [ ] With `MIGA_DISCOVERY_ROUTING=1`, logs show "resolved via directory search" for at
      least one role, and the role query returns results.
- [ ] With the directory stopped (or the flag unset), routing still works from the static
      registry (guaranteed fallback).
