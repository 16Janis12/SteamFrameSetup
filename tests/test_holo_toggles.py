"""
Unit tests for HoloFirmwareManager in steamframe-setup.
Tests installation, polkit policy placement, low-latency execution, and undo.
"""

import unittest
from pathlib import Path
import tempfile
import shutil

from tests.helper import sf, MockSystemExecutor


class TestHoloFirmwareManager(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.root_path = Path(self.test_dir)
        self.executor = MockSystemExecutor(root=self.root_path)
        self.manifest_mgr = sf.ManifestManager(self.executor)
        self.holo = sf.HoloFirmwareManager(self.executor)
        self.manifest_data = {}

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_apply_installs_helper_and_polkit(self):
        """When package is not installed via pacman, helper and polkit policy are installed as files."""
        self.executor.set_response(("pacman", "-Q", "holo-realtek-firmware-toggles"), returncode=1, stdout="")

        actions = self.holo.apply(self.manifest_mgr, self.manifest_data)
        self.assertTrue(len(actions) >= 2)

        bin_path = self.executor.resolve_path(sf.HOLO_TOGGLE_BIN_REL)
        policy_path = self.executor.resolve_path(sf.HOLO_POLKIT_POLICY_REL)

        self.assertTrue(bin_path.exists())
        self.assertTrue(policy_path.exists())
        self.assertTrue(self.holo.is_installed())

        # Check binary has executable bit
        mode = bin_path.stat().st_mode
        self.assertTrue(bool(mode & 0o111), "Helper binary must be executable")

        # Check polkit action contains expected action id
        policy_text = policy_path.read_text(encoding="utf-8")
        self.assertIn("org.valve.policykit.holo.pkexec.run-holo-polkit-helpers-holo-realtek-firmware-toggles", policy_text)
        self.assertIn("<allow_active>yes</allow_active>", policy_text)

        # Check manifest tracking
        created_files = self.manifest_data.get("created_files", [])
        self.assertIn(str(bin_path), created_files)
        self.assertIn(str(policy_path), created_files)

    def test_revert_holo(self):
        """Revert should invoke reset command on helper binary."""
        bin_path = self.executor.resolve_path(sf.HOLO_TOGGLE_BIN_REL)
        bin_path.parent.mkdir(parents=True, exist_ok=True)
        bin_path.write_text("#!/bin/sh\nexit 0\n")
        bin_path.chmod(0o755)

        self.executor.set_response((str(bin_path), "reset"), returncode=0, stdout="")
        reverted = self.holo.revert(self.manifest_data)

        self.assertEqual(len(reverted), 1)
        self.assertIn("reset", reverted[0])


if __name__ == "__main__":
    unittest.main()
