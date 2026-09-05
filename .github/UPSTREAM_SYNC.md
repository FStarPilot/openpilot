# Upstream branch synchronization

This workflow preserves the upstream code and safety features. It does not apply
custom commits. The driver-monitoring removal commit requested alongside this
workflow is intentionally not included.

Merge the workflow and script into `master` to enable the schedule. The workflow
checks `dev-chestnut`, `dev`, `staging-chestnut`, and `staging` every six hours at
00:17, 06:17, 12:17, and 18:17 UTC (08:17, 14:17, 20:17, and 02:17 in Taiwan).
GitHub can delay scheduled runs during high load.

Missing branches are created from the upstream SHA. Existing branches are
fast-forwarded only; divergent histories, upstream force pushes, missing upstream
branches, and API failures fail the corresponding job. No branch is force-pushed.
One failure does not cancel the other branch jobs. The workflow never changes
`master`, so branch synchronization does not remove its scheduling entry point.

Use **Actions > Sync sunnypilot upstream > Run workflow** on `master` to check
manually. Dry run is enabled by default; uncheck it to update branches.

The workflow uses `GITHUB_TOKEN` with `contents: write` by default. If GitHub
rejects updates involving `.github/workflows`, add a repository Actions secret
named `SYNC_TOKEN`: a fine-grained token scoped only to this repository with
**Contents: read/write** and **Workflows: read/write**. Branch rules can also
prevent updates. Never put the token in a file or workflow source. A custom token
may trigger workflows present on the synchronized branches; review those workflows
before enabling that token.

Failures appear in Actions with the branch name and API error. To receive native
failure notifications, enable Actions email/web notifications and **failed
workflows only** in your GitHub notification settings. Scheduled-run notifications
go to the user who last changed the cron expression; manual-run notifications go
to the triggering user. The workflow cannot override personal notification settings.

GitHub can disable scheduled workflows in public repositories after 60 days of
repository inactivity. Check the Actions page and re-enable the workflow if needed.

References:
- https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule
- https://docs.github.com/en/actions/concepts/workflows-and-actions/notifications-for-workflow-runs
- https://docs.github.com/en/rest/git/refs

Local verification: `python3 -m unittest discover -s .github/scripts -p 'test_*.py'`.
