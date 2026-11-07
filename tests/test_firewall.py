"""
Unit tests for FirewallManager in steamframe-setup.
Tests UFW detection, rule addition with scope (iface/all), comment tagging, and undo.
"""

import unittest
from pathlib import Path
import tempfile
import shutil

from tests.helper import sf, MockSystemExecutor


class TestFirewallManager(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.root_path = Path(self.test_dir)
        self.executor = MockSystemExecutor(root=self.root_path)
        self.manifest_mgr = sf.ManifestManager(self.executor)
        self.firewall = sf.FirewallManager(self.executor)
        self.manifest_data = {}

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_detect_ufw_active(self):
        self.executor.set_response(("ufw", "status"), returncode=0, stdout="Status: active\n")
        self.assertEqual(self.firewall.detect_active_firewall(), "ufw")

    def test_detect_firewalld(self):
        self.executor.set_response(("ufw", "status"), returncode=1, stdout="Status: inactive\n")
        self.executor.set_response(("systemctl", "is-active", "ufw"), returncode=1, stdout="inactive\n")
        self.executor.set_response(("firewall-cmd", "--state"), returncode=0, stdout="running\n")
        self.assertEqual(self.firewall.detect_active_firewall(), "firewalld")

    def test_detect_no_firewall(self):
        self.executor.set_response(("ufw", "status"), returncode=1, stdout="Status: inactive\n")
        self.executor.set_response(("firewall-cmd", "--state"), returncode=1, stdout="not running\n")
        self.executor.set_response(("systemctl", "is-active", "ufw"), returncode=1, stdout="inactive\n")
        self.executor.set_response(("systemctl", "is-active", "nftables"), returncode=1, stdout="inactive\n")
        self.assertEqual(self.firewall.detect_active_firewall(), "none")

    def test_no_changes_when_ufw_inactive(self):
        """When UFW is inactive, no rules should be added."""
        self.executor.set_response(("ufw", "status"), returncode=1, stdout="Status: inactive\n")
        self.executor.set_response(("systemctl", "is-active", "ufw"), returncode=1, stdout="inactive\n")
        self.executor.set_response(("firewall-cmd", "--state"), returncode=1, stdout="not running\n")

        actions = self.firewall.apply_rules("iface", "wlan1", self.manifest_mgr, self.manifest_data)
        self.assertEqual(len(actions), 0)
        self.assertEqual(len(self.manifest_data.get("ufw_rules", [])), 0)

    def test_apply_rules_iface_scope(self):
        """Test rule addition with scope 'iface' and comments."""
        self.executor.set_response(("ufw", "status"), returncode=0, stdout="Status: active\n")
        self.executor.set_response(("ufw", "status", "verbose"), returncode=0, stdout="Status: active\nLogging: on\n")

        actions = self.firewall.apply_rules("iface", "wlan1", self.manifest_mgr, self.manifest_data)

        # There are 6 VRLINK_PORTS
        self.assertEqual(len(actions), 6)
        recorded_rules = self.manifest_data.get("ufw_rules", [])
        self.assertEqual(len(recorded_rules), 6)

        # Verify command arguments for first port 27031/udp
        rule_cmds = [cmd for cmd in self.executor.executed_commands if cmd[0] == "ufw" and cmd[1] == "allow"]
        self.assertEqual(len(rule_cmds), 6)
        self.assertIn("in", rule_cmds[0])
        self.assertIn("wlan1", rule_cmds[0])
        self.assertIn("comment", rule_cmds[0])
        self.assertIn("steamframe-setup", rule_cmds[0])

    def test_apply_rules_all_scope(self):
        """Test rule addition with scope 'all'."""
        self.executor.set_response(("ufw", "status"), returncode=0, stdout="Status: active\n")
        self.executor.set_response(("ufw", "status", "verbose"), returncode=0, stdout="Status: active\n")

        actions = self.firewall.apply_rules("all", None, self.manifest_mgr, self.manifest_data)
        self.assertEqual(len(actions), 6)
        rule_cmds = [cmd for cmd in self.executor.executed_commands if cmd[0] == "ufw" and cmd[1] == "allow"]
        self.assertEqual(len(rule_cmds), 6)
        # Verify scope 'all' command format: ufw allow 27031/udp comment steamframe-setup
        self.assertEqual(rule_cmds[0], ["ufw", "allow", "27031/udp", "comment", "steamframe-setup"])

    def test_idempotent_ufw_rules(self):
        """If a port is already open, do not re-add it."""
        self.executor.set_response(("ufw", "status"), returncode=0, stdout="Status: active\n")
        mock_status = (
            "Status: active\n"
            "To                         Action      From\n"
            "--                         ------      ----\n"
            "27031/udp on wlan1         ALLOW IN    Anywhere\n"
        )
        self.executor.set_response(("ufw", "status", "verbose"), returncode=0, stdout=mock_status)

        actions = self.firewall.apply_rules("iface", "wlan1", self.manifest_mgr, self.manifest_data)
        # 1 already present, so only 5 applied
        self.assertEqual(len(actions), 5)

    def test_revert_ufw_rules(self):
        """Test exact undo of recorded UFW rules."""
        self.executor.set_response(("ufw", "status"), returncode=0, stdout="Status: active\n")
        self.manifest_data["ufw_rules"] = [
            {
                "port": 27031,
                "proto": "udp",
                "scope": "iface",
                "iface": "wlan1",
                "delete_cmd": ["ufw", "delete", "allow", "in", "on", "wlan1", "to", "any", "port", "27031", "proto", "udp"],
            }
        ]

        reverted = self.firewall.revert_rules(self.manifest_data)
        self.assertEqual(len(reverted), 1)
        self.assertIn("27031/udp", reverted[0])

        # Verify execution of delete command and reload
        del_cmds = [cmd for cmd in self.executor.executed_commands if cmd[0] == "ufw" and cmd[1] == "delete"]
        self.assertEqual(len(del_cmds), 1)
        reload_cmds = [cmd for cmd in self.executor.executed_commands if cmd == ["ufw", "reload"]]
        self.assertEqual(len(reload_cmds), 1)


if __name__ == "__main__":
    unittest.main()
