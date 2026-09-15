# Release system

## Contract

- `release/v1` is the only integration/release trunk and the intended GitHub default.
- `dev/*` branches are short-lived PR branches. Target `release/v1`.
- `vX.Y.Z` tags identify exact versions. Never move published tags.
- `gh-pages` is reserved for public documentation.
- GitHub `origin` is the release authority; GitLab is an optional mirror.

`VERSION` is the only manually edited version pin. Normal builds only read it.
Tagged clean builds use that version; other local builds append `-dev.<commit>`
and `.dirty` when appropriate. The installer selects the latest **published**
release; `go install @latest` instead follows Go module tags.

## Checks and builds

`make ci` runs release-script regressions, module verification, all Go tests, and
builds the binary. If `web/package.json` exists, both `make build` and `make ci`
first run `npm ci` and `npm run build`; an embedded server without its frontend
sources fails. Go-only revisions skip the frontend explicitly.

Commit rebuilt `internal/server/static` assets with web changes so Go module
source installs work too. CI rejects changed or untracked embedded assets after
rebuilding; the release validator also requires a clean checkout. Do not commit
`node_modules` or TypeScript incremental cache files.

CI runs on work-branch pushes, trunk pushes, and PRs. Protect `release/v1` with
an approving review, the required **Build and test** status, up-to-date branches,
and administrator enforcement. Formula PRs use the same checks and reviews.

## Release flow

1. Create a branch from the current trunk:

   ```bash
   git fetch origin
   git switch -c dev/release-next origin/release/v1
   scripts/release vX.Y.Z
   ```

2. Review and commit `VERSION`. Push explicitly to `origin`, then open a PR into
   `release/v1`. In the maintainer's CLOUDMANAGER checkout, run `gituse personal`
   before every push; preserve the GitLab remote.
3. Merge after review and a green **Build and test** check.
4. Run **Release Go Module** from `release/v1`, entering the merged version.
   Tests cannot be skipped. A direct tag push does not publish a release.
5. The workflow validates the commit/version and remote release state, runs CI,
   creates or resumes the tag, and invokes GoReleaser in the **same run**. There
   is no dependency on another workflow being triggered by `GITHUB_TOKEN`.
6. Verify the downloaded binary/version and installer. Merge the generated
   Homebrew formula PR. Delete the short-lived work branch.

The workflow serializes release attempts. New tags must use the current trunk
tip. Retries must use the same commit, still present in trunk history; use
**Re-run jobs** on the original workflow run when trunk has advanced. Older
stable versions are rejected. A failure never grants permission to move a tag.

## Recovery

- **No tag yet:** fix the failed validation/build and rerun.
- **Tag exists, no published release:** rerun only for the exact tagged commit.
- **Draft with partial assets:** inspect the draft; the automated validator stops
  for manual recovery rather than overwriting existing files.
- **Already published:** fix the problem in a new patch release. The validator
  rejects republishing; GoReleaser also disables artifact replacement.
- **Formula PR failed after publication:** repair the formula from the existing
  release checksums in a normal PR. Do not republish the release to fix Homebrew.

GoReleaser stays pinned at `v2.9.0` while using its existing `brews` publisher.
Modernizing that publisher is a separate migration; upgrading it blindly breaks
packaging. A dedicated tap is optional, not required for this release repair.
`mode: keep-existing` preserves notes; `replace_existing_artifacts: false`
protects assets. These are separate GoReleaser settings.

## Branch migration

Reconcile `release/v1.0.0` into `release/v1` through a PR before retiring the old
line; both contain useful changes. Set GitHub's default to `release/v1`, retarget
open dependency PRs, and require **Build and test** once that check is present.
The checked-in Dependabot configuration explicitly targets `release/v1`.
Keep the old release/prep branches until the repaired release is proven. Do not
remove or move the existing `v1.0.0` and `v1.0.2` tags.
