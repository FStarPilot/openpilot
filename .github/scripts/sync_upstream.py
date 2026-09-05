"""Synchronize unmodified upstream branches in the sunnypilot fork network."""

import json
import os
import urllib.error
import urllib.request

UPSTREAM = "sunnypilot/sunnypilot"
TARGET = "FStarPilot/sunnypilot"
BRANCHES = {"dev-chestnut", "dev", "staging-chestnut", "staging"}


def api(path, method="GET", data=None):
  request = urllib.request.Request(
    f"https://api.github.com/repos/{path}",
    data=None if data is None else json.dumps(data).encode(),
    headers={
      "Authorization": f"Bearer {os.environ['GH_TOKEN']}",
      "Accept": "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "Content-Type": "application/json",
    },
    method=method,
  )
  with urllib.request.urlopen(request, timeout=60) as response:
    return json.load(response)


def sync(branch, dry_run=False):
  if branch not in BRANCHES:
    raise ValueError(f"Unsupported synchronization branch: {branch}")
  upstream_sha = api(f"{UPSTREAM}/git/ref/heads/{branch}")["object"]["sha"]
  try:
    current_sha = api(f"{TARGET}/git/ref/heads/{branch}")["object"]["sha"]
  except urllib.error.HTTPError as error:
    if error.code != 404:
      raise
    current_sha = None

  if current_sha == upstream_sha:
    return f"{branch}: already synchronized at {upstream_sha}"
  if current_sha is not None:
    # Detect rewritten upstream history before attempting any update, including dry runs.
    comparison = api(f"{TARGET}/compare/{current_sha}...{upstream_sha}")
    if comparison["status"] != "ahead":
      raise RuntimeError(f"{branch}: histories diverged or upstream moved backwards; branch left unchanged")
  if dry_run:
    return f"{branch}: would {'create' if current_sha is None else 'fast-forward'} to {upstream_sha}"

  if current_sha is None:
    # Forks share Git objects, so the upstream SHA can be used directly.
    api(f"{TARGET}/git/refs", "POST", {"ref": f"refs/heads/{branch}", "sha": upstream_sha})
  else:
    # The server rechecks fast-forward safety if the branch changed after the read.
    api(f"{TARGET}/git/refs/heads/{branch}", "PATCH", {"sha": upstream_sha, "force": False})
  return f"{branch}: synchronized to {upstream_sha}"


if __name__ == "__main__":
  try:
    result = sync(os.environ["SYNC_BRANCH"], os.environ.get("SYNC_DRY_RUN") == "true")
  except urllib.error.HTTPError as error:
    print(f"GitHub API HTTP {error.code}: {error.read().decode()}", flush=True)
    raise
  print(result)
  if summary_path := os.environ.get("GITHUB_STEP_SUMMARY"):
    with open(summary_path, "a") as summary:
      summary.write(f"- {result}\n")
