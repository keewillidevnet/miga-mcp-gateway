"""Tests for the miga CLI — focus on the argv (shell=False) logs invocation.

A registry-derived compose_service name must reach subprocess as a discrete argv
element, never interpolated into a shell command string.
"""

from __future__ import annotations

from click.testing import CliRunner

import packages.cli.miga_cli as cli


class _FakeCP:
    def __init__(self, rc=0, stdout=""):
        self.returncode = rc
        self.stdout = stdout
        self.stderr = ""


def _capture_subprocess(monkeypatch):
    calls: list[dict] = []

    def fake_run(args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        return _FakeCP(0, stdout="")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    return calls


def test_logs_uses_argv_list_not_shell(monkeypatch):
    calls = _capture_subprocess(monkeypatch)
    result = CliRunner().invoke(cli.cli, ["logs", "meraki"])
    assert result.exit_code == 0, result.output
    assert calls, "subprocess.run was not invoked"
    last = calls[-1]
    # argv form (a list), shell never enabled
    assert isinstance(last["args"], list)
    assert last["kwargs"].get("shell", False) is False
    # the registry-derived compose service is a discrete list element
    assert "meraki-mcp" in last["args"]
    assert last["args"][:3] == ["docker", "compose", "logs"]


def test_logs_remote_server_makes_no_subprocess_call(monkeypatch):
    calls = _capture_subprocess(monkeypatch)
    result = CliRunner().invoke(cli.cli, ["logs", "thousandeyes"])
    assert result.exit_code == 0, result.output
    assert "not available" in result.output.lower()
    assert calls == []  # remote_managed → no local logs, no shell-out


def test_no_shell_true_anywhere_in_cli():
    with open(cli.__file__) as fh:
        src = fh.read()
    assert "shell=True" not in src
