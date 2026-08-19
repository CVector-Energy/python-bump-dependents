"""Move a package's version specifier in every pyproject.toml under the tree.

Prints the path of each file it changed, one per line, so the caller can report what moved.

Kept out of the action's YAML because this is the one piece with real logic in it: which
specifiers to touch and which to leave alone. tests/test_rewrite_specifier.py exercises it
directly.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

# Directories that hold resolved copies of other people's code rather than this
# repository's own manifests. A pyproject.toml under one of these is not ours to edit.
SKIP_DIRS = frozenset({".venv", "venv", "node_modules", ".git", ".tox", "build", "dist"})


def build_pattern(package: str) -> re.Pattern[str]:
    """Match `"<package>[extras]<op><version>"` inside a TOML string.

    The operator and any extras are captured so they survive the rewrite:
    `aion-sdk[knowledge]>=0.7.1` -> `aion-sdk[knowledge]>=0.8.0`.

    A bare `"aion-sdk"` deliberately does not match. It already resolves to the newest
    release, and pinning it here would be a policy change nobody asked for.

    Normalized per PEP 503: a dependency on `aion_sdk` and one on `aion-sdk` name the same
    package, and a consumer that spells it the other way should still be bumped.
    """
    # PEP 503 collapses any run of `-`, `_` and `.` to a single `-`, so each such run in the
    # name matches any such run in the file. Built by splitting rather than by substituting
    # into an escaped string, which would corrupt the character class it had just inserted.
    stem = "[-_.]+".join(re.escape(part) for part in re.split(r"[-_.]+", package) if part)
    return re.compile(r'("' + stem + r'(?:\[[^\]]*\])?)(===|==|>=|~=|>)([0-9][^"]*)(")')


def rewrite(root: pathlib.Path, package: str, version: str) -> list[pathlib.Path]:
    pattern = build_pattern(package)
    changed: list[pathlib.Path] = []
    for path in sorted(root.rglob("pyproject.toml")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        before = path.read_text()
        after, hits = pattern.subn(
            lambda m: f"{m.group(1)}{m.group(2)}{version}{m.group(4)}", before
        )
        if hits and after != before:
            path.write_text(after)
            changed.append(path)
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package")
    parser.add_argument("version")
    parser.add_argument("--root", default=".", type=pathlib.Path)
    args = parser.parse_args(argv)

    for path in rewrite(args.root, args.package, args.version):
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
