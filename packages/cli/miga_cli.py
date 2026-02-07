"""miga-cli — MIGA deployment and operations CLI.

Commands:
    miga-cli deploy    Deploy MIGA to target environment
    miga-cli status    Check health of all services
    miga-cli logs      View service logs
    miga-cli add-platform  Enable a stubbed platform
    miga-cli rotate-secrets  Rotate API credentials
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Optional

import click

PLATFORMS = [
    "catalyst-center", "meraki", "thousandeyes", "webex", "xdr",
    "security-cloud-control", "infer", "appdynamics", "nexus-dashboard",
    "sdwan", "ise", "splunk", "hypershield",
]
INFRA_SERVICES = ["gateway", "webex-bot", "redis", "agntcy-directory"]


def _run(cmd: str, capture: bool = False) -> subprocess.CompletedProcess:
    """Run a shell command."""
    return subprocess.run(cmd, shell=True, capture_output=capture, text=True)


def _docker_compose(subcmd: str, services: list[str] | None = None) -> int:
    svc = " ".join(services) if services else ""
    return _run(f"docker compose {subcmd} {svc}").returncode


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
@click.option("--platforms", default="all", help="Comma-separated platform list or 'all'")
@click.option("--build", is_flag=True, help="Build images before deploying")
@click.option("--detach/--no-detach", default=True, help="Run in background")
def deploy(env: str, platforms: str, build: bool, detach: bool):
    """Deploy MIGA cluster to the target environment."""
    click.echo(f"🚀 Deploying MIGA ({env})...")

    # Validate .env file
    if not os.path.exists(".env"):
        if os.path.exists(".env.example"):
            click.echo("⚠️  No .env found — copying .env.example")
            _run("cp .env.example .env")
        else:
            click.secho("❌ No .env or .env.example found.", fg="red")
            sys.exit(1)

    if env == "dev":
        # Docker Compose deployment
        services = []
        if platforms != "all":
            selected = [p.strip() for p in platforms.split(",")]
            svc_names = [p.replace("-", "_") + "_mcp" for p in selected]
            services = INFRA_SERVICES + svc_names
        else:
            services = []  # all services

        if build:
            click.echo("🔨 Building images...")
            _docker_compose("build", services or None)

        flags = "-d" if detach else ""
        click.echo("📦 Starting services...")
        rc = _docker_compose(f"up {flags}", services or None)
        if rc == 0:
            click.secho("✅ MIGA cluster is running!", fg="green")
            click.echo("   Gateway: http://localhost:8000")
            click.echo("   WebEx Bot: http://localhost:9000")
        else:
            click.secho("❌ Deployment failed.", fg="red")
            sys.exit(1)

    elif env == "prod":
        # Helm deployment
        click.echo("🎡 Deploying with Helm...")
        namespace = "miga"
        values = f"helm/miga/values-{env}.yaml" if os.path.exists(f"helm/miga/values-{env}.yaml") else ""
        values_flag = f"-f {values}" if values else ""
        rc = _run(f"helm upgrade --install miga ./helm/miga --namespace {namespace} --create-namespace {values_flag}").returncode
        if rc == 0:
            click.secho("✅ MIGA deployed to Kubernetes!", fg="green")
        else:
            click.secho("❌ Helm deployment failed.", fg="red")
            sys.exit(1)


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="table")
def status(fmt: str):
    """Check health of all MIGA services."""
    result = _run("docker compose ps --format json", capture=True)
    if result.returncode != 0:
        click.secho("❌ Could not query Docker Compose.", fg="red")
        sys.exit(1)

    try:
        # docker compose ps --format json outputs one JSON per line
        services = []
        for line in result.stdout.strip().split("\n"):
            if line.strip():
                services.append(json.loads(line))
    except json.JSONDecodeError:
        click.echo(result.stdout)
        return

    if fmt == "json":
        click.echo(json.dumps(services, indent=2))
        return

    click.echo(f"\n{'Service':<35} {'Status':<15} {'Ports'}")
    click.echo("-" * 70)
    for svc in services:
        name = svc.get("Name", svc.get("Service", "unknown"))
        state = svc.get("State", svc.get("Status", "unknown"))
        ports = svc.get("Publishers", [])
        port_str = ", ".join(f"{p.get('PublishedPort', '?')}→{p.get('TargetPort', '?')}" for p in ports if isinstance(p, dict)) if isinstance(ports, list) else str(ports)
        emoji = "🟢" if "running" in state.lower() else "🔴"
        click.echo(f"  {emoji} {name:<33} {state:<15} {port_str}")


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("service")
@click.option("--follow", "-f", is_flag=True, help="Follow log output")
@click.option("--tail", default=100, help="Number of lines")
def logs(service: str, follow: bool, tail: int):
    """View logs for a MIGA service."""
    svc_name = service.replace("-", "_")
    # Try exact name, then with _mcp suffix
    flags = f"--tail {tail}"
    if follow:
        flags += " -f"
    rc = _run(f"docker compose logs {flags} {svc_name}").returncode
    if rc != 0:
        _run(f"docker compose logs {flags} {svc_name}_mcp")


# ---------------------------------------------------------------------------
# Add Platform
# ---------------------------------------------------------------------------

@cli.command("add-platform")
@click.argument("platform", type=click.Choice(PLATFORMS))
def add_platform(platform: str):
    """Enable a stubbed platform server."""
    svc_name = platform.replace("-", "_") + "_mcp"
    click.echo(f"📦 Starting {platform} server...")
    rc = _docker_compose(f"up -d", [svc_name])
    if rc == 0:
        click.secho(f"✅ {platform} server is running!", fg="green")
    else:
        click.secho(f"❌ Failed to start {platform}.", fg="red")


# ---------------------------------------------------------------------------
# Rotate Secrets
# ---------------------------------------------------------------------------

@cli.command("rotate-secrets")
@click.option("--platform", type=click.Choice(PLATFORMS), help="Rotate for specific platform")
def rotate_secrets(platform: Optional[str]):
    """Rotate API credentials and restart affected services."""
    targets = [platform] if platform else PLATFORMS
    click.echo(f"🔐 Rotating secrets for: {', '.join(targets)}")
    click.echo("⚠️  Update your .env file with new credentials, then run:")
    click.echo(f"   miga-cli deploy --env dev --build")
    click.echo("\nFor Kubernetes:")
    click.echo("   kubectl create secret generic miga-secrets --from-env-file=.env -n miga --dry-run=client -o yaml | kubectl apply -f -")
    click.echo("   kubectl rollout restart deployment -n miga")


# ---------------------------------------------------------------------------
# Stop
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--volumes", "-v", is_flag=True, help="Remove volumes too")
def stop(volumes: bool):
    """Stop all MIGA services."""
    click.echo("🛑 Stopping MIGA cluster...")
    flags = "-v" if volumes else ""
    _docker_compose(f"down {flags}")
    click.secho("✅ Cluster stopped.", fg="green")


if __name__ == "__main__":
    cli()
