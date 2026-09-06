# Development branch synchronization

`master` hosts the controller workflow. Every six hours it checks upstream
`dev-chestnut`, `dev`, `staging-chestnut`, and `staging`, then rebuilds each matching
fork branch from its upstream tip plus this pinned commit, followed by removal
of the reviewed unused automation files:

https://github.com/chiachunli08/openpilot/commit/f08c7d88f847ec0878ed6ec524663784258ed32f

The patch is for the owner's development machine and disables driver monitoring.
The workflow applies it exactly with `git cherry-pick -x`; it does not attempt
automatic conflict resolution. If upstream already contains the changes, Git
drops the empty cherry-pick. Successful text application is not a driving validation.

The schedule runs at 00:17, 06:17, 12:17, and 18:17 UTC (08:17, 14:17, 20:17, and
02:17 in Taiwan). GitHub can delay scheduled runs during high load.

The four destination branches are automation-managed. Each successful run replaces
the previous upstream-plus-patch history, including after upstream history rewrites.
Keep additional manual work on other branches. Updates use an explicit
`--force-with-lease` against the SHA read at the start, so concurrent changes fail
instead of being overwritten. Missing destination branches are created only after
the cherry-pick succeeds. A conflict leaves an existing branch unchanged (or a
missing branch uncreated), lists conflicting files, and fails its Actions job.
Other branches continue independently. `master` is never synchronized or patched.

Only `.github/workflows/sync-upstream.yml` remains on `master`. The 19 reviewed
unused upstream workflows, their three composite actions, `.github/labeler.yaml`,
and `.github/release-drafter.yml` have been deleted. Their previously registered
workflows remain disabled in this fork's Actions settings.

After cherry-picking, each managed branch removes only the exact 24 paths listed
in `UNUSED_AUTOMATION_FILES` in `.github/scripts/sync_upstream.py`, with a separate
deterministic cleanup commit. This prevents those files from returning on the
next synchronization. New upstream workflow paths are preserved pending review.
Issue templates and application code are preserved. No cleanup commit is added
when none of the listed files exist. Both the patch and cleanup must succeed
before the branch is pushed.

Commit generation is deterministic: repeating the same upstream and pinned patch
does not add commits or push updates. Submodules and LFS assets are not downloaded;
only files touched by the patch are checked out.

Use **Actions > Sync sunnypilot upstream with development patch > Run workflow**
on `master` for a manual run. Dry run defaults to enabled and tests the actual
cherry-pick without pushing. Uncheck it to synchronize branches.

The workflow uses `GITHUB_TOKEN` with `contents: write` by default. If GitHub
rejects updates involving `.github/workflows`, a repository secret `SYNC_TOKEN`
can provide a token scoped to this repository with **Contents: read/write** and
**Workflows: read/write**. Branch rules can also prevent updates. A custom token
may trigger upstream workflows on branch pushes. Never store tokens in source.

Failures use native GitHub Actions notifications. Enable Actions email/web
notifications and **failed workflows only** in your GitHub notification settings.
Scheduled notifications go to the user who last changed the cron expression;
manual notifications go to the triggering user. The workflow cannot override
personal notification preferences. Public repositories can have scheduled
workflows disabled after 60 days of repository inactivity.

References:
- https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule
- https://docs.github.com/en/actions/concepts/workflows-and-actions/notifications-for-workflow-runs

Local verification: `python3 -m unittest discover -s .github/scripts -p 'test_*.py'`.
