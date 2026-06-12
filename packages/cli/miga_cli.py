"""miga-cli — MIGA deployment and operations CLI.

Commands:
    miga-cli deploy          Deploy MIGA to target environment
    miga-cli status          Check health/reachability of all registered servers
    miga-cli logs            View logs for a locally-running service
    miga-cli add-platform    Start a compose-deployed platform server
    miga-cli rotate-secrets  Rotate API credentials
    miga-cli stop            Stop the cluster

The server/platform set is derived at runtime from config/server-registry.yaml
(the same loader the gateway uses) — there is no hardcoded platform list.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import click

from miga_shared.registry import ServerSpec, load_registry

INFRA_SERVICES = ["gateway", "webex-bot", "redis", "agntcy-directory"]


def _load_specs() -> list[ServerSpec]:
    """Load registered servers from the registry. Returns [] if unreadable so the
    CLI still imports (e.g. for --help) outside a repo checkout."""
    try:
        return load_registry()
    except Exception:  # noqa: BLE001 - CLI must stay importable
        return []


_SPECS = _load_specs()
SERVER_NAMES = [s.name for s in _SPECS]


def _spec(name: str) -> ServerSpec | None:
    norm = name.replace("-", "_")
    return next((s for s in _SPECS if s.name == norm), None)


def _deployment_kind(spec: ServerSpec) -> str:
    return (spec.deployment or {}).get("kind", "")


def _compose_service(spec: ServerSpec) -> str | None:
    """The docker-compose service that runs this server locally, if any.

    remote_managed servers have none (they are vendor-hosted). Otherwise prefer the
    registry's explicit compose_service, falling back to the `<name>-mcp` convention
    only when such a service exists in docker-compose.yml. Servers spawned as stdio
    subprocesses of the gateway (docker_image / local_process without their own
    service) return None and surface through the gateway's logs."""
    if _deployment_kind(spec) == "remote_managed":
        return None
    cs = (spec.deployment or {}).get("compose_service")
    if cs:
        return cs
    candidate = spec.name.replace("_", "-") + "-mcp"
    return candidate if candidate in _compose_services() else None


_COMPOSE_SERVICES_CACHE: list[str] | None = None


def _compose_services() -> list[str]:
    global _COMPOSE_SERVICES_CACHE
    if _COMPOSE_SERVICES_CACHE is None:
        try:
            import yaml

            with open("docker-compose.yml") as fh:
                _COMPOSE_SERVICES_CACHE = list(yaml.safe_load(fh).get("services", {}))
        except Exception:  # noqa: BLE001
            _COMPOSE_SERVICES_CACHE = []
    return _COMPOSE_SERVICES_CACHE


def _run(args: list[str], capture: bool = False) -> subprocess.CompletedProcess:
    """Run a command as an argv list with shell=False.

    Using an argv list (never an interpolated command string) means no
    registry-derived value (e.g. a compose_service name) can ever reach a shell.
    Falls back to a 127 result if the binary is missing, preserving the prior
    non-crashing behavior of the shell-based implementation."""
    try:
        return subprocess.run(args, shell=False, capture_output=capture, text=True)
    except FileNotFoundError:
        return subprocess.CompletedProcess(args, 127, stdout="", stderr="")


def _docker_compose(args: list[str]) -> int:
    """Run `docker compose <args...>` as argv (shell=False)."""
    return _run(["docker", "compose", *args]).returncode


# ---------------------------------------------------------------------------
# CLI Root
# ---------------------------------------------------------------------------


@click.group()
@click.version_option("1.0.0", prog_name="miga-cli")
def cli():
    """MIGA — MCP Intelligence Gateway Architecture CLI."""
    pass


