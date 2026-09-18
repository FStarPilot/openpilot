"""Rebuild development branches with nodm, no comma uploader, and workflow cleanup."""

import base64
import os
from pathlib import Path
import subprocess
import tempfile

UPSTREAM = "https://github.com/sunnypilot/sunnypilot.git"
TARGET = "https://github.com/FStarPilot/openpilot.git"
PATCH_REPO = "https://github.com/chiachunli08/openpilot.git"
PATCH_COMMIT = "f08c7d88f847ec0878ed6ec524663784258ed32f"
BRANCHES = {"dev-chestnut", "dev", "staging-chestnut", "staging"}
UPLOADER_PROCESS_CONFIG = "openpilot/system/manager/process_config.py"
COMMA_UPLOADER_ENABLED = '  PythonProcess("uploader", "openpilot.system.loggerd.uploader", uploader_ready),'
COMMA_UPLOADER_DISABLED = '  PythonProcess("uploader", "openpilot.system.loggerd.uploader", uploader_ready, enabled=False),'
# Explicitly reviewed unused files. New upstream workflow paths are preserved.
UNUSED_AUTOMATION_FILES = (
  ".github/labeler.yaml",
  ".github/release-drafter.yml",
  ".github/workflows/auto_pr_review.yaml",
  ".github/workflows/build-all-tinygrad-models.yaml",
  ".github/workflows/build-default-models.yaml",
  ".github/workflows/build-single-tinygrad-model.yaml",
  ".github/workflows/cereal_validation.yaml",
  ".github/workflows/diff_report.yaml",
  ".github/workflows/docs.yaml",
  ".github/workflows/download-hf-model-chunks/action.yml",
  ".github/workflows/jenkins-pr-trigger.yaml",
  ".github/workflows/lfs-maintenance.yaml",
  ".github/workflows/post-to-discourse/action.yml",
  ".github/workflows/release-drafter.yml",
  ".github/workflows/release.yaml",
  ".github/workflows/repo-maintenance.yaml",
  ".github/workflows/stale.yaml",
  ".github/workflows/sunnypilot-build-model.yaml",
  ".github/workflows/sunnypilot-build-prebuilt.yaml",
  ".github/workflows/sunnypilot-master-dev-prep.yaml",
  ".github/workflows/test-discourse.yaml.yml",
  ".github/workflows/tests.yaml",
  ".github/workflows/ui_preview.yaml",
  ".github/workflows/wait-for-action/action.yaml",
)


def git(*args, cwd=None, env=None, stdin_text=None, check=True):
  result = subprocess.run(["git", *args], cwd=cwd, env=env, input=stdin_text, text=True,
                          stdout=subprocess.PIPE, check=False)
  if check and result.returncode:
    print(result.stdout, flush=True)
    result.check_returncode()
  return result


def remote_head(repo, branch, env):
  result = git("ls-remote", "--exit-code", "--heads", repo, f"refs/heads/{branch}", env=env, check=False)
  if result.returncode == 2:
    return None
  result.check_returncode()
  return result.stdout.split()[0]


def disable_comma_uploader(directory):
  path = Path(directory) / UPLOADER_PROCESS_CONFIG
  contents = path.read_text()
  enabled_count = contents.count(COMMA_UPLOADER_ENABLED)
  disabled_count = contents.count(COMMA_UPLOADER_DISABLED)
  if enabled_count == 0 and disabled_count == 1:
    return False
  if enabled_count != 1 or disabled_count != 0:
    raise RuntimeError(f"Unable to find the expected comma uploader process in {UPLOADER_PROCESS_CONFIG}")
  path.write_text(contents.replace(COMMA_UPLOADER_ENABLED, COMMA_UPLOADER_DISABLED))
  return True


