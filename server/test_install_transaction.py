"""Exercise the supported shell installer with isolated local process fixtures."""
import json
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("install_transaction", ROOT / "server/install_transaction.py")
transaction = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(transaction)


class InstallTransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / "repo"
        self.home = self.base / "home"
        self.codex_home = self.home / ".codex"
        self.state = self.codex_home / "codex-router"
        self.state.mkdir(parents=True)
        self.config = self.codex_home / "config.toml"
        self.original = b'personality = "pragmatic"\n'
        self.config.write_bytes(self.original)
        (self.codex_home / "auth.json").write_text('{"synthetic":true}\n')
        (self.state / "discovery-mode.json").write_text(
            '{"version":1,"discovery":"disabled"}\n')
        for folder in ["router/bin", "router/src", "server"]:
            (self.repo / folder).mkdir(parents=True)
        shutil.copy2(ROOT / "install.sh", self.repo / "install.sh")
        transaction = ROOT / "server/install_transaction.py"
        if transaction.exists():
            shutil.copy2(transaction, self.repo / "server/install_transaction.py")
        (self.repo / "server/install_preflight.py").write_text("# Preflight has its own isolated tests.\n")
        self.commands = self.base / "commands"
        self.commands.mkdir()
        self.env = {**os.environ, "HOME": str(self.home),
                    "CODEX_HOME": str(self.codex_home),
                    "CODEX_ROUTER_STATE_DIR": str(self.state),
                    "PATH": str(self.commands) + os.pathsep + os.environ["PATH"],
                    "FIXTURE_CALLS": str(self.base / "calls")}
        self._script(self.commands / "node", '''#!/usr/bin/env python3
import json,os,pathlib,sys
state=pathlib.Path(os.environ['CODEX_ROUTER_STATE_DIR'])
with open(os.environ['FIXTURE_CALLS'],'a') as log:log.write('node '+ ' '.join(sys.argv[1:])+'\\n')
if 'discovery-mode.mjs' in sys.argv[1]:
 (state/'discovery-mode.json').write_text(json.dumps({'version':1,'discovery':'enabled'}))
if 'catalog.mjs' in sys.argv[1]:
 (state/'merged-models.json').write_text(json.dumps({'models':[] if os.environ.get('FIXTURE_EMPTY') else [{'slug':'test/native'}]}))
''')
        self._script(self.repo / "router/bin/codex-router", '''#!/usr/bin/env python3
import json,os,pathlib,sys
state=pathlib.Path(os.environ['CODEX_ROUTER_STATE_DIR'])
with open(os.environ['FIXTURE_CALLS'],'a') as log:log.write('cli '+' '.join(sys.argv[1:])+'\\n')
if sys.argv[1:3]==['providers','generic'] and 'show' in sys.argv:sys.exit(1)
if sys.argv[1:3]==['chatgpt-session','enable']:
 if json.loads((state/'discovery-mode.json').read_text())['discovery']=='disabled':
  print('ChatGPT session sharing cannot be enabled while credential discovery is disabled.');sys.exit(1)
''')
        installer = '''#!/usr/bin/env python3
import json,os,pathlib,sys
state=pathlib.Path(os.environ['CODEX_ROUTER_STATE_DIR'])
with open(os.environ['FIXTURE_CALLS'],'a') as log:log.write('install '+' '.join(sys.argv[1:])+'\\n')
if '--prepare-only' in sys.argv:sys.exit(0)
disabled='--no-discovery' in sys.argv
(state/'discovery-mode.json').write_text(json.dumps({'version':1,'discovery':'disabled' if disabled else 'enabled'}))
(state/'merged-models.json').write_text(json.dumps({'models':[] if disabled else [{'slug':'test/native'}]}))
(pathlib.Path(os.environ['CODEX_HOME'])/'config.toml').write_text('# BEGIN codex-router-managed\\nmodel_catalog_json = "'+str(state/'merged-models.json')+'"\\n# END codex-router-managed\\n')
'''
        self._script(self.repo / "router/install.sh", installer)
        self._script(self.repo / "router/bin/install", installer)
        self._script(self.repo / "router/bin/control", "#!/bin/sh\nexit 0\n")
        self._script(self.repo / "server/install-service.sh", "#!/bin/sh\nexit 0\n")
        (self.repo / "server/smoke.py").write_text(
            'import os,sys\nsys.exit(7 if os.environ.get("FIXTURE_FAIL_SMOKE") else 0)\n')

    @staticmethod
    def _script(path: Path, text: str):
        path.write_text(text)
        path.chmod(0o755)

    def run_install(self, **flags):
        return subprocess.run(["sh", str(self.repo / "install.sh")],
                              env={**self.env, **flags}, capture_output=True,
                              text=True, timeout=20)

    def test_fresh_install_enables_required_discovery_and_completes(self):
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = (self.base / "calls").read_text()
        self.assertNotIn("install --no-provider --no-discovery", calls)
        self.assertIn("chatgpt-session enable", calls)
        self.assertTrue(json.loads((self.state / "merged-models.json").read_text())["models"])

    def test_empty_catalog_is_rejected_before_live_config_activation(self):
        result = self.run_install(FIXTURE_EMPTY="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("non-empty", result.stderr)
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertNotIn("install --no-provider", (self.base / "calls").read_text())

    def test_late_failure_restores_original_config_and_state(self):
        result = self.run_install(FIXTURE_FAIL_SMOKE="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertEqual(json.loads((self.state / "discovery-mode.json").read_text())["discovery"], "disabled")
        self.assertFalse((self.state / "merged-models.json").exists())
        self.assertEqual((self.codex_home / "auth.json").read_text(), '{"synthetic":true}\n')

    def test_existing_idle_install_transitions_to_required_discovery(self):
        (self.state / "enabled-providers.json").write_text('{"version":1,"providers":[]}\n')
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = (self.base / "calls").read_text()
        self.assertIn("install --take-over-managed-router", calls)
        self.assertEqual(json.loads((self.state / "discovery-mode.json").read_text())["discovery"], "enabled")

    def test_rollback_preserves_owner_execute_permission(self):
        shim = self.state / "bin/codex"
        shim.parent.mkdir()
        self._script(shim, "#!/bin/sh\nexit 0\n")
        shim.chmod(0o700)
        result = self.run_install(FIXTURE_FAIL_SMOKE="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(shim.stat().st_mode & 0o777, 0o700)

    def test_private_copy_rejects_destination_symlink_without_touching_target(self):
        victim = self.base / "victim"
        victim.write_text("original")
        link = self.base / "link"
        link.symlink_to(victim)
        with self.assertRaises((ValueError, OSError)):
            transaction.private_copy(self.config, link)
        self.assertEqual(victim.read_text(), "original")

    def stage_service_backup(self):
        for label in transaction.LABELS:
            plist = self.home / "Library/LaunchAgents" / f"{label}.plist"
            plist.parent.mkdir(parents=True, exist_ok=True)
            plist.write_text("synthetic plist")
        with mock.patch.dict(os.environ, self.env), mock.patch.object(transaction.sys, "platform", "darwin"), \
                mock.patch.object(transaction.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)):
            return transaction.begin()

    def test_services_are_all_stopped_before_state_restore_or_restart(self):
        backup = self.stage_service_backup()
        stopped = []
        writer_file = self.state / "post-snapshot-service-write"

        def launchctl(command, **kwargs):
            if command[1] == "bootout":
                writer_file.write_text("last write by still running service")
                stopped.append(command[-1].split("/")[-1])
            if command[1] == "bootstrap":
                self.assertEqual(set(stopped), set(transaction.LABELS))
                self.assertFalse(writer_file.exists())
            return subprocess.CompletedProcess(command, 0)

        with mock.patch.dict(os.environ, self.env), mock.patch.object(transaction.sys, "platform", "darwin"), \
                mock.patch.object(transaction.subprocess, "run", side_effect=launchctl):
            transaction.restore(backup)
        self.assertFalse(writer_file.exists())

    def test_stop_failure_leaves_state_in_place_and_client_config_restored(self):
        backup = self.stage_service_backup()
        (self.state / "live-marker").write_text("keep until service stops")
        self.config.write_text("# BEGIN codex-router-managed\n")

        def launchctl(command, **kwargs):
            return subprocess.CompletedProcess(command, 1 if command[1] == "bootout" else 0)

        with mock.patch.dict(os.environ, self.env), mock.patch.object(transaction.sys, "platform", "darwin"), \
                mock.patch.object(transaction.subprocess, "run", side_effect=launchctl):
            with self.assertRaises(RuntimeError):
                transaction.restore(backup)
        self.assertTrue((self.state / "live-marker").exists())
        self.assertEqual(self.config.read_bytes(), self.original)


if __name__ == "__main__":
    unittest.main()
