import unittest
import urllib.error
from unittest.mock import patch

from sync_upstream import TARGET, sync


class SyncTests(unittest.TestCase):
  def run_sync(self, responses, dry_run=False):
    with patch("sync_upstream.api", side_effect=responses) as api:
      result = sync("dev", dry_run=dry_run)
    return result, api

  def test_create_missing_branch(self):
    missing = urllib.error.HTTPError("url", 404, "missing", {}, None)
    _, api = self.run_sync([{"object": {"sha": "new"}}, missing, {}])
    api.assert_called_with(f"{TARGET}/git/refs", "POST", {"ref": "refs/heads/dev", "sha": "new"})

  def test_unchanged_does_not_write(self):
    result, api = self.run_sync([{"object": {"sha": "same"}}] * 2)
    self.assertIn("already synchronized", result)
    self.assertEqual(api.call_count, 2)

  def test_fast_forward_never_forces(self):
    _, api = self.run_sync([{"object": {"sha": "new"}}, {"object": {"sha": "old"}}, {"status": "ahead"}, {}])
    api.assert_called_with(f"{TARGET}/git/refs/heads/dev", "PATCH", {"sha": "new", "force": False})

  def test_divergence_and_backwards_upstream_do_not_write(self):
    for status in ("diverged", "behind"):
      for dry_run in (False, True):
        with self.subTest(status=status, dry_run=dry_run):
          with patch("sync_upstream.api", side_effect=[{"object": {"sha": "new"}}, {"object": {"sha": "old"}}, {"status": status}]) as api:
            with self.assertRaises(RuntimeError):
              sync("dev", dry_run=dry_run)
            self.assertEqual(api.call_count, 3)

  def test_dry_run_does_not_write(self):
    result, api = self.run_sync([{"object": {"sha": "new"}}, {"object": {"sha": "old"}}, {"status": "ahead"}], dry_run=True)
    self.assertIn("would fast-forward", result)
    self.assertEqual(api.call_count, 3)

  def test_target_api_error_is_not_treated_as_missing(self):
    for status in (403, 429, 500):
      with self.subTest(status=status):
        with patch("sync_upstream.api", side_effect=[{"object": {"sha": "new"}}, urllib.error.HTTPError("url", status, "failed", {}, None)]) as api:
          with self.assertRaises(urllib.error.HTTPError):
            sync("dev")
          self.assertEqual(api.call_count, 2)

  def test_upstream_missing_does_not_touch_target(self):
    with patch("sync_upstream.api", side_effect=urllib.error.HTTPError("url", 404, "missing", {}, None)) as api:
      with self.assertRaises(urllib.error.HTTPError):
        sync("dev")
      self.assertEqual(api.call_count, 1)

  def test_concurrent_write_rejection_propagates(self):
    with self.assertRaises(urllib.error.HTTPError):
      self.run_sync([{"object": {"sha": "new"}}, {"object": {"sha": "old"}}, {"status": "ahead"}, urllib.error.HTTPError("url", 422, "not fast forward", {}, None)])

  def test_disallowed_branch_does_not_call_api(self):
    with patch("sync_upstream.api") as api:
      with self.assertRaises(ValueError):
        sync("master")
      api.assert_not_called()


if __name__ == "__main__":
  unittest.main()
