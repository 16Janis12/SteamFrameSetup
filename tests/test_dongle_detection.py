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

    def _create_mock_usb_device(
        self,
        iface: str,
        driver_name: str,
        vid: str = "28de",
        pid: str = "2432",
        mac: str = "7a:dd:3b:9b:37:43",
        mfg: str = "Realtek",
        prod: str = "802.11ax WLAN Adapter",
    ):
        dev_dir = self.net_dir / iface
        dev_dir.mkdir(parents=True, exist_ok=True)

        usb_parent = self.root_path / "sys/devices/pci0000:00/usb2/2-3"
        usb_parent.mkdir(parents=True, exist_ok=True)
        (usb_parent / "idVendor").write_text(vid)
        (usb_parent / "idProduct").write_text(pid)
        (usb_parent / "manufacturer").write_text(mfg)
        (usb_parent / "product").write_text(prod)

        usb_intf = usb_parent / "2-3:1.0"
        usb_intf.mkdir(parents=True, exist_ok=True)

        driver_dir = self.root_path / f"sys/bus/usb/drivers/{driver_name}"
        driver_dir.mkdir(parents=True, exist_ok=True)
        (usb_intf / "driver").symlink_to(driver_dir)

        subsys_dir = self.root_path / "sys/bus/usb"
        subsys_dir.mkdir(parents=True, exist_ok=True)
        (usb_intf / "subsystem").symlink_to(subsys_dir)

        (dev_dir / "device").symlink_to(usb_intf)
        (dev_dir / "address").write_text(mac)

    def test_internal_wifi_never_selected_as_dongle(self):
        """Internal Wi-Fi card (e.g. MediaTek mt7921e, Intel iwlwifi) must NEVER be chosen."""
        self._create_mock_net_device("wlan0", "mt7921e", bus_type="pci")
        self._create_mock_net_device("eth0", "r8169", bus_type="pci")

        dongle = self.detector.find_dongle(interactive=False)
        self.assertIsNone(dongle, "Internal Wi-Fi mt7921e should NOT be identified as dongle")

    def test_valve_dongle_detected_when_named_wlan0(self):
        """When dongle probes first and gets wlan0, it is correctly identified via USB 28de:2432."""
        self._create_mock_usb_device("wlan0", "rtw89_8852cu", vid="28de", pid="2432")
        self._create_mock_net_device("wlan1", "mt7921e", bus_type="pci")

        dongle = self.detector.find_dongle(interactive=False)
        self.assertIsNotNone(dongle)
        self.assertEqual(dongle.iface, "wlan0")
        self.assertTrue(dongle.is_valve_dongle)
        self.assertEqual(dongle.vendor_id, "28de")
        self.assertEqual(dongle.product_id, "2432")
        self.assertEqual(dongle.bus, "usb")

    def test_valve_dongle_detected_when_swapped_to_wlan1(self):
        """When onboard Wi-Fi probes first (wlan0) and dongle gets wlan1, dongle is still identified."""
        self._create_mock_net_device("wlan0", "mt7921e", bus_type="pci")
        self._create_mock_usb_device("wlan1", "rtw89_8852cu", vid="28de", pid="2432")

        dongle = self.detector.find_dongle(interactive=False)
        self.assertIsNotNone(dongle)
        self.assertEqual(dongle.iface, "wlan1")
        self.assertTrue(dongle.is_valve_dongle)
        self.assertEqual(dongle.vendor_id, "28de")
        self.assertEqual(dongle.product_id, "2432")
        self.assertEqual(dongle.bus, "usb")

    def test_valve_dongle_priority_over_generic_rtw89(self):
        """Official Valve dongle (28de:2432) is prioritized over internal rtw89 PCIe cards."""
        self._create_mock_net_device("wlan0", "rtw89_8852ce", bus_type="pci")
        self._create_mock_usb_device("wlan1", "rtw89_8852cu", vid="28de", pid="2432")

        dongle = self.detector.find_dongle(interactive=False)
        self.assertIsNotNone(dongle)
        self.assertEqual(dongle.iface, "wlan1")
        self.assertTrue(dongle.is_valve_dongle)

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
