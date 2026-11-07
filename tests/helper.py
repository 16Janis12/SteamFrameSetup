"""
Test helper and module loader for steamframe-setup unit tests.
"""

import sys
from pathlib import Path
import importlib.machinery
import importlib.util

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load steamframe-setup cleanly into sys.modules
script_path = PROJECT_ROOT / "steamframe-setup"
loader = importlib.machinery.SourceFileLoader("steamframe_setup", str(script_path))
spec = importlib.util.spec_from_loader(loader.name, loader)
sf = importlib.util.module_from_spec(spec)
sys.modules[loader.name] = sf
loader.exec_module(sf)


class MockSystemExecutor(sf.SystemExecutor):
    """Mocks command execution for deterministic testing without system side-effects."""

    def __init__(self, root: Path, dry_run: bool = False):
        super().__init__(dry_run=dry_run, root=root)
        self.executed_commands = []
        self.command_responses = {}

    def set_response(self, cmd_prefix: tuple, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self.command_responses[cmd_prefix] = (returncode, stdout, stderr)

    def run_cmd(
        self,
        cmd,
        check=False,
        capture_output=True,
        simulate_in_dry_run=False,
        dry_run_output="",
    ):
        self.executed_commands.append(list(cmd))

        # Check matched response (most specific / longest prefix first)
        for prefix in sorted(self.command_responses.keys(), key=lambda p: len(p), reverse=True):
            if tuple(cmd[: len(prefix)]) == prefix:
                rc, out, err = self.command_responses[prefix]
                return sf.CommandResult(returncode=rc, stdout=out, stderr=err, cmd=cmd)

        # Default fallback
        return sf.CommandResult(returncode=0, stdout="", stderr="", cmd=cmd)
