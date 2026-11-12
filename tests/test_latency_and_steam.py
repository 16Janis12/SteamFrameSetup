"""
Unit tests for LatencyManager and SteamManager in steamframe-setup.
"""

import os
import unittest
from pathlib import Path
import tempfile
import shutil

from tests.helper import sf, MockSystemExecutor


class TestLatencyAndSteam(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.root_path = Path(self.test_dir)
        self.executor = MockSystemExecutor(root=self.root_path)
        self.manifest_mgr = sf.ManifestManager(self.executor)
        self.latency = sf.LatencyManager(self.executor)
        self.steam = sf.SteamManager(self.executor)
        self.manifest_data = {}

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_latency_manager_nm_files(self):
        """Tests NM powersave conf and dispatcher script creation."""
        self.executor.set_response(("iw", "dev", "wlan1", "set", "power_save", "off"), returncode=0)
        self.executor.set_response(("wpa_cli", "-i", "wlan1", "ping"), returncode=1, stdout="Failed to connect")

        actions = self.latency.apply_latency_tweaks("wlan1", self.manifest_mgr, self.manifest_data)
        self.assertTrue(len(actions) > 0)

        # Check NM powersave conf
        nm_conf = self.executor.resolve_path(sf.NM_CONF_REL)
        self.assertTrue(nm_conf.exists())
        nm_text = nm_conf.read_text(encoding="utf-8")
        self.assertIn("match-device=interface-name:wlan1", nm_text)
        self.assertIn("wifi.powersave=2", nm_text)

        # Check NM dispatcher script
        dispatcher = self.executor.resolve_path(sf.NM_DISPATCHER_REL)
        self.assertTrue(dispatcher.exists())
        disp_text = dispatcher.read_text(encoding="utf-8")
        self.assertIn('TARGET_IFACE="wlan1"', disp_text)
        self.assertIn("iw dev", disp_text)
        self.assertIn("bgscan", disp_text)

        # Verify executable permissions
        mode = dispatcher.stat().st_mode
        self.assertTrue(bool(mode & 0o111), "Dispatcher script must be executable")

    def test_steam_manager_wrapper_and_desktop(self):
        """Tests user-level wrapper script and .desktop file creation."""
        # Mock native steam present
        native_steam = self.executor.resolve_path("usr/bin/steam")
        native_steam.parent.mkdir(parents=True, exist_ok=True)
        native_steam.touch()

        actions = self.steam.apply_steam_wrapper(self.manifest_mgr, self.manifest_data)
        self.assertTrue(len(actions) >= 2)

        _, user_home, _, _ = sf.get_target_user(self.executor)
        wrapper_path = user_home / ".local" / "bin" / "steam-frame"
        desktop_path = user_home / ".local" / "share" / "applications" / "steam-frame.desktop"

        self.assertTrue(wrapper_path.exists())
        self.assertTrue(desktop_path.exists())

        # Check wrapper content
        wrapper_text = wrapper_path.read_text(encoding="utf-8")
        self.assertIn("steam -pipewire -vrlinkforceenable", wrapper_text)
        self.assertIn('PIPEWIRE_LATENCY="512/48000"', wrapper_text)
        self.assertIn('QT_QPA_PLATFORM="xcb"', wrapper_text)
        self.assertTrue(bool(wrapper_path.stat().st_mode & 0o111), "Wrapper must be executable")

        # Check desktop file content
        desktop_text = desktop_path.read_text(encoding="utf-8")
        self.assertIn("Name=Steam (Frame / VRLink)", desktop_text)
        self.assertIn("steam-frame", desktop_text)

    def test_reset_steam(self):
        """Tests reset_steam terminates lingering processes."""
        engine = sf.SetupEngine(self.executor)
        # Mock pgrep finding vrserver
        self.executor.set_response(("pgrep", "-x", "vrserver"), returncode=0)
        self.executor.set_response(("pgrep", "-x", "steam"), returncode=1)
        self.executor.set_response(("pgrep", "-x", "steamvr"), returncode=1)
        self.executor.set_response(("pgrep", "-x", "vrcompositor"), returncode=1)
        self.executor.set_response(("pgrep", "-x", "vrmonitor"), returncode=1)
        self.executor.set_response(("pgrep", "-x", "vrwebhelper"), returncode=1)

        ret = engine.reset_steam()
        self.assertEqual(ret, 0)
        # Verify pkill was invoked for vrserver
        self.assertIn(["pkill", "-9", "-x", "vrserver"], self.executor.executed_commands)


if __name__ == "__main__":
    unittest.main()
