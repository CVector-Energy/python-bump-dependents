#!/usr/bin/env bash
# Relock every uv.lock under the tree against a new version of one package.
#
# Writes the directories it could not relock to stdout, one per line, and exits non-zero only
# when *every* project failed — one project must not cost the repository its whole PR, since
# CodeArtifact rejects individual artifacts inconsistently and losing 24 good locks to one 401
# is the wrong trade. Partial failures are reported so the caller can warn on the PR.
#
# Usage: relock.sh <package>
set -euo pipefail

PACKAGE="${1:?usage: relock.sh <package>}"

mapfile -t LOCKS < <(find . -name uv.lock -not -path '*/.venv/*' -not -path '*/node_modules/*' -exec dirname {} \; | sort)

if [ "${#LOCKS[@]}" -eq 0 ]; then
  echo "::notice::No uv.lock found; nothing to relock." >&2
  exit 0
fi

FAILED=()
# A monorepo keeps one lock per project, and a lock records the requirements of its path
# dependencies — so raising a shared lib's floor leaves every dependent lock stale no matter
# which order the first pass ran in. Two passes settle that without modelling the dependency
# order here.
for pass in 1 2; do
  FAILED=()
  for dir in "${LOCKS[@]}"; do
    echo "::group::pass ${pass}: uv lock ${dir}" >&2
    # Scoped to the one package so an unrelated release does not ride along in the diff.
    if ! (cd "$dir" && uv lock --upgrade-package "$PACKAGE" >&2); then
      echo "::warning::uv lock failed in ${dir}" >&2
      FAILED+=("$dir")
    fi
    echo "::endgroup::" >&2
  done
done

if [ "${#FAILED[@]}" -eq "${#LOCKS[@]}" ]; then
  echo "::error::uv lock failed in every project (${#LOCKS[@]}); not raising a PR." >&2
  exit 1
fi

printf '%s\n' "${FAILED[@]+"${FAILED[@]}"}"
