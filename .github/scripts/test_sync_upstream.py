import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from sync_upstream import git, remote_head, sync


class SyncTests(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self.tmp.cleanup)
    root = Path(self.tmp.name)
    self.upstream = root / 'upstream'
    self.patch_repo = root / 'patch'
    self.target = root / 'target.git'
    self.upstream.mkdir()
    self.run_git('init', '-q', '-b', 'dev', cwd=self.upstream)
    self.run_git('config', 'user.name', 'Sync Test', cwd=self.upstream)
    self.run_git('config', 'user.email', 'sync@example.invalid', cwd=self.upstream)
    self.run_git('config', 'commit.gpgSign', 'false', cwd=self.upstream)
    self.original = ''.join(f'line {i}\n' for i in range(40))
    (self.upstream / 'code.txt').write_text(self.original)
    self.commit(self.upstream, 'base')
    self.run_git('clone', '-q', '--no-hardlinks', str(self.upstream), str(self.patch_repo))
    self.run_git('config', 'user.name', 'Sync Test', cwd=self.patch_repo)
    self.run_git('config', 'user.email', 'sync@example.invalid', cwd=self.patch_repo)
    self.run_git('config', 'commit.gpgSign', 'false', cwd=self.patch_repo)
    (self.patch_repo / 'code.txt').write_text(self.original.replace('line 10\n', 'patched\n'))
    self.patch_sha = self.commit(self.patch_repo, 'development patch')
    self.run_git('init', '-q', '--bare', str(self.target))
    # GitHub forks share upstream objects, including future upstream commits.
    (self.target / 'objects/info/alternates').write_text(str(self.upstream / '.git/objects') + '\n')

  def run_git(self, *args, cwd=None):
    return git(*args, cwd=cwd).stdout.strip()

  def commit(self, repo, message):
    self.run_git('add', '.', cwd=repo)
    self.run_git('commit', '-q', '-m', message, cwd=repo)
    return self.run_git('rev-parse', 'HEAD', cwd=repo)

  def synchronize(self, dry_run=False):
    return sync('dev', dry_run=dry_run, upstream=str(self.upstream), target=str(self.target),
                patch_repo=str(self.patch_repo), patch_commit=self.patch_sha)

  def head(self):
    return remote_head(str(self.target), 'dev', os.environ)

  def test_create_and_repeat_are_deterministic(self):
    self.synchronize()
    first = self.head()
    self.assertIn('(cherry picked from commit ' + self.patch_sha + ')', self.run_git('show', '-s', '--format=%B', first, cwd=self.target))
    self.assertIn('already synchronized', self.synchronize())
    self.assertEqual(first, self.head())
    self.assertIn('patched', self.run_git('show', first + ':code.txt', cwd=self.target))

  def test_upstream_update_rebuilds_patch(self):
    self.synchronize()
    (self.upstream / 'other.txt').write_text('new upstream file\n')
    upstream_sha = self.commit(self.upstream, 'upstream update')
    self.synchronize()
    self.assertEqual(upstream_sha, self.run_git('rev-parse', self.head() + '^', cwd=self.target))
    self.assertEqual('new upstream file', self.run_git('show', self.head() + ':other.txt', cwd=self.target))

  def test_conflict_preserves_previous_branch(self):
    self.synchronize()
    previous = self.head()
    (self.upstream / 'code.txt').write_text(self.original.replace('line 10\n', 'upstream conflict\n'))
    self.commit(self.upstream, 'conflict')
    with self.assertRaisesRegex(RuntimeError, 'cherry-pick failed'):
      self.synchronize()
    self.assertEqual(previous, self.head())

  def test_conflict_does_not_create_missing_branch(self):
    (self.upstream / 'code.txt').write_text(self.original.replace('line 10\n', 'conflict\n'))
    self.commit(self.upstream, 'conflict')
    with self.assertRaisesRegex(RuntimeError, 'cherry-pick failed'):
      self.synchronize()
    self.assertIsNone(self.head())

  def test_patch_already_upstream_is_dropped(self):
    (self.upstream / 'code.txt').write_text(self.original.replace('line 10\n', 'patched\n'))
    upstream_sha = self.commit(self.upstream, 'upstream includes patch')
    self.synchronize()
    self.assertEqual(upstream_sha, self.head())

  def test_dry_run_tests_patch_without_writing(self):
    self.assertIn('cherry-pick succeeded', self.synchronize(dry_run=True))
    self.assertIsNone(self.head())

  def test_reviewed_cleanup_preserves_other_files_and_is_deterministic(self):
    removed = {'.github/workflows/tests.yaml', '.github/workflows/post-to-discourse/action.yml',
               '.github/labeler.yaml', '.github/release-drafter.yml'}
    retained = {'.github/ISSUE_TEMPLATE/bug.yml', '.github/workflows/custom.yml'}
    for name in sorted(removed | retained):
      path = self.upstream / name
      path.parent.mkdir(parents=True, exist_ok=True)
      path.write_text('name: upstream configuration\n')
    upstream_sha = self.commit(self.upstream, 'upstream automation')
    self.assertIn('workflow cleanup complete', self.synchronize(dry_run=True))
    self.assertIsNone(self.head())
    self.synchronize()
    first = self.head()
    files = set(self.run_git('ls-tree', '-r', '--name-only', first, cwd=self.target).splitlines())
    self.assertTrue(removed.isdisjoint(files))
    self.assertTrue(retained.issubset(files))
    self.assertIn('patched', self.run_git('show', first + ':code.txt', cwd=self.target))
    self.assertEqual(removed, set(self.run_git('diff-tree', '--no-commit-id', '--name-only', '-r', first, cwd=self.target).splitlines()))
    self.assertIn(self.patch_sha, self.run_git('show', '-s', '--format=%B', first + '^', cwd=self.target))
    self.assertEqual(upstream_sha, self.run_git('rev-parse', first + '^^', cwd=self.target))
    self.assertIn('already synchronized', self.synchronize())
    self.assertEqual(first, self.head())
    new_workflow = '.github/workflows/new.yaml'
    (self.upstream / new_workflow).write_text('name: new upstream job\n')
    self.commit(self.upstream, 'new upstream automation')
    self.synchronize()
    files = set(self.run_git('ls-tree', '-r', '--name-only', self.head(), cwd=self.target).splitlines())
    self.assertIn(new_workflow, files)
    self.assertTrue(removed.isdisjoint(files))

  def test_concurrent_branch_creation_rejected_by_lease(self):
    actual_git = git
    concurrent_sha = self.run_git('rev-parse', 'HEAD', cwd=self.upstream)

    def racing_git(*args, **kwargs):
      if args[0] == 'push':
        actual_git('update-ref', 'refs/heads/dev', concurrent_sha, cwd=self.target)
      return actual_git(*args, **kwargs)

    with patch('sync_upstream.git', side_effect=racing_git):
      with self.assertRaises(subprocess.CalledProcessError):
        self.synchronize()
    self.assertEqual(concurrent_sha, self.head())

  def test_missing_upstream_does_not_create_branch(self):
    self.run_git('branch', '-m', 'other', cwd=self.upstream)
    with self.assertRaisesRegex(RuntimeError, 'Missing upstream'):
      self.synchronize()
    self.assertIsNone(self.head())

  def test_master_is_rejected(self):
    with self.assertRaises(ValueError):
      sync('master')


if __name__ == '__main__':
  unittest.main()