# ---------------------------------------------------------------------------
# Deploy
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--env", type=click.Choice(["dev", "prod"]), default="dev", help="Target environment")
@click.option("--platforms", default="all", help="Comma-separated server list or 'all'")
@click.option("--build", is_flag=True, help="Build images before deploying")
@click.option("--detach/--no-detach", default=True, help="Run in background")
def deploy(env: str, platforms: str, build: bool, detach: bool):
    """Deploy MIGA cluster to the target environment."""
    click.echo(f"🚀 Deploying MIGA ({env})...")

    # Validate .env file
    if not os.path.exists(".env"):
        if os.path.exists(".env.example"):
            click.echo("⚠️  No .env found — copying .env.example")
            _run(["cp", ".env.example", ".env"])
        else:
            click.secho("❌ No .env or .env.example found.", fg="red")
            sys.exit(1)

    if env == "dev":
        # Docker Compose deployment
        services: list[str] = []
        if platforms != "all":
            selected = [p.strip() for p in platforms.split(",")]
            svc_names = []
            for p in selected:
                spec = _spec(p)
                cs = _compose_service(spec) if spec else None
                if cs:
                    svc_names.append(cs)
                else:
                    click.echo(f"   (skipping {p}: no local compose service)")
            services = INFRA_SERVICES + svc_names

        if build:
            click.echo("🔨 Building images...")
            _docker_compose(["build", *services])

        click.echo("📦 Starting services...")
        up_args = ["up"] + (["-d"] if detach else []) + services
        rc = _docker_compose(up_args)
        if rc == 0:
            click.secho("✅ MIGA cluster is running!", fg="green")
            click.echo("   Gateway: http://localhost:8000")
            click.echo("   Webex Bot: http://localhost:9000")
        else:
            click.secho("❌ Deployment failed.", fg="red")
            sys.exit(1)

    elif env == "prod":
        # Helm deployment
        click.echo("🎡 Deploying with Helm...")
        namespace = "miga"
        values = (
            f"helm/miga/values-{env}.yaml" if os.path.exists(f"helm/miga/values-{env}.yaml") else ""
        )
        helm_args = [
            "helm",
            "upgrade",
            "--install",
            "miga",
            "./helm/miga",
            "--namespace",
            namespace,
            "--create-namespace",
        ] + (["-f", values] if values else [])
        rc = _run(helm_args).returncode
        if rc == 0:
            click.secho("✅ MIGA deployed to Kubernetes!", fg="green")
        else:
            click.secho("❌ Helm deployment failed.", fg="red")
            sys.exit(1)


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


def _compose_state_map() -> dict[str, str]:
    """Map docker-compose service name -> state string (best effort)."""
    result = _run(["docker", "compose", "ps", "--format", "json"], capture=True)
    states: dict[str, str] = {}
    if result.returncode != 0 or not result.stdout.strip():
        return states
    for line in result.stdout.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            svc = json.loads(line)
        except json.JSONDecodeError:
            continue
        name = svc.get("Service", svc.get("Name", ""))
        states[name] = svc.get("State", svc.get("Status", "unknown"))
    return states


