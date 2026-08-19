# python-bump-dependents

Publisher-side dependency fan-out. When you release a Python package, this raises (or
refreshes) an upgrade pull request in every repository in your org that depends on it — so a
release reaches its consumers without anyone opening five PRs by hand.

It is deliberately mechanical: it moves the version specifier and relocks. A release that
changes the API still needs a human to migrate the call sites. The PR is the starting point
for that work, not a substitute for it.

Consumers are **discovered**, not listed. Avoiding a hard-coded list of dependents in the
publisher's workflow is the whole point.

## Why not Dependabot, Renovate, or create-pull-request?

- **Dependabot** and **Renovate** are consumer-side pollers, and both currently struggle with
  `uv.lock` behind a private index — Dependabot doesn't match index URLs carrying userinfo
  (as AWS CodeArtifact's do), and Renovate can silently fall back to public PyPI when
  refreshing a `uv.lock`. They are also per-consumer configuration rather than a single
  publisher-side fan-out.
- **`peter-evans/create-pull-request`** resets the PR branch onto its base and force-pushes.
  This action does the opposite on purpose: it *appends* to the bump branch, so migration
  commits a human pushed onto the PR survive the next release. That difference is the reason
  the branch handling here is not delegated.

If none of that applies to you — a public package on PyPI, no hand-written migration commits
on the bump branch — reach for Dependabot first. It is less machinery.

## Usage

Two steps, because the fan-out is a job matrix and only the caller can declare one.

```yaml
name: Bump dependents

on:
  release:
    types: [released]
  workflow_dispatch:

permissions:
  contents: read

# Never cancel: two runs racing on the same branch would have the second push rejected as
# non-fast-forward, and a run cancelled mid-fan-out leaves the consumers it had not reached on
# the previous version. Queueing means each release appends its commit in order.
concurrency:
  group: bump-dependents
  cancel-in-progress: false

jobs:
  discover:
    runs-on: ubuntu-24.04
    outputs:
      version: ${{ steps.discover.outputs.version }}
      repositories: ${{ steps.discover.outputs.repositories }}
      has-dependents: ${{ steps.discover.outputs.has-dependents }}
    steps:
      - uses: CVector-Energy/python-bump-dependents@v1
        id: discover
        with:
          package: my-package
          app-id: ${{ vars.APP_ID }}
          app-private-key: ${{ secrets.APP_PRIVATE_KEY }}

  bump:
    needs: discover
    if: needs.discover.outputs.has-dependents == 'true'
    runs-on: ubuntu-24.04
    strategy:
      fail-fast: false      # one broken consumer must not stop the others getting their PR
      max-parallel: 4
      matrix:
        repository: ${{ fromJSON(needs.discover.outputs.repositories) }}
    steps:
      - uses: CVector-Energy/python-bump-dependents/bump@v1
        with:
          package: my-package
          repository: ${{ matrix.repository }}
          version: ${{ needs.discover.outputs.version }}
          app-id: ${{ vars.APP_ID }}
          app-private-key: ${{ secrets.APP_PRIVATE_KEY }}
          reviewer: ${{ github.event.release.author.login || github.actor }}
```

### With a private index

Publishing usually runs off the same release event, so discovery can start before the wheel
is on the index. `wait-command` is polled until it exits zero; it runs with `PACKAGE` and
`VERSION` in the environment. `pre-lock-command` runs just before `uv lock` and can export
credentials to `$GITHUB_ENV`.

Configure cloud credentials in the caller — a composite action cannot host another action's
steps mid-sequence.

```yaml
  discover:
    permissions:
      contents: read
      id-token: write
    steps:
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::000000000000:role/MyPackage-Bump
          aws-region: us-east-1
      - uses: CVector-Energy/python-bump-dependents@v1
        id: discover
        with:
          package: my-package
          app-id: ${{ vars.APP_ID }}
          app-private-key: ${{ secrets.APP_PRIVATE_KEY }}
          wait-command: |
            aws codeartifact describe-package-version \
              --domain my-domain --domain-owner 000000000000 \
              --repository internal --format pypi \
              --package "$PACKAGE" --package-version "$VERSION" >/dev/null 2>&1
```

```yaml
      - uses: CVector-Energy/python-bump-dependents/bump@v1
        with:
          # ...
          pre-lock-command: |
            TOKEN=$(aws codeartifact get-authorization-token \
              --domain my-domain --domain-owner 000000000000 \
              --region us-east-1 --query authorizationToken --output text)
            echo "::add-mask::${TOKEN}"
            echo "UV_INDEX_MY_INDEX_USERNAME=aws" >> "$GITHUB_ENV"
            echo "UV_INDEX_MY_INDEX_PASSWORD=${TOKEN}" >> "$GITHUB_ENV"
```

Give the bump role **read-only** index access, not publish. The relock resolves the
dependents' full dependency trees, and uv builds any sdist whose metadata it cannot read
statically — which runs third-party code in the same job that holds the registry token.

## Inputs

### `CVector-Energy/python-bump-dependents` (discover)

| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `package` | yes | | Package name as it appears in dependents' `pyproject.toml`. |
| `app-id` | yes | | Client ID of a GitHub App installed org-wide. |
| `app-private-key` | yes | | Private key of that app. |
| `owner` | no | calling repo's owner | Org to search. |
| `self` | no | calling repo | Repository name to exclude from results. |
| `version` | no | the release tag, `v` stripped | Version to roll out. |
| `repositories` | no | | Space-separated names to bump instead of searching. |
| `allow-empty` | no | `false` | Treat "no dependents" as a no-op instead of an error. |
| `wait-command` | no | | Shell snippet polled until the version is installable. |
| `wait-attempts` | no | `30` | Attempts before giving up. |
| `wait-interval` | no | `20` | Seconds between attempts. |

Outputs: `version`, `repositories` (JSON array for `fromJSON`), `count`, `has-dependents`,
`token`.

### `CVector-Energy/python-bump-dependents/bump`

| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `package` | yes | | Package name. |
| `repository` | yes | | Bare name of the dependent to bump. |
| `version` | yes | | Version to roll out, no leading `v`. |
| `app-id` | yes | | Client ID of a GitHub App installed on the dependent. |
| `app-private-key` | yes | | Private key of that app. |
| `owner` | no | calling repo's owner | Org that owns the dependent. |
| `branch` | no | `deps/<package>` | Branch to raise the PR from. |
| `committer-name` | no | `github-actions[bot]` | Commit author name. |
| `committer-email` | no | the bot's noreply | Commit author email. |
| `reviewer` | no | | Login to request review from; best-effort. |
| `labels` | no | | Comma-separated labels for the PR. |
| `pre-lock-command` | no | | Shell snippet run before `uv lock`. |
| `setup-uv` | no | `true` | Install uv. |

Outputs: `relevant`, `pushed`, `pull-request-number`.

## Behaviour worth knowing

**Discovery is a text search.** GitHub code search indexes default branches only, which is
exactly the set worth bumping, but it matches text — a `pyproject.toml` that names the package
in a comment can land in the matrix. The bump step then checks `uv.lock` for a resolved
`name = "<package>"` entry and skips the repository if it isn't there. That is the resolver's
own answer to whether the repository depends on the package, rather than the same text the
search matched.

**Zero dependents is an error by default.** A search that silently returns nothing — an app
that lost its org installation, an index that hasn't caught up — otherwise looks exactly like
a run that bumped everything. Set `allow-empty: true` for a package published before anything
consumes it.

**Unconstrained dependencies are left alone.** A bare `"my-package"` already resolves to the
newest release; pinning it would be a policy change nobody asked for. The relock still runs
for those repositories, so their lockfile moves even though the manifest doesn't.

**Names are matched per PEP 503.** A consumer depending on `my_package` is bumped by a
release of `my-package`.

**The bump branch does not follow its base.** A later release appends another commit rather
than rebasing, so unmerged work on the PR is kept. Rebase or merge it as you would any other
long-lived PR.

**Relock runs twice.** A monorepo keeps one lock per project, and a lock records the
requirements of its path dependencies, so raising a shared library's floor leaves dependent
locks stale regardless of the order the first pass ran in. Two passes settle that without
modelling the dependency graph.

**A partial relock failure still raises the PR**, with a warning listing the projects that
need relocking by hand. Every project failing stops the run instead.

## Development

```bash
uv run --group dev pytest
shellcheck scripts/*.sh
```

The logic that would be painful to debug from a failed fan-out lives in `scripts/` and is
tested directly: `rewrite_specifier.py` (which specifiers move and which don't) and
`relock.sh` (the failure policy, driven through a stub `uv`).

## License

MIT
