"""MIGA downstream server registry loader.

Single source of truth for *how the gateway connects* to each downstream MCP
server. Parses ``config/server-registry.yaml``, validates it against
``config/server-registry.schema.json``, resolves ``${ENV}`` placeholders from the
process environment, and exposes typed :class:`ServerSpec` objects to the gateway
and the transport layer.

Secrets never live in the registry — only env var *names* are referenced. Values
are read from the environment (``.env``) at runtime.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("miga.registry")

# Repo-relative default locations.
_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REGISTRY_PATH = _REPO_ROOT / "config" / "server-registry.yaml"
DEFAULT_SCHEMA_PATH = _REPO_ROOT / "config" / "server-registry.schema.json"

_ENV_RE = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _resolve_env(value: Any, *, environ: dict[str, str] | None = None) -> Any:
    """Recursively substitute ``${ENV}`` placeholders using ``environ`` (defaults
    to ``os.environ``). Unset variables are left as the literal placeholder so the
    gateway can surface a clear "missing env" error instead of a silent blank."""
    env = environ if environ is not None else os.environ
    if isinstance(value, str):
        return _ENV_RE.sub(lambda m: env.get(m.group(1), m.group(0)), value)
    if isinstance(value, list):
        return [_resolve_env(v, environ=env) for v in value]
    if isinstance(value, dict):
        return {k: _resolve_env(v, environ=env) for k, v in value.items()}
    return value


@dataclass
class ServerSpec:
    """A single downstream MCP server the gateway routes to, as declared in the
    registry. ``transport`` is the connection method; ``deployment`` is how the
    process is provisioned (a separate concern)."""

    name: str
    display_name: str
    status: str
    roles: list[str]
    transport: dict[str, Any]
    oasf_record: str
    enabled: bool = True
    source: str = ""
    deployment: dict[str, Any] = field(default_factory=dict)
    env_required: list[str] = field(default_factory=list)

    # -- transport helpers ----------------------------------------------------

    @property
    def transport_type(self) -> str:
        return self.transport.get("type", "")

    @property
    def url(self) -> str | None:
        return self.transport.get("url")

    @property
    def command(self) -> str | None:
        return self.transport.get("command")

    @property
    def args(self) -> list[str]:
        return list(self.transport.get("args", []))

    def auth_headers(self, *, environ: dict[str, str] | None = None) -> dict[str, str]:
        """Build HTTP auth headers for http transports. For ``bearer`` auth the
        token is read from the env var named in ``auth.token_env`` and injected as
        ``Authorization: Bearer <token>``. Any static ``headers`` are merged in."""
        env = environ if environ is not None else os.environ
        headers: dict[str, str] = dict(self.transport.get("headers", {}))
        auth = self.transport.get("auth") or {}
        if auth.get("type") == "bearer":
            token_env = auth.get("token_env")
            token = env.get(token_env, "") if token_env else ""
            url = self.url or ""
            if token and not url.startswith("https://"):
                # Refuse to send a bearer token over a non-TLS endpoint — prevents
                # token leakage / exfiltration if the URL (or its ${ENV} host) is
                # tampered with. Fails closed: no Authorization header is attached.
                logger.error(
                    "Server %s: refusing to attach bearer token to non-https URL %r",
                    self.name,
                    url,
                )
            elif token:
                headers["Authorization"] = f"Bearer {token}"
            else:
                logger.warning(
                    "Server %s: bearer token env %s is unset; no Authorization header set",
                    self.name,
                    token_env,
                )
        return headers

    def missing_env(self, *, environ: dict[str, str] | None = None) -> list[str]:
        env = environ if environ is not None else os.environ
        return [k for k in self.env_required if not env.get(k)]


def _load_yaml(path: Path) -> dict[str, Any]:
    import yaml  # local import keeps PyYAML optional for non-registry code paths

    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def validate_registry(raw: dict[str, Any], schema_path: Path = DEFAULT_SCHEMA_PATH) -> None:
    """Validate a parsed registry document against the JSON schema. Raises
    ``jsonschema.ValidationError`` on failure. Silently skips if jsonschema is not
    installed (so production import never hard-fails on a missing dev dependency),
    logging a warning instead."""
    try:
        import json

        import jsonschema
    except ImportError:  # pragma: no cover - defensive
        logger.warning("jsonschema not installed; skipping registry schema validation")
        return
    with open(schema_path, encoding="utf-8") as fh:
        schema = json.load(fh)
    jsonschema.validate(raw, schema)


def load_registry(
    path: Path | str = DEFAULT_REGISTRY_PATH,
    *,
    schema_path: Path | str = DEFAULT_SCHEMA_PATH,
    validate: bool = True,
    resolve_env: bool = True,
    enabled_only: bool = True,
    environ: dict[str, str] | None = None,
) -> list[ServerSpec]:
    """Load and validate the registry, returning typed :class:`ServerSpec` objects.

    ``${ENV}`` placeholders inside transport fields are resolved from ``environ``
    (defaults to ``os.environ``) unless ``resolve_env=False``.
    """
    path = Path(path)
    raw = _load_yaml(path)
    if validate:
        validate_registry(raw, Path(schema_path))

    specs: list[ServerSpec] = []
    for entry in raw.get("servers", []):
        if enabled_only and not entry.get("enabled", True):
            continue
        transport = entry.get("transport", {})
        if resolve_env:
            transport = _resolve_env(transport, environ=environ)
        specs.append(
            ServerSpec(
                name=entry["name"],
                display_name=entry.get("display_name", entry["name"]),
                status=entry.get("status", "community"),
                roles=list(entry.get("roles", [])),
                transport=transport,
                oasf_record=entry.get("oasf_record", ""),
                enabled=entry.get("enabled", True),
                source=entry.get("source", ""),
                deployment=entry.get("deployment", {}) or {},
                env_required=list(entry.get("env_required", [])),
            )
        )
    logger.info("Loaded %d enabled servers from registry %s", len(specs), path)
    return specs