@cli.command()
@click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="table")
def status(fmt: str):
    """Check health/reachability of all registered servers + infra."""
    states = _compose_state_map()

    rows: list[dict[str, str]] = []
    # Infrastructure services
    for name in INFRA_SERVICES:
        rows.append({"name": name, "kind": "infra", "state": states.get(name, "absent")})
    # All registered servers (from the registry — always the full current set)
    for spec in _SPECS:
        kind = _deployment_kind(spec)
        if kind == "remote_managed":
            state = "remote (vendor-hosted)"
        else:
            cs = _compose_service(spec)
            if cs:
                state = states.get(cs, "absent")
            else:
                state = "stdio (spawned on demand by gateway)"
        rows.append({"name": spec.name, "kind": kind or "server", "state": state})

    if fmt == "json":
        click.echo(json.dumps(rows, indent=2))
        return

    click.echo(f"\n{'Service':<22} {'Deployment':<16} {'State'}")
    click.echo("-" * 70)
    for r in rows:
        s = r["state"].lower()
        if "running" in s or "remote" in s or "stdio" in s:
            emoji = "🟢" if "running" in s else "🌐" if "remote" in s else "⚙️"
        else:
            emoji = "🔴"
        click.echo(f"  {emoji} {r['name']:<20} {r['kind']:<16} {r['state']}")


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("service")
@click.option("--follow", "-f", is_flag=True, help="Follow log output")
@click.option("--tail", default=100, help="Number of lines")
def logs(service: str, follow: bool, tail: int):
    """View logs for a locally-running service.

    Only servers that run locally have logs: infra services, compose-deployed
    servers (Meraki, ISE, NetBox, INFER), or stdio servers spawned by the gateway.
    Remote, vendor-hosted servers (ThousandEyes, Splunk) have no local logs.
    """
    log_flags = ["--tail", str(tail)] + (["-f"] if follow else [])
    norm = service.replace("-", "_")

    # Infra services / direct compose service names pass straight through.
    if service in INFRA_SERVICES or service in _compose_services():
        _run(["docker", "compose", "logs", *log_flags, service])
        return

    spec = _spec(norm)
    if spec is None:
        click.secho(f"❌ Unknown service '{service}'.", fg="red")
        valid = INFRA_SERVICES + [s.name for s in _SPECS if _deployment_kind(s) != "remote_managed"]
        click.echo(f"   Local services with logs: {', '.join(valid)}")
        sys.exit(1)

    if _deployment_kind(spec) == "remote_managed":
        click.secho(
            f"ℹ️  '{spec.name}' is hosted by Cisco/the vendor — logs are not available "
            f"locally. Inspect it in the {spec.display_name} console.",
            fg="yellow",
        )
        return

    cs = _compose_service(spec)
    if cs:
        _run(["docker", "compose", "logs", *log_flags, cs])
    else:
        # docker_image / local_process spawned as a stdio subprocess of the gateway.
        click.secho(
            f"ℹ️  '{spec.name}' runs as a stdio subprocess of the gateway; its output "
            f"appears in the gateway logs. Showing `miga logs gateway`:",
            fg="yellow",
        )
        _run(["docker", "compose", "logs", *log_flags, "gateway"])


# ---------------------------------------------------------------------------
# Add Platform
# ---------------------------------------------------------------------------


@cli.command("add-platform")
@click.argument("platform", type=click.Choice(SERVER_NAMES) if SERVER_NAMES else str)
def add_platform(platform: str):
    """Start a compose-deployed platform server."""
    spec = _spec(platform)
    cs = _compose_service(spec) if spec else None
    if not cs:
        click.secho(
            f"ℹ️  '{platform}' has no local compose service "
            f"(remote-hosted or spawned by the gateway); nothing to start.",
            fg="yellow",
        )
        return
    click.echo(f"📦 Starting {platform} server ({cs})...")
    rc = _docker_compose(["up", "-d", cs])
    if rc == 0:
        click.secho(f"✅ {platform} server is running!", fg="green")
    else:
        click.secho(f"❌ Failed to start {platform}.", fg="red")


# ---------------------------------------------------------------------------
# Rotate Secrets
# ---------------------------------------------------------------------------


@cli.command("rotate-secrets")
@click.option(
    "--platform",
    type=click.Choice(SERVER_NAMES) if SERVER_NAMES else str,
    help="Rotate for specific server",
)
def rotate_secrets(platform: str | None):
    """Rotate API credentials and restart affected services."""
    targets = [platform] if platform else SERVER_NAMES
    click.echo(f"🔐 Rotating secrets for: {', '.join(targets)}")
    click.echo("⚠️  Update your .env file with new credentials, then run:")
    click.echo("   miga-cli deploy --env dev --build")
    click.echo("\nFor Kubernetes:")
    click.echo(
        "   kubectl create secret generic miga-secrets --from-env-file=.env -n miga --dry-run=client -o yaml | kubectl apply -f -"
    )
    click.echo("   kubectl rollout restart deployment -n miga")


# ---------------------------------------------------------------------------
# Stop
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--volumes", "-v", is_flag=True, help="Remove volumes too")
def stop(volumes: bool):
    """Stop all MIGA services."""
    click.echo("🛑 Stopping MIGA cluster...")
    _docker_compose(["down"] + (["-v"] if volumes else []))
    click.secho("✅ Cluster stopped.", fg="green")


if __name__ == "__main__":
    cli()
