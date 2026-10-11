"""Exercise the supported shell installer with isolated local process fixtures."""
import json
import importlib.util
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from install_services import jev_labels

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
        for helper in ("install_services.py", "install_config_rollback.py"):
            if (ROOT / "server" / helper).exists():
                shutil.copy2(ROOT / "server" / helper, self.repo / "server" / helper)
        (self.repo / "server/install_preflight.py").write_text("# Preflight has its own isolated tests.\n")
        (self.repo / "server/desktop_session.py").write_text(
            'LABEL="io.github.jev-desktop-bridge"\n'
            'def snapshot(home, state):\n'
            ' return {"environment":"", "service_present":False, "service_running":False}\n'
            'def prepare_restore(previous, home, original): pass\n'
            'def finish_restore(previous, home, original): pass\n')
        self.commands = self.base / "commands"
        self.commands.mkdir()
        self.env = {**os.environ, "HOME": str(self.home),
                    "CODEX_HOME": str(self.codex_home),
                    "CODEX_ROUTER_STATE_DIR": str(self.state),
                    "MODEL_ROUTER_STATE_DIR": str(self.state),
                    "MODEL_ROUTER_USER_MODELS": str(self.state / "user-models.json"),
                    "MODEL_ROUTER_MODEL_PICKER_STATE": str(self.state / "model-picker.json"),
                    "FIXTURE_SOURCE": str(ROOT),
                    "PATH": str(self.commands) + os.pathsep + os.environ["PATH"],
                    "FIXTURE_CALLS": str(self.base / "calls"),
                    "FIXTURE_NODE": shutil.which("node"),
                    "FIXTURE_MANAGER": str(ROOT / "router/src/config-manager.mjs")}
        self._script(self.commands / "launchctl", "#!/bin/sh\n[ \"$1\" != print ]\n")
        self._script(self.commands / "node", '''#!/usr/bin/env python3
import json,os,pathlib,sys,subprocess
state=pathlib.Path(os.environ['CODEX_ROUTER_STATE_DIR'])
with open(os.environ['FIXTURE_CALLS'],'a') as log:log.write('node '+ ' '.join(sys.argv[1:])+'\\n')
if 'config-manager.mjs' in sys.argv[1]:
 os.execv(os.environ['FIXTURE_NODE'],[os.environ['FIXTURE_NODE'],os.environ['FIXTURE_MANAGER'],*sys.argv[2:]])
if 'configure-model.mjs' in sys.argv[1]:
 os.execv(os.environ['FIXTURE_NODE'],[os.environ['FIXTURE_NODE'],os.environ['FIXTURE_SOURCE']+'/server/configure-model.mjs'])
if 'configure-auth.mjs' in sys.argv[1]:
 (state/'fixture-jev-auth').write_text('configured')
if 'discovery-mode.mjs' in sys.argv[1]:
 (state/'discovery-mode.json').write_text(json.dumps({'version':1,'discovery':'enabled'}))
if 'catalog.mjs' in sys.argv[1]:
 if os.environ.get('FIXTURE_CHECK_OWNER'):
  source=(pathlib.Path(os.environ['FIXTURE_SOURCE'])/'router/src/state-owner.mjs').as_uri()
  code="import {assertStateOwnership} from '"+source+"';assertStateOwnership('publish native catalog')"
  subprocess.run([os.environ['FIXTURE_NODE'],'--input-type=module','-e',code],check=True)
 (state/'merged-models.json').write_text(json.dumps({'models':[] if os.environ.get('FIXTURE_EMPTY') else [{'slug':'test/native'}]}))
''')
        self._script(self.repo / "router/bin/codex-router", '''#!/usr/bin/env python3
import json,os,pathlib,sys
state=pathlib.Path(os.environ['CODEX_ROUTER_STATE_DIR'])
with open(os.environ['FIXTURE_CALLS'],'a') as log:log.write('cli '+' '.join(sys.argv[1:])+'\\n')
if sys.argv[1:3]==['providers','generic']:
 if os.environ.get('FIXTURE_STALE_SERVICE') and not (state/'fixture-service-repaired').exists():
  raise RuntimeError('stale service must be repaired before provider publication/restart')
 if 'show' in sys.argv:sys.exit(1)
if sys.argv[1:4]==['providers','generic','enable']:
 (state/'generic-providers.json').write_text(json.dumps({'version':1,'providers':[{
  'id':'jev','displayName':'Jev Router','baseUrl':'http://127.0.0.1:4319/v1',
  'adapter':'openai-responses','allowPrivate':True,'enabled':True}]}))
if sys.argv[1:3]==['chatgpt-session','enable']:
 if json.loads((state/'discovery-mode.json').read_text())['discovery']=='disabled':
  print('ChatGPT session sharing cannot be enabled while credential discovery is disabled.');sys.exit(1)
''')
        installer = '''#!/usr/bin/env python3
import json,os,pathlib,sys,subprocess
state=pathlib.Path(os.environ['CODEX_ROUTER_STATE_DIR'])
with open(os.environ['FIXTURE_CALLS'],'a') as log:log.write('install '+' '.join(sys.argv[1:])+'\\n')
if '--prepare-only' in sys.argv:sys.exit(0)
if '--take-over-managed-router' not in sys.argv:
 # Use the doctor's actual provider/model readiness helpers before activation.
 source=(pathlib.Path(os.environ['FIXTURE_SOURCE'])/'router/src').as_uri()
 code="import {genericProviderConfigured} from '"+source+"/generic-provider-readiness.mjs';" \
      +"import {selectedConfiguredListedModels} from '"+source+"/provider-selection.mjs';" \
      +"if(!genericProviderConfigured('jev'))throw Error('FAIL Enabled providers: none');" \
      +"if(!['jev/auto','jev/manual','jev/sol','jev/astra'].every(s=>selectedConfiguredListedModels().some(m=>m.slug===s)))throw Error('FAIL Merged catalog');"
 subprocess.run([os.environ['FIXTURE_NODE'],'--input-type=module','-e',code],check=True)
 if not (state/'fixture-jev-auth').exists():
  raise RuntimeError('Jev authentication must be configured before embedded validation')
(state/'fixture-service-repaired').write_text('repaired')
if os.environ.get('FIXTURE_FAIL_EMBEDDED'):
 raise RuntimeError('synthetic embedded installation failure')
disabled='--no-discovery' in sys.argv
(state/'discovery-mode.json').write_text(json.dumps({'version':1,'discovery':'disabled' if disabled else 'enabled'}))
(state/'merged-models.json').write_text(json.dumps({'models':[] if disabled else [{'slug':'test/native'}]}))
(state/'caller-secret').write_text('synthetic-installer-caller-key-long-enough\\n')
(state/'loaded-routes.json').write_text(json.dumps(['jev/auto']))
subprocess.run([os.environ['FIXTURE_NODE'],os.environ['FIXTURE_MANAGER'],'enable'],check=True)
'''
        self._script(self.repo / "router/install.sh", installer)
        self._script(self.repo / "router/bin/install", installer)
        self._script(self.repo / "router/bin/control", '''#!/usr/bin/env python3
import os,pathlib,sys
if sys.argv[1:3]==['picker','set']:
 source=(pathlib.Path(os.environ['FIXTURE_SOURCE'])/'router/src/model-picker-state.mjs').as_uri()
 code="import {setModelVisible} from '"+source+"';setModelVisible(process.argv[1],true)"
 os.execv(os.environ['FIXTURE_NODE'],[os.environ['FIXTURE_NODE'],'--input-type=module','-e',code,sys.argv[3]])
if sys.argv[1:3]==['service','restart']:
 source=(pathlib.Path(os.environ['FIXTURE_SOURCE'])/'router/src/user-models.mjs').as_uri()
 code="import {readUserModels} from '"+source+"';import {writeFileSync} from 'node:fs';writeFileSync(process.env.CODEX_ROUTER_STATE_DIR+'/loaded-routes.json',JSON.stringify(readUserModels().map(r=>r.slug)))"
 os.execv(os.environ['FIXTURE_NODE'],[os.environ['FIXTURE_NODE'],'--input-type=module','-e',code])
''')
        self._script(self.repo / "server/install-service.sh", "#!/bin/sh\nexit 0\n")
        (self.repo / "server/smoke.py").write_text(
            'import os,sys\nsys.exit(7 if os.environ.get("FIXTURE_FAIL_SMOKE") else 0)\n')

    def test_begin_rejects_route_state_overlap_before_snapshot(self):
        routes = self.codex_home / "jev-desktop-thread-routes"
        routes.mkdir(mode=0o700)
        for state in (routes, routes / "child"):
            with self.subTest(state=state), mock.patch.dict(os.environ, {
                **self.env, "MODEL_ROUTER_STATE_DIR": str(state),
            }):
                with self.assertRaisesRegex(ValueError, "Desktop route state"):
                    transaction.begin()
            self.assertFalse((self.codex_home / "jev-install-backups").exists())
        alias = self.base / "route-alias"
        alias.symlink_to(routes, target_is_directory=True)
        with mock.patch.dict(os.environ, {**self.env, "MODEL_ROUTER_STATE_DIR": str(alias / "child")}):
            with self.assertRaisesRegex(ValueError, "Desktop route state"):
                transaction.begin()
        self.assertFalse((self.codex_home / "jev-install-backups").exists())

    def test_rollback_preserves_external_desktop_route_writer_state(self):
        routes = self.codex_home / "jev-desktop-thread-routes"
        routes.mkdir(mode=0o700)
        record = routes / "fixture.json"
        record.write_text('{"revision":1}')
        record.chmod(0o600)
        with mock.patch.dict(os.environ, self.env), mock.patch.object(transaction.sys, "platform", "linux"):
            backup = transaction.begin()
            record.write_text('{"revision":2}')
            lock = routes / "fixture.json.lock"
            lock.write_text("active writer")
            lock.chmod(0o600)
            transaction.restore(backup)
        self.assertEqual(record.read_text(), '{"revision":2}')
        self.assertEqual(lock.read_text(), "active writer")
        self.assertEqual(record.stat().st_mode & 0o777, 0o600)
        self.assertEqual(lock.stat().st_mode & 0o777, 0o600)
        self.assertEqual(routes.stat().st_mode & 0o777, 0o700)
        self.assertFalse((backup / "state/desktop/thread-routes").exists())

    @staticmethod
    def _script(path: Path, text: str):
        path.write_text(text)
        path.chmod(0o755)

    def run_install(self, **flags):
        return subprocess.run(["sh", str(self.repo / "install.sh")],
                              env={**self.env, **flags}, capture_output=True,
                              text=True, timeout=20)

    def test_desktop_opt_in_failure_restores_original_state(self) -> None:
        desktop = self.state / "desktop"
        desktop.mkdir()
        (desktop / "manifest.json").write_text("original launcher state")
        (self.repo / "server/install_desktop.py").write_text(
            "import os,pathlib,sys\n"
            "if '--check' in sys.argv: sys.exit(0)\n"
            "root=pathlib.Path(os.environ['CODEX_ROUTER_STATE_DIR'])/'desktop'\n"
            "(root/'manifest.json').write_text('failed candidate')\n"
            "sys.exit(9)\n")
        result = subprocess.run(["sh", str(self.repo / "install.sh"), "--desktop"],
                                env=self.env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 9, result.stderr)
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertEqual((desktop / "manifest.json").read_text(), "original launcher state")

    def test_supported_desktop_checks_before_setup_and_rechecks_after_smoke(self) -> None:
        (self.repo / "server/install_desktop.py").write_text(
            "import os,sys\n"
            "with open(os.environ['FIXTURE_CALLS'], 'a') as log:\n"
            " log.write('desktop-check\\n' if '--check' in sys.argv else 'desktop-install\\n')\n")
        result = subprocess.run(["sh", str(self.repo / "install.sh"), "--desktop"],
                                env=self.env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = (self.base / "calls").read_text().splitlines()
        self.assertEqual(calls[0], "desktop-check")
        self.assertEqual(calls[-1], "desktop-install")

    def test_unknown_desktop_is_rejected_before_transaction_or_services(self) -> None:
        (self.repo / "server/install_desktop.py").write_text(
            "import sys\nprint('Unverified Desktop build', file=sys.stderr)\nsys.exit(9)\n")
        before = {str(p.relative_to(self.codex_home)): p.read_bytes()
                  for p in self.codex_home.rglob("*") if p.is_file()}
        result = subprocess.run(["sh", str(self.repo / "install.sh"), "--desktop"],
                                env=self.env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 9, result.stderr)
        self.assertFalse((self.base / "calls").exists(), "No dependency or service commands")
        after = {str(p.relative_to(self.codex_home)): p.read_bytes()
                 for p in self.codex_home.rglob("*") if p.is_file()}
        self.assertEqual(after, before)
        self.assertNotIn("previous configuration restored", result.stderr)

    def test_fresh_install_enables_required_discovery_and_completes(self):
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = (self.base / "calls").read_text()
        self.assertNotIn("install --no-provider --no-discovery", calls)
        self.assertIn("chatgpt-session enable", calls)
        self.assertTrue(json.loads((self.state / "merged-models.json").read_text())["models"])

    def test_embedded_failure_restores_preregistered_state(self) -> None:
        result = self.run_install(FIXTURE_FAIL_EMBEDDED="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("synthetic embedded installation failure", result.stderr)
        self.assertEqual(self.config.read_bytes(), self.original)
        for name in ["generic-providers.json", "user-models.json", "fixture-jev-auth"]:
            self.assertFalse((self.state / name).exists(), name)

    def test_reinstall_repairs_stale_service_before_provider_publication(self) -> None:
        (self.state / "enabled-providers.json").write_text('{"version":1,"providers":[]}')
        result = self.run_install(FIXTURE_STALE_SERVICE="1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = (self.base / "calls").read_text()
        self.assertLess(calls.index("install --take-over-managed-router"),
                        calls.index("cli providers generic show jev"))

    def test_install_preserves_existing_provider_selection(self) -> None:
        selection = '{"version":1,"providers":["deepseek"]}\n'
        (self.state / "enabled-providers.json").write_text(selection)
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.state / "enabled-providers.json").read_text(), selection)

    def test_reinstall_keeps_default_config_and_profile_identical(self) -> None:
        first = self.run_install()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(self.config.read_bytes(), self.original)
        profile = self.codex_home / "jev.config.toml"
        previous = profile.read_bytes()
        second = self.run_install()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertEqual(profile.read_bytes(), previous)

    def test_late_failure_restores_existing_profile(self) -> None:
        profile = self.codex_home / "jev.config.toml"
        previous = '# Jev managed isolated profile v1\nmodel = "previous"\n'
        profile.write_text(previous)
        result = self.run_install(FIXTURE_FAIL_SMOKE="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(profile.read_text(), previous)
        self.assertEqual(self.config.read_bytes(), self.original)

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
        self.assertFalse((self.codex_home / "jev.config.toml").exists())
        self.assertEqual((self.codex_home / "auth.json").read_text(), '{"synthetic":true}\n')

    def test_existing_idle_install_transitions_to_required_discovery(self):
        (self.state / "enabled-providers.json").write_text('{"version":1,"providers":[]}\n')
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = (self.base / "calls").read_text()
        self.assertIn("install --take-over-managed-router", calls)
        self.assertEqual(json.loads((self.state / "discovery-mode.json").read_text())["discovery"], "enabled")

    def test_full_reinstall_authorizes_ownership_before_catalog_publication(self):
        (self.state / "install-manifest.json").write_text(json.dumps({
            "version": 1, "current": {"sourceRoot": str(self.base / "previous/router")},
        }))
        result = self.run_install(FIXTURE_CHECK_OWNER="1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_full_install_reloads_router_after_publishing_all_four_routes(self):
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        loaded = json.loads((self.state / "loaded-routes.json").read_text())
        self.assertEqual(loaded, ["jev/auto", "jev/manual", "jev/sol", "jev/astra"])

    def test_four_mode_reinstall_preserves_other_models_and_picker_entries(self):
        original = {"version": 1, "models": [{"slug": "fixture/other", "provider": "fixture"}]}
        (self.state / "user-models.json").write_text(json.dumps(original))
        (self.state / "model-picker.json").write_text(json.dumps({
            "version": 1, "visible": ["fixture/other"], "hidden": [],
        }))
        for _ in range(2):
            result = self.run_install()
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        rows = json.loads((self.state / "user-models.json").read_text())["models"]
        self.assertEqual([row["slug"] for row in rows],
                         ["fixture/other", "jev/auto", "jev/manual", "jev/sol", "jev/astra"])
        visible = json.loads((self.state / "model-picker.json").read_text())["visible"]
        self.assertEqual(set(visible), {"fixture/other", "jev/auto", "jev/manual", "jev/sol", "jev/astra"})

    def test_fixed_catalog_routes_use_exact_identities_and_bounded_placeholder_efforts(self):
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        rows = {row["slug"]: row for row in json.loads((self.state / "user-models.json").read_text())["models"]}
        for mode, label in (("sol", "Sol"), ("astra", "Astra")):
            with self.subTest(mode=mode):
                row = rows[f"jev/{mode}"]
                self.assertEqual(row["displayName"], f"Jev {label} Router")
                self.assertEqual(row["gatewayModel"], f"jev-{mode}")
                self.assertEqual(row["upstreamModel"], mode)
                self.assertEqual(row["defaultEffort"], "high")
                self.assertEqual([item["effort"] for item in row["reasoningLevels"]],
                                 ["low", "medium", "high", "xhigh", "max"])
                self.assertIn("selected effort is ignored", row["description"])

    def test_late_failure_restores_two_mode_catalog_and_picker_snapshot(self):
        saved = {
            "user-models.json": '{"version":1,"models":[{"slug":"fixture/other","provider":"fixture"}]}',
            "model-picker.json": '{"version":1,"visible":["fixture/other"],"hidden":["jev/auto"]}',
        }
        for name, text in saved.items():
            (self.state / name).write_text(text)
        result = self.run_install(FIXTURE_FAIL_SMOKE="1")
        self.assertNotEqual(result.returncode, 0)
        for name, text in saved.items():
            self.assertEqual((self.state / name).read_text(), text)

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

    def test_isolation_rejects_default_router_model_and_nested_openai_url(self) -> None:
        self.assertEqual(self.run_install().returncode, 0)
        for text in ['model = "jev/auto"\n',
                     'model_provider = "jev-router-auto"\n',
                     'model_provider = "jev-router-manual"\n',
                     'model_provider = "jev-router-sol"\n',
                     'model_provider = "jev-router-astra"\n',
                     '[model_providers.openai]\nbase_url = "http://localhost:4202/v1"\n']:
            with self.subTest(config=text):
                self.config.write_text(text)
                with mock.patch.dict(os.environ, self.env), self.assertRaises(ValueError):
                    transaction.validate_isolation()

    def test_isolation_rejects_incomplete_profile_transport(self) -> None:
        (self.codex_home / "jev.config.toml").write_text(
            'model="jev/auto"\nmodel_provider="jev-router"\n'
            '[model_providers.jev-router]\nrequires_openai_auth=false\n')
        with mock.patch.dict(os.environ, self.env), self.assertRaises(ValueError):
            transaction.validate_isolation()

    def test_desktop_transaction_restores_session_around_state_replacement(self) -> None:
        saved = {"environment": "", "service_present": False, "service_running": False}
        events = []
        marker = self.state / "candidate-state"

        def prepare(*args: object) -> None:
            self.assertTrue(marker.exists())
            events.append("stopped")

        def finish(*args: object) -> None:
            self.assertFalse(marker.exists())
            events.append("restored")

        with mock.patch.dict(os.environ, {**self.env, "JEV_INSTALL_DESKTOP": "1"}), \
                mock.patch.object(transaction.sys, "platform", "darwin"), \
                mock.patch.object(transaction.desktop_session, "snapshot", return_value=saved), \
                mock.patch.object(transaction.desktop_session, "prepare_restore", side_effect=prepare), \
                mock.patch.object(transaction.desktop_session, "finish_restore", side_effect=finish):
            backup = transaction.begin()
            marker.write_text("new candidate")
            transaction.restore(backup)
        self.assertEqual(events, ["stopped", "restored"])
        manifest = json.loads((backup / "manifest.json").read_text())
        self.assertEqual(manifest["desktop_session"], saved)

    def stage_service_backup(self):
        # The current embedded producer and supported Jev labels are provable;
        # undocumented legacy embedded definitions must be refused, not stopped.
        self.service_labels = ("io.github.codex-router", *jev_labels())
        for label in self.service_labels:
            plist = self.home / "Library/LaunchAgents" / f"{label}.plist"
            plist.parent.mkdir(parents=True, exist_ok=True)
            source = ROOT / "router"
            script = "/fixture/server/jev_server.py" if label in jev_labels() else str(source / "src/start.mjs")
            plist.write_bytes(plistlib.dumps({"Label": label, "ProgramArguments": ["/fixture/runtime", script],
                "WorkingDirectory": str(source), "EnvironmentVariables": {
                    "CODEX_HOME": str(self.codex_home), **{key: str(self.state) for key in (
                        "MODEL_ROUTER_STATE_DIR", "CODEX_ROUTER_STATE_DIR", "KIMI_CODEX_STATE_DIR")}}}))
        real_run = subprocess.run
        def launchctl(command, **kwargs):
            if command[0] != "launchctl":
                return real_run(command, **kwargs)
            present = command[-1].split("/")[-1] in self.service_labels
            return subprocess.CompletedProcess(command, 0 if command[1] != "print" or present else 1)
        with mock.patch.dict(os.environ, self.env), mock.patch.object(transaction.sys, "platform", "darwin"), \
                mock.patch.object(transaction.subprocess, "run", side_effect=launchctl):
            return transaction.begin()

    def test_services_are_all_stopped_before_state_restore_or_restart(self):
        backup = self.stage_service_backup()
        stopped = []
        writer_file = self.state / "post-snapshot-service-write"

        def launchctl(command, **kwargs):
            if command[1] == "print" and command[-1].split("/")[-1] in stopped:
                return subprocess.CompletedProcess(command, 113)
            if command[1] == "bootout":
                writer_file.write_text("last write by still running service")
                stopped.append(command[-1].split("/")[-1])
            if command[1] == "bootstrap":
                self.assertEqual(set(stopped), set(self.service_labels))
                self.assertFalse(writer_file.exists())
            return subprocess.CompletedProcess(command, 0)

        with mock.patch.dict(os.environ, self.env), mock.patch.object(transaction.sys, "platform", "darwin"), \
                mock.patch.object(transaction.subprocess, "run", side_effect=launchctl):
            transaction.restore(backup)
        self.assertFalse(writer_file.exists())

    def test_stop_failure_leaves_state_in_place_and_client_config_restored(self):
        backup = self.stage_service_backup()
        (self.state / "live-marker").write_text("keep until service stops")
        self.config.write_bytes(self.original)

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
