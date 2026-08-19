"""Behaviour of the relock loop, driven through a stub `uv` on PATH.

The failure policy is the point: one project that will not lock must not cost the repository
its whole PR, but every project failing must stop the run rather than raise a PR with no
lockfile changes in it.
"""

from __future__ import annotations

import pathlib
import subprocess

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "relock.sh"


def make_uv(tmp_path: pathlib.Path, body: str) -> pathlib.Path:
    """Put a stub `uv` on PATH. It appends each invocation's cwd to a log."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    uv = bindir / "uv"
    uv.write_text("#!/usr/bin/env bash\n" + body)
    uv.chmod(0o755)
    return bindir


def run(tmp_path: pathlib.Path, bindir: pathlib.Path):
    import os

    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}")
    return subprocess.run(
        ["bash", str(SCRIPT), "aion-sdk"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )


def project(tmp_path: pathlib.Path, *names: str) -> None:
    for name in names:
        d = tmp_path / name if name else tmp_path
        d.mkdir(parents=True, exist_ok=True)
        (d / "uv.lock").write_text("")


def test_relocks_every_project(tmp_path):
    bindir = make_uv(tmp_path, f'pwd >> "{tmp_path}/log"\nexit 0\n')
    project(tmp_path, "a", "b")
    result = run(tmp_path, bindir)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ""
    log = (tmp_path / "log").read_text()
    # Two projects, two passes: a monorepo's dependent locks only settle on the second.
    assert log.count("/a") == 2
    assert log.count("/b") == 2


def test_reports_a_partial_failure_without_failing(tmp_path):
    bindir = make_uv(tmp_path, '[[ "$PWD" == */broken ]] && exit 1\nexit 0\n')
    project(tmp_path, "ok", "broken")
    result = run(tmp_path, bindir)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "./broken"


def test_fails_when_every_project_fails(tmp_path):
    bindir = make_uv(tmp_path, "exit 1\n")
    project(tmp_path, "a", "b")
    result = run(tmp_path, bindir)
    assert result.returncode == 1
    assert "failed in every project" in result.stderr


def test_no_lockfiles_is_a_clean_no_op(tmp_path):
    bindir = make_uv(tmp_path, "exit 1\n")
    result = run(tmp_path, bindir)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ""


def test_ignores_vendored_lockfiles(tmp_path):
    bindir = make_uv(tmp_path, f'pwd >> "{tmp_path}/log"\nexit 0\n')
    project(tmp_path, "a")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "uv.lock").write_text("")
    result = run(tmp_path, bindir)
    assert result.returncode == 0, result.stderr
    assert ".venv" not in (tmp_path / "log").read_text()


def test_passes_the_package_to_uv(tmp_path):
    bindir = make_uv(tmp_path, f'echo "$@" >> "{tmp_path}/args"\nexit 0\n')
    project(tmp_path, "a")
    run(tmp_path, bindir)
    assert "lock --upgrade-package aion-sdk" in (tmp_path / "args").read_text()