def sync(branch, dry_run=False, *, upstream=UPSTREAM, target=TARGET,
         patch_repo=PATCH_REPO, patch_commit=PATCH_COMMIT):
  if branch not in BRANCHES:
    raise ValueError(f"Unsupported synchronization branch: {branch}")
  env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_LFS_SKIP_SMUDGE": "1"}
  if token := env.get("GH_TOKEN"):
    auth = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    env.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="http.https://github.com/.extraheader",
               GIT_CONFIG_VALUE_0=f"AUTHORIZATION: basic {auth}")
  upstream_sha = remote_head(upstream, branch, env)
  if upstream_sha is None:
    raise RuntimeError(f"Missing upstream branch: {branch}")
  previous_sha = remote_head(target, branch, env)
  print(f"{branch}: upstream={upstream_sha}; target={previous_sha or 'missing'}", flush=True)

  with tempfile.TemporaryDirectory(prefix="sunnypilot-sync-") as directory:
    def run(*args, **kwargs):
      return git(*args, cwd=directory, env=env, **kwargs)

    run("init", "--quiet")
    run("config", "user.name", "github-actions[bot]")
    run("config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    run("config", "core.hooksPath", "/dev/null")
    run("config", "commit.gpgSign", "false")
    run("config", "rerere.enabled", "false")
    run("remote", "add", "origin", target)
    run("remote", "add", "upstream", upstream)
    run("remote", "add", "patch", patch_repo)
    # Keep complete commit ancestry for pushes; partial clones omit unneeded file blobs/LFS.
    run("fetch", "--quiet", "--no-tags", "--filter=blob:none", "patch", patch_commit)
    paths = run("diff-tree", "--no-commit-id", "--name-only", "-r", patch_commit).stdout
    if not paths.strip():
      raise RuntimeError("The pinned patch has no changed files")
    # Load the patch's old/new blobs from its own repository before the merge.
    # This avoids probing upstream for fork-only blobs during lazy fetching.
    changes = run("diff-tree", "--no-commit-id", "--raw", "-r", patch_commit).stdout
    blobs = {sha for change in changes.splitlines() for sha in change.split()[2:4] if set(sha) != {"0"}}
    run("cat-file", "--batch", stdin_text="\n".join(sorted(blobs)) + "\n")
    run("fetch", "--quiet", "--no-tags", "--filter=blob:none", "upstream", upstream_sha)
    sparse_paths = set(paths.splitlines()) | {UPLOADER_PROCESS_CONFIG}
    run("sparse-checkout", "set", "--no-cone", "--stdin", stdin_text="\n".join(sorted(sparse_paths)) + "\n")
    run("checkout", "--quiet", "--detach", upstream_sha)
    # Identical upstream + patch yields an identical commit on every run.
    env["GIT_COMMITTER_DATE"] = run("show", "-s", "--format=%cI", upstream_sha).stdout.strip()
    picked = run("cherry-pick", "--empty=drop", "-x", patch_commit, check=False)
    if picked.returncode:
      conflicts = run("diff", "--name-only", "--diff-filter=U").stdout.strip()
      run("cherry-pick", "--abort", check=False)
      raise RuntimeError(f"{branch}: cherry-pick failed; remote unchanged. Conflicts: {conflicts or picked.stdout.strip()}")
    if disable_comma_uploader(directory):
      run("add", "--", UPLOADER_PROCESS_CONFIG)
      env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"]
      run("commit", "--quiet", "-m", "system: disable comma uploader")
    # Remove only the reviewed files, without recursively deleting directories.
    run("rm", "--quiet", "--sparse", "--ignore-unmatch", "--", *UNUSED_AUTOMATION_FILES)
    staged = run("diff", "--cached", "--quiet", check=False)
    if staged.returncode == 1:
      env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"]
      run("commit", "--quiet", "-m", "ci: remove reviewed unused automation from managed branch")
    else:
      staged.check_returncode()
    new_sha = run("rev-parse", "HEAD").stdout.strip()
    if new_sha == previous_sha:
      return f"{branch}: already synchronized at {new_sha}"
    if dry_run:
      return f"{branch}: cherry-pick succeeded; comma uploader disabled; workflow cleanup complete; would update to {new_sha} (upstream {upstream_sha})"
    # These four branches are managed mirrors. Rebuilding replaces the previous patch commit.
    # An explicit lease also protects first creation if another actor creates the branch meanwhile.
    run("push", "--porcelain", f"--force-with-lease=refs/heads/{branch}:{previous_sha or ''}",
        "origin", f"HEAD:refs/heads/{branch}")
    return f"{branch}: synchronized to {new_sha} (upstream {upstream_sha}, patch {patch_commit}, comma uploader disabled)"


if __name__ == "__main__":
  result = sync(os.environ["SYNC_BRANCH"], os.environ.get("SYNC_DRY_RUN") == "true")
  print(result)
  if summary_path := os.environ.get("GITHUB_STEP_SUMMARY"):
    with Path(summary_path).open("a") as summary:
      summary.write(f"- {result}\n")
