"""
Unit tests for dongle detection logic in steamframe-setup.
Verifies that rtw89 devices are detected and internal Wi-Fi is protected.
"""

import unittest
from pathlib import Path
import tempfile
import shutil

from tests.helper import sf, MockSystemExecutor


class TestDongleDetection(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.root_path = Path(self.test_dir)
        self.executor = MockSystemExecutor(root=self.root_path)
        self.detector = sf.DongleDetector(self.executor)

        # Create sys/class/net directory
        self.net_dir = self.root_path / "sys/class/net"
        self.net_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_mock_net_device(self, iface: str, driver_name: str, bus_type: str = "pci", mac: str = "00:11:22:33:44:55"):
        dev_dir = self.net_dir / iface
        dev_dir.mkdir(parents=True, exist_ok=True)

        # Device driver symlink
        drivers_dir = self.root_path / f"sys/bus/{bus_type}/drivers/{driver_name}"
        drivers_dir.mkdir(parents=True, exist_ok=True)

        driver_link = dev_dir / "device" / "driver"
        driver_link.parent.mkdir(parents=True, exist_ok=True)
        # Point to driver
        driver_link.symlink_to(drivers_dir)

        # Subsystem symlink
        subsys_dir = self.root_path / f"sys/bus/{bus_type}"
        subsys_link = dev_dir / "device" / "subsystem"
        subsys_link.symlink_to(subsys_dir)

        # MAC address
        (dev_dir / "address").write_text(mac)

    def test_internal_wifi_never_selected_as_dongle(self):
        """Internal Wi-Fi card (e.g. MediaTek mt7921e, Intel iwlwifi) must NEVER be chosen."""
        self._create_mock_net_device("wlan0", "mt7921e", bus_type="pci")
        self._create_mock_net_device("eth0", "r8169", bus_type="pci")

        dongle = self.detector.find_dongle(interactive=False)
        self.assertIsNone(dongle, "Internal Wi-Fi mt7921e should NOT be identified as dongle")

    def test_rtw89_dongle_auto_detected(self):
        """rtw89 USB/PCI dongle is correctly identified."""
        self._create_mock_net_device("wlan0", "mt7921e", bus_type="pci")
        self._create_mock_net_device("wlan1", "rtw89_8852cu", bus_type="usb", mac="aa:bb:cc:dd:ee:ff")

        dongle = self.detector.find_dongle(interactive=False)
        self.assertIsNotNone(dongle)
        self.assertEqual(dongle.iface, "wlan1")
        self.assertEqual(dongle.driver, "rtw89_8852cu")
        self.assertEqual(dongle.bus, "usb")
        self.assertEqual(dongle.mac, "aa:bb:cc:dd:ee:ff")
        self.assertTrue(dongle.is_rtw89)

    def test_explicit_iface_override(self):
        """User can specify interface explicitly with --iface."""
        self._create_mock_net_device("wlan0", "mt7921e", bus_type="pci")
        self._create_mock_net_device("wlan1", "rtw89_8852cu", bus_type="usb")

        dongle = self.detector.find_dongle(requested_iface="wlan1", interactive=False)
        self.assertIsNotNone(dongle)
        self.assertEqual(dongle.iface, "wlan1")


if __name__ == "__main__":
    unittest.main()
