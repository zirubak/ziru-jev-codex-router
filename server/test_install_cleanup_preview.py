"""The rollback planner reuses the isolated cleaner without mutating live files."""
import json
import subprocess
import unittest

import test_install_transaction as fixture_module


class CleanupPreviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = fixture_module.InstallTransactionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_preview_reads_snapshot_and_has_no_runtime_writes(self) -> None:
        snapshot = self.fixture.base / "config-snapshot.toml"
        snapshot.write_text('model_catalog_json = ' + json.dumps(str(self.fixture.state / "merged-models.json"))
                            + '\nmodel = "gpt-6.1-sol"\n')
        snapshot.chmod(0o600)
        self.fixture.config.write_text('personality = "live-user-edit"\n')
        before = {str(path.relative_to(self.fixture.home)): path.read_bytes()
                  for path in self.fixture.home.rglob("*") if path.is_file()}
        result = subprocess.run([self.fixture.env["FIXTURE_NODE"],
            str(fixture_module.ROOT / "router/src/config-manager.mjs"),
            "cleanup-preview", str(snapshot)], env={**self.fixture.env, "CODEX_ROUTER_ISOLATED": "1"},
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"cleaned": 'model = "gpt-6.1-sol"\n'})
        after = {str(path.relative_to(self.fixture.home)): path.read_bytes()
                 for path in self.fixture.home.rglob("*") if path.is_file()}
        self.assertEqual(after, before)
        self.assertFalse((self.fixture.base / "calls").exists())

    def test_preview_refuses_linked_snapshot_without_disclosing_content(self) -> None:
        snapshot = self.fixture.base / "linked.toml"
        snapshot.symlink_to(self.fixture.config)
        result = subprocess.run([self.fixture.env["FIXTURE_NODE"],
            str(fixture_module.ROOT / "router/src/config-manager.mjs"),
            "cleanup-preview", str(snapshot)], env={**self.fixture.env, "CODEX_ROUTER_ISOLATED": "1"},
            capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertNotIn(self.fixture.original.decode().strip(), result.stderr)
