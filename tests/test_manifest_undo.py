"""
Unit tests for ManifestManager and end-to-end Undo logic in steamframe-setup.
Verifies exact restoration, hash integrity, idempotency, and clean rollback.
"""

import argparse
import hashlib
import unittest
from pathlib import Path
import tempfile
import shutil

from tests.helper import sf, MockSystemExecutor


class TestManifestAndUndo(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.root_path = Path(self.test_dir)
        self.executor = MockSystemExecutor(root=self.root_path)
        self.engine = sf.SetupEngine(self.executor)

        # Mock standard command outputs
        self.executor.set_response(("uname", "-r"), returncode=0, stdout="7.3.1-1-cachyos\n")
        self.executor.set_response(("pacman", "-Q", "game-devices-udev"), returncode=0, stdout="game-devices-udev 0.22-1\n")
        self.executor.set_response(("pacman", "-Q", "wireless-regdb"), returncode=0, stdout="wireless-regdb 2026.09.03-1\n")
        self.executor.set_response(("iw", "reg", "get"), returncode=0, stdout="global\ncountry 00: DFS-UNSET\n")
        self.executor.set_response(("iw", "reg", "set", "DE"), returncode=0, stdout="")
        self.executor.set_response(("iw", "reg", "set", "00"), returncode=0, stdout="")
        self.executor.set_response(("ufw", "status"), returncode=0, stdout="Status: active\n")
        self.executor.set_response(("ufw", "status", "verbose"), returncode=0, stdout="Status: active\n")
        self.executor.set_response(("systemctl", "daemon-reload"), returncode=0, stdout="")
        self.executor.set_response(("systemctl", "enable", "steamframe-regdom.service"), returncode=0, stdout="")
        self.executor.set_response(("systemctl", "disable", "--now", "steamframe-regdom.service"), returncode=0, stdout="")
        self.executor.set_response(("nmcli", "general", "reload", "conf"), returncode=0, stdout="")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_full_apply_and_exact_undo(self):
        """Tests that apply modifies and creates files, and undo restores everything exactly."""
        # 1. Create a pre-existing /etc/conf.d/wireless-regdom with distinct content
        regdom_file = self.executor.resolve_path(sf.REGDOM_CONF_REL)
        regdom_file.parent.mkdir(parents=True, exist_ok=True)
        original_text = "# ORIGINAL ARCH CONFIG\n#WIRELESS_REGDOM=\"00\"\n# SOME COMMENT\n"
        regdom_file.write_text(original_text, encoding="utf-8")
        orig_hash = hashlib.sha256(original_text.encode("utf-8")).hexdigest()

        # Run apply
        args_apply = argparse.Namespace(
            command="apply",
            dry_run=False,
            iface="wlan1",
            country="DE",
            ufw_scope="iface",
            yes=True,
            root=str(self.root_path),
        )
        res_apply = self.engine.apply(args_apply)
        self.assertEqual(res_apply, 0)

        # Verify file was modified
        self.assertIn('WIRELESS_REGDOM="DE"', regdom_file.read_text(encoding="utf-8"))

        # Verify manifest exists and has recorded backup
        manifest = self.engine.manifest_mgr.load_manifest()
        self.assertTrue(bool(manifest))
        self.assertIn(str(regdom_file), manifest["modified_files"])
        self.assertEqual(manifest["modified_files"][str(regdom_file)]["sha256"], orig_hash)
        self.assertEqual(len(manifest["created_files"]), 6)

        # Run undo
        args_undo = argparse.Namespace(
            command="undo",
            dry_run=False,
            yes=True,
            remove_packages=False,
            root=str(self.root_path),
        )
        res_undo = self.engine.undo(args_undo)
        self.assertEqual(res_undo, 0)

        # Verify regdom_file is bit-for-bit identical to original
        restored_text = regdom_file.read_text(encoding="utf-8")
        self.assertEqual(restored_text, original_text)
        restored_hash = hashlib.sha256(restored_text.encode("utf-8")).hexdigest()
        self.assertEqual(restored_hash, orig_hash)

        # Verify all created files were deleted
        for created_path_str in manifest["created_files"]:
            self.assertFalse(Path(created_path_str).exists(), f"File {created_path_str} should have been deleted")

        # Verify manifest file and backup directory were deleted
        self.assertFalse(self.engine.manifest_mgr.manifest_path.exists())
        self.assertFalse(self.engine.manifest_mgr.backup_dir.exists())

    def test_idempotent_double_apply(self):
        """Running apply twice must preserve original backup and avoid duplicate rules."""
        regdom_file = self.executor.resolve_path(sf.REGDOM_CONF_REL)
        regdom_file.parent.mkdir(parents=True, exist_ok=True)
        original_text = "# INITIAL\n"
        regdom_file.write_text(original_text, encoding="utf-8")
        orig_hash = hashlib.sha256(original_text.encode("utf-8")).hexdigest()

        args = argparse.Namespace(
            command="apply",
            dry_run=False,
            iface="wlan1",
            country="DE",
            ufw_scope="iface",
            yes=True,
            root=str(self.root_path),
        )

        # First apply
        self.engine.apply(args)
        manifest1 = self.engine.manifest_mgr.load_manifest()

        # Second apply
        self.engine.apply(args)
        manifest2 = self.engine.manifest_mgr.load_manifest()

        # The backup hash should still be the initial hash!
        self.assertEqual(manifest2["modified_files"][str(regdom_file)]["sha256"], orig_hash)
        self.assertEqual(len(manifest2["created_files"]), len(manifest1["created_files"]))

    def test_idempotent_double_undo(self):
        """Running undo when nothing is applied exits cleanly with 0."""
        args_undo = argparse.Namespace(
            command="undo",
            dry_run=False,
            yes=True,
            remove_packages=False,
            root=str(self.root_path),
        )
        # No manifest present
        res = self.engine.undo(args_undo)
        self.assertEqual(res, 0)

    def test_undo_dry_run(self):
        """Dry-run undo should not delete files on disk."""
        args_apply = argparse.Namespace(
            command="apply",
            dry_run=False,
            iface="wlan1",
            country="DE",
            ufw_scope="all",
            yes=True,
            root=str(self.root_path),
        )
        self.engine.apply(args_apply)

        # Manifest exists
        self.assertTrue(self.engine.manifest_mgr.manifest_path.exists())

        # Dry-run undo
        engine_dry = sf.SetupEngine(MockSystemExecutor(root=self.root_path, dry_run=True))
        args_undo_dry = argparse.Namespace(
            command="undo",
            dry_run=True,
            yes=True,
            remove_packages=False,
            root=str(self.root_path),
        )
        res = engine_dry.undo(args_undo_dry)
        self.assertEqual(res, 0)

        # Files should still exist because dry_run was True
        self.assertTrue(self.engine.manifest_mgr.manifest_path.exists())


if __name__ == "__main__":
    unittest.main()
