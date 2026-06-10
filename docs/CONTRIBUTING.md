# Contributing to MIGA

Thank you for your interest in contributing to MIGA! MIGA is an **aggregation /
fusion layer**: it routes to real, published MCP servers across the ecosystem and
adds cross-platform reasoning via INFER. Contributing a platform therefore means
**registering an existing MCP server** so the gateway can route to it — not writing
a new server implementation inside this repo.

## Quick Start

```bash
git clone https://github.com/keewillidevnet/miga-mcp-gateway.git && cd miga-mcp-gateway
cp .env.example .env
docker compose up -d
python -m packages.cli.miga_cli status
```

## Architecture in one paragraph

`config/server-registry.yaml` is the single source of truth for **how the gateway
connects** to each downstream MCP server (transport, endpoint/command, auth, env
vars). Each server also publishes an **OASF capability record** (`oasf/records/`)
so it is discoverable via the AGNTCY Directory. The gateway loads the registry
(`miga_shared/registry.py`) and connects as an MCP **client** over the right
transport (`miga_shared/transport.py`): remote HTTP/SSE URLs or local stdio
subprocesses (including the `docker run -i` pattern). MIGA does not re-vendor or
re-implement upstream server logic. The only MIGA-original server is **INFER**
(`servers/infer_mcp`).

## Adding a platform (the normal contribution)

You are wiring up an existing, published MCP server. No new `servers/<platform>`
directory is created.

1. **Add a registry entry** to `config/server-registry.yaml` with: `name`,
   `display_name`, `status` (`official` | `cisco_devnet_community` | `community`),
   `roles`, a `transport` block, a `deployment` block, `env_required` (env var
   *names* only — never secrets), and the `oasf_record` path. Validate it:

   ```bash
   python - <<'PY'
   import yaml, json, jsonschema
   reg = yaml.safe_load(open("config/server-registry.yaml"))
   schema = json.load(open("config/server-registry.schema.json"))
   jsonschema.validate(reg, schema)
   print("registry valid")
   PY
   ```

   - **Remote HTTP/SSE server** → `transport: {type: http, url: ..., auth: {...}}`,
     `deployment: {kind: remote_managed}`. Reference it by URL; do **not** add a
     compose service.
   - **Container you run** → `transport: {type: http, url: http://<svc>:<port>/mcp}`,
     `deployment: {kind: docker_compose, compose_service: <svc>, ports: [...]}`, and
     add the service to `docker-compose.yml` wired from `.env`.
   - **Docker stdio image** → `transport: {type: stdio, command: docker, args: [run, -i, --rm, -e, VAR, ..., <image>]}`,
     `deployment: {kind: docker_image, image: <image>}`.
   - **Local stdio process** (bundled in the gateway image) →
     `transport: {type: stdio, command: ..., args: [...]}`,
     `deployment: {kind: local_process}`.

2. **Author an OASF record** at the `oasf_record` path, following
   `oasf/OASF_RECORDS.md`. Every skill/domain/module `name` and numeric `id` **must**
   come from the live OASF catalogs (skill_categories / domain_categories /
   module_categories) — do not invent ids. Validate the record against the OASF
   schema/validation endpoint before submitting.

3. **Wire env + deployment**: add every `env_required` var to `.env.example`
   (grouped by platform, placeholder values, no secrets). For compose servers add
   the service to `docker-compose.yml`; for stdio servers confirm the gateway image
   can spawn the command.

4. **Verify**:

   ```bash
   pytest -q
   ruff check . && ruff format --check .
   python -m packages.cli.miga_cli status   # your server should appear in the list
   ```

The gateway discovers and routes to your server automatically from the registry —
**no gateway code changes are required.**

## Working on INFER

INFER (`servers/infer_mcp`) is MIGA's own fusion engine and the one server whose
logic lives in this repo. Improvements to correlation, root-cause templates, anomaly
detection, prediction, or risk scoring are welcome. INFER consumes the normalized
output of whatever servers are registered, so keep it platform-agnostic.

## Code Style

- Python 3.11+
- Ruff for linting and formatting (`ruff check .` and `ruff format .`)
- Type hints on all public functions
- Pydantic models for tool inputs; docstrings on all tools (shown to MCP clients)

## Testing

```bash
pytest tests/ -v
```

Tests that exercise downstream connectivity must **mock the MCP client transport**
(see `tests/test_transport.py` and `tests/test_gateway.py`) — never require live
credentials.

## Commit Messages

Use conventional commits, e.g. `feat(registry): add Cisco Nexus Dashboard MCP entry`.

## License

By contributing, you agree that your contributions will be licensed under the
Apache 2.0 License.
