"""
Unit tests for RegdomManager in steamframe-setup.
Tests package check, 6-GHz detection, conf updating, fallbacks, and undo.
"""

import unittest
from pathlib import Path
import tempfile
import shutil

from tests.helper import sf, MockSystemExecutor


MOCK_IW_REG_GET_DE = """global
country DE: DFS-ETSI
\t(2400 - 2483 @ 40), (N/A, 20), (N/A)
\t(5150 - 5250 @ 80), (N/A, 23), (N/A), NO-OUTDOOR, AUTO-BW
\t(5250 - 5350 @ 80), (N/A, 20), (0 ms), NO-OUTDOOR, DFS, AUTO-BW
\t(5470 - 5725 @ 160), (N/A, 26), (0 ms), DFS
\t(5725 - 5875 @ 80), (N/A, 13), (N/A)
\t(5945 - 6425 @ 320), (N/A, 23), (N/A), NO-OUTDOOR
\t(57000 - 66000 @ 2160), (N/A, 40), (N/A)

phy#0 (self-managed)
country DE: DFS-ETSI
\t(5945 - 6425 @ 160), (6, 22), (N/A), AUTO-BW, NO-320MHZ, NO-EHT, PASSIVE-SCAN
"""

MOCK_IW_REG_GET_00 = """global
country 00: DFS-UNSET
\t(2402 - 2472 @ 40), (N/A, 20), (N/A)
\t(2457 - 2482 @ 20), (N/A, 20), (N/A), AUTO-BW, PASSIVE-SCAN
\t(5170 - 5250 @ 80), (N/A, 20), (N/A), AUTO-BW, PASSIVE-SCAN
\t(5250 - 5330 @ 80), (N/A, 20), (0 ms), DFS, AUTO-BW, PASSIVE-SCAN
\t(5490 - 5730 @ 160), (N/A, 20), (0 ms), DFS, AUTO-BW, PASSIVE-SCAN
\t(5735 - 5835 @ 80), (N/A, 20), (N/A), AUTO-BW, PASSIVE-SCAN
"""


class TestRegdomManager(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.root_path = Path(self.test_dir)
        self.executor = MockSystemExecutor(root=self.root_path)
        self.manifest_mgr = sf.ManifestManager(self.executor)
        self.regdom = sf.RegdomManager(self.executor)
        self.manifest_data = {}

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_parse_regdom_and_6ghz(self):
        country, output = "DE", MOCK_IW_REG_GET_DE
        self.assertTrue(self.regdom.check_6ghz_active(output))
        self.assertEqual(self.regdom.has_self_managed_phys(output), ["phy#0"])

        self.assertFalse(self.regdom.check_6ghz_active(MOCK_IW_REG_GET_00))
        self.assertEqual(len(self.regdom.has_self_managed_phys(MOCK_IW_REG_GET_00)), 0)

    def test_package_install_tracking(self):
        # When pacman -Q fails, simulate auto install
        self.executor.set_response(("pacman", "-Q", "wireless-regdb"), returncode=1, stdout="", stderr="error")
        self.executor.set_response(("pacman", "-S", "--needed", "--noconfirm", "wireless-regdb"), returncode=0, stdout="installed")

        installed = self.regdom.check_and_install_package(
            auto_yes=True,
            interactive=False,
            manifest_mgr=self.manifest_mgr,
            manifest_data=self.manifest_data,
        )
        self.assertTrue(installed)
        self.assertIn("wireless-regdb", self.manifest_data.get("installed_packages", []))

    def test_apply_and_revert_regdom(self):
        # Prepare existing conf file
        conf_path = self.executor.resolve_path(sf.REGDOM_CONF_REL)
        conf_path.parent.mkdir(parents=True, exist_ok=True)
        orig_content = "# Initial comment\n#WIRELESS_REGDOM=\"00\"\n"
        conf_path.write_text(orig_content, encoding="utf-8")

        self.executor.set_response(("iw", "reg", "get"), returncode=0, stdout=MOCK_IW_REG_GET_00)
        self.executor.set_response(("iw", "reg", "set", "DE"), returncode=0, stdout="")

        # Apply
        actions = self.regdom.apply_regdom("DE", self.manifest_mgr, self.manifest_data)
        self.assertTrue(any("WIRELESS_REGDOM=\"DE\"" in act for act in actions))

        # Check modified file
        updated_content = conf_path.read_text(encoding="utf-8")
        self.assertIn('WIRELESS_REGDOM="DE"', updated_content)

        # Check modprobe fallback created
        modprobe_path = self.executor.resolve_path(sf.MODPROBE_CONF_REL)
        self.assertTrue(modprobe_path.exists())
        self.assertIn("options cfg80211 ieee80211_regdom=DE", modprobe_path.read_text())

        # Check systemd unit created
        unit_path = self.executor.resolve_path(sf.SYSTEMD_UNIT_REL)
        self.assertTrue(unit_path.exists())
        self.assertIn("ExecStart=/usr/bin/iw reg set DE", unit_path.read_text())

        # Revert regdom
        self.executor.set_response(("iw", "reg", "set", "00"), returncode=0, stdout="")
        reverted = self.regdom.revert_regdom(self.manifest_data)
        self.assertTrue(any("00" in r for r in reverted))


if __name__ == "__main__":
    unittest.main()
