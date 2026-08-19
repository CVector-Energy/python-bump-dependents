"""Behaviour of the version-specifier rewrite.

These are the decisions that matter when a bad rewrite would land in a PR against every
consumer at once: which specifiers move, which are deliberately left alone, and that nothing
outside the package's own specifier is touched.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "rewrite_specifier.py"
sys.path.insert(0, str(SCRIPT.parent))

from rewrite_specifier import rewrite  # noqa: E402


def write(tmp_path: pathlib.Path, body: str, name: str = "pyproject.toml") -> pathlib.Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return path


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ('"aion-sdk>=0.7.1"', '"aion-sdk>=0.8.0"'),
        ('"aion-sdk==0.7.1"', '"aion-sdk==0.8.0"'),
        ('"aion-sdk~=0.7.1"', '"aion-sdk~=0.8.0"'),
        ('"aion-sdk>0.7.1"', '"aion-sdk>0.8.0"'),
        ('"aion-sdk===0.7.1"', '"aion-sdk===0.8.0"'),
        # Extras and the operator survive; only the version moves.
        ('"aion-sdk[knowledge]>=0.7.1"', '"aion-sdk[knowledge]>=0.8.0"'),
        ('"aion-sdk[knowledge,extra]>=0.7.1"', '"aion-sdk[knowledge,extra]>=0.8.0"'),
        # PEP 503 says these name the same package.
        ('"aion_sdk>=0.7.1"', '"aion_sdk>=0.8.0"'),
        ('"aion.sdk>=0.7.1"', '"aion.sdk>=0.8.0"'),
    ],
)
def test_moves_the_specifier(tmp_path, before, after):
    path = write(tmp_path, f"dependencies = [{before}]\n")
    assert rewrite(tmp_path, "aion-sdk", "0.8.0") == [path]
    assert path.read_text() == f"dependencies = [{after}]\n"


def test_leaves_an_unconstrained_dependency_alone():
    """A bare name already resolves to the newest release; pinning it would be a policy change."""
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        tmp = pathlib.Path(d)
        path = write(tmp, 'dependencies = ["aion-sdk"]\n')
        assert rewrite(tmp, "aion-sdk", "0.8.0") == []
        assert path.read_text() == 'dependencies = ["aion-sdk"]\n'


def test_leaves_other_packages_alone(tmp_path):
    body = 'dependencies = ["aion-sdk>=0.7.1", "boto3>=1.0.0", "aion-sdk-extras>=2.0.0"]\n'
    path = write(tmp_path, body)
    rewrite(tmp_path, "aion-sdk", "0.8.0")
    text = path.read_text()
    assert '"aion-sdk>=0.8.0"' in text
    assert '"boto3>=1.0.0"' in text
    # A longer name that merely starts with the package name is a different package.
    assert '"aion-sdk-extras>=2.0.0"' in text


def test_reports_only_files_it_changed(tmp_path):
    changed = write(tmp_path, 'dependencies = ["aion-sdk>=0.7.1"]\n', "a/pyproject.toml")
    write(tmp_path, 'dependencies = ["boto3>=1.0.0"]\n', "b/pyproject.toml")
    assert rewrite(tmp_path, "aion-sdk", "0.8.0") == [changed]


def test_is_idempotent(tmp_path):
    write(tmp_path, 'dependencies = ["aion-sdk>=0.8.0"]\n')
    assert rewrite(tmp_path, "aion-sdk", "0.8.0") == []


def test_skips_vendored_trees(tmp_path):
    """A pyproject.toml under .venv belongs to a resolved dependency, not to this repository."""
    vendored = write(tmp_path, 'dependencies = ["aion-sdk>=0.7.1"]\n', ".venv/lib/pyproject.toml")
    assert rewrite(tmp_path, "aion-sdk", "0.8.0") == []
    assert "0.7.1" in vendored.read_text()


def test_handles_a_dev_version(tmp_path):
    path = write(tmp_path, 'dependencies = ["aion-sdk>=0.7.1"]\n')
    rewrite(tmp_path, "aion-sdk", "0.7.2.dev1+g2f463d36e")
    assert '"aion-sdk>=0.7.2.dev1+g2f463d36e"' in path.read_text()


def test_cli_prints_changed_paths(tmp_path):
    write(tmp_path, 'dependencies = ["aion-sdk>=0.7.1"]\n')
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "aion-sdk", "0.8.0", "--root", str(tmp_path)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip().endswith("pyproject.toml")
