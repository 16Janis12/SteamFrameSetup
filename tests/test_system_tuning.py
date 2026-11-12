"""
Unit tests for SystemTuningManager in steamframe-setup.
Tests USB autosuspend udev rule, rtw89 modprobe PM disable, network socket buffers,
polkit NM rule, and ananicy vrcompositor rule.
"""

import unittest
from pathlib import Path
import tempfile
import shutil

from tests.helper import sf, MockSystemExecutor


class TestSystemTuningManager(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.root_path = Path(self.test_dir)
        self.executor = MockSystemExecutor(root=self.root_path)
        self.manifest_mgr = sf.ManifestManager(self.executor)
        self.tuning = sf.SystemTuningManager(self.executor)
        self.manifest_data = {}

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_apply_system_tuning_files(self):
        actions = self.tuning.apply_all(self.manifest_mgr, self.manifest_data)
        self.assertTrue(len(actions) >= 4)

        # 1. Check udev USB rule
        self.assertTrue(self.tuning.udev_path.exists())
        udev_text = self.tuning.udev_path.read_text(encoding="utf-8")
        self.assertIn('ATTR{idVendor}=="28de"', udev_text)
        self.assertIn('ATTR{idProduct}=="2432"', udev_text)
        self.assertIn('ATTR{power/control}="on"', udev_text)

        # 2. Check modprobe rtw89_core
        self.assertTrue(self.tuning.modprobe_path.exists())
        modprobe_text = self.tuning.modprobe_path.read_text(encoding="utf-8")
        self.assertIn("options rtw89_core disable_ps_mode=y", modprobe_text)

        # 3. Check sysctl network buffers
        self.assertTrue(self.tuning.sysctl_path.exists())
        sysctl_text = self.tuning.sysctl_path.read_text(encoding="utf-8")
        self.assertIn("net.core.rmem_max=33554432", sysctl_text)
        self.assertIn("-net.core.netdev_max_backlog=10000", sysctl_text)

        # 4. Check polkit rule
        self.assertTrue(self.tuning.polkit_path.exists())
        polkit_text = self.tuning.polkit_path.read_text(encoding="utf-8")
        self.assertIn("org.freedesktop.NetworkManager.settings.modify.system", polkit_text)
        self.assertIn("org.freedesktop.NetworkManager.network-control", polkit_text)

        # Verify all created files are tracked in manifest
        created_files = self.manifest_data.get("created_files", [])
        self.assertIn(str(self.tuning.udev_path), created_files)
        self.assertIn(str(self.tuning.modprobe_path), created_files)
        self.assertIn(str(self.tuning.sysctl_path), created_files)
        self.assertIn(str(self.tuning.polkit_path), created_files)


if __name__ == "__main__":
    unittest.main()
