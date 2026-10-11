"""Root installer rollback preserves concurrent configuration and legacy services."""
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tomllib
import unittest
from unittest import mock

import desktop_provider_registry
import install_config_rollback as config_rollback
import test_install_transaction as fixture_module

ROOT = fixture_module.ROOT
transaction = fixture_module.transaction


class RollbackSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = fixture_module.InstallTransactionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def late_config_edit(self, contents: str) -> subprocess.CompletedProcess:
        source = ('import os,pathlib\n'
                  'p=pathlib.Path(os.environ["CODEX_HOME"])/"config.toml"\n'
                  f'p.write_text({contents!r})\nraise SystemExit(7)\n')
        (self.fixture.repo / "server/smoke.py").write_text(source)
        return self.fixture.run_install()

    def test_root_failure_preserves_changed_existing_user_setting(self) -> None:
        expected = 'personality = "friendly"\n[features]\nfixture = true\n'
        result = self.late_config_edit(expected)
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertEqual(self.fixture.config.read_text(), expected)
        self.assertIn("previous configuration restored", result.stderr)

    def test_root_failure_preserves_config_created_after_begin(self) -> None:
        self.fixture.config.unlink()
        expected = 'model = "gpt-6.1-sol"\n'
        result = self.late_config_edit(expected)
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertEqual(self.fixture.config.read_text(), expected)

    def test_overlapping_managed_block_is_preserved_and_reported(self) -> None:
        original = ('# BEGIN codex-router-managed\n'
                    'model_provider = "codex-router"\n'
                    '# END codex-router-managed\n')
        self.fixture.config.write_text(original)
        with mock.patch.dict(os.environ, self.fixture.env), mock.patch.object(transaction.sys, "platform", "linux"):
            backup = transaction.begin()
            concurrent = original.replace('"codex-router"', '"foreign"')
            self.fixture.config.write_text(concurrent)
            with self.assertRaisesRegex(ValueError, "configuration.*conflict"):
                transaction.restore(backup)
        self.assertEqual(self.fixture.config.read_text(), concurrent)
        self.assertEqual((backup / "config-current.toml").read_text(), concurrent)
        self.assertEqual((backup / "config-current.toml").stat().st_mode & 0o777, 0o600)
        self.assertNotEqual(json.loads((backup / "result.json").read_text())["status"], "restored")

    def test_foreign_table_inside_owned_block_is_never_discarded(self) -> None:
        original = ('# BEGIN codex-router-managed\nmodel_provider = "codex-router"\n'
                    '# END codex-router-managed\n')
        self.fixture.config.write_text(original)
        with mock.patch.dict(os.environ, self.fixture.env), mock.patch.object(transaction.sys, "platform", "linux"):
            backup = transaction.begin()
            current = original.replace('# END', '[projects.fixture]\ntrust_level = "trusted"\n# END')
            self.fixture.config.write_text(current)
            with self.assertRaisesRegex(ValueError, "configuration.*conflict"):
                transaction.restore(backup)
        self.assertEqual(self.fixture.config.read_text(), current)

    def test_removed_owned_block_restores_exact_baseline_with_external_edit(self) -> None:
        original = ('personality = "pragmatic"\n# BEGIN codex-router-managed\n'
                    'model_provider = "codex-router"\n# END codex-router-managed\n')
        self.fixture.config.write_text(original)
        with mock.patch.dict(os.environ, self.fixture.env), mock.patch.object(transaction.sys, "platform", "linux"):
            backup = transaction.begin()
            self.fixture.config.write_text('personality = "friendly"\n[features]\nfixture = true\n')
            transaction.restore(backup)
        expected = original.replace('"pragmatic"', '"friendly"') + '[features]\nfixture = true\n'
        self.assertEqual(self.fixture.config.read_text(), expected)

    def test_ambiguous_config_preserves_file_and_reports_partial_rollback(self) -> None:
        with mock.patch.dict(os.environ, self.fixture.env), mock.patch.object(transaction.sys, "platform", "linux"):
            backup = transaction.begin()
            current = "# BEGIN codex-router-managed\n"
            self.fixture.config.write_text(current)
            with self.assertRaisesRegex(ValueError, "configuration.*conflict"):
                transaction.restore(backup)
        self.assertEqual(self.fixture.config.read_text(), current)

    def test_owned_only_block_removal_restores_original_byte_positions(self) -> None:
        block = '# BEGIN codex-router-managed\nmodel_provider="codex-router"\n# END codex-router-managed\n'
        before = block + 'personality = "pragmatic"\n'
        result = config_rollback.merge(before.encode(), before.removeprefix(block).encode(), self.fixture.state)
        self.assertEqual(result, before.encode())

    def test_desktop_rollback_removes_only_expected_generated_blocks(self) -> None:
        provider = {"name": "Jev", "base_url": "http://127.0.0.1:4202/v1", "wire_api": "responses",
                    "requires_openai_auth": False, "auth": {"command": "/fixture/node",
                    "args": ["/fixture/src/caller-key-auth-command.mjs", "/fixture/caller-secret"]}}
        desktop = self.fixture.state / "desktop"
        desktop.mkdir()
        (desktop / "manifest.json").write_text(json.dumps({"provider": provider,
            "appExecutable": "/Applications/ChatGPT.app/Contents/MacOS/ChatGPT"}))
        generated = desktop_provider_registry.render(provider)
        current = 'personality = "friendly"\n' + generated
        self.assertEqual(config_rollback.merge(self.fixture.original, current.encode(), self.fixture.state),
                         b'personality = "friendly"\n')
        with self.assertRaisesRegex(ValueError, "configuration.*conflict"):
            config_rollback.merge(self.fixture.original,
                current.replace('name = "Jev"', 'name = "User edit"', 1).encode(), self.fixture.state)

    def test_desktop_rollback_recognizes_legacy_and_four_provider_outputs(self) -> None:
        from test_desktop_provider_registry import provider
        value = provider()
        desktop = self.fixture.state / "desktop"
        desktop.mkdir()
        (desktop / "manifest.json").write_text(json.dumps({"provider": value,
            "appExecutable": "/Applications/ChatGPT.app/Contents/MacOS/ChatGPT"}))
        four = desktop_provider_registry.render(value)
        marker = "[model_providers.jev-router-sol]"
        two = four[:four.find(marker)] + desktop_provider_registry.END if marker in four else four
        for generated in (two, four):
            current = 'personality = "friendly"\n' + generated
            self.assertEqual(config_rollback.merge(self.fixture.original, current.encode(), self.fixture.state),
                             b'personality = "friendly"\n')
        legacy_original = self.fixture.original + two.replace('"/runtime/node"', '"/old/node"').encode()
        current = b'personality = "friendly"\n' + four.encode() + b'\n[features]\nuser_setting = true\n'
        expected = legacy_original.replace(b'"pragmatic"', b'"friendly"') + b'\n[features]\nuser_setting = true\n'
        self.assertEqual(config_rollback.merge(legacy_original, current, self.fixture.state), expected)
        with self.assertRaisesRegex(ValueError, "configuration.*conflict"):
            config_rollback.merge(legacy_original, current.replace(b'name = "Jev"', b'name = "User"', 1), self.fixture.state)

    def test_rollback_detects_a_second_edit_before_replacement(self) -> None:
        block = '# BEGIN codex-router-managed\nmodel_provider="codex-router"\n# END codex-router-managed\n'
        self.fixture.config.write_text(block + self.fixture.original.decode())
        with mock.patch.dict(os.environ, self.fixture.env), mock.patch.object(transaction.sys, "platform", "linux"):
            backup = transaction.begin()
            self.fixture.config.write_bytes(self.fixture.original)
            real_merge = config_rollback.merge
            def editing_merge(*args: object) -> bytes | None:
                result = real_merge(*args)
                self.fixture.config.write_text('personality = "edited again"\n')
                return result
            with mock.patch.object(config_rollback, "merge", side_effect=editing_merge):
                with self.assertRaisesRegex(ValueError, "configuration.*conflict"):
                    transaction.restore(backup)
        self.assertEqual(self.fixture.config.read_text(), 'personality = "edited again"\n')
        self.assertEqual((backup / "config-current.toml").read_bytes(), self.fixture.config.read_bytes())

    def test_root_owned_cleanup_failure_restores_exact_legacy_config(self) -> None:
        original = ('# BEGIN codex-router-managed\nmodel_provider = "codex-router"\n'
                    '# END codex-router-managed\n\npersonality = "pragmatic"\n')
        self.fixture.config.write_text(original)
        result = self.fixture.run_install(FIXTURE_FAIL_SMOKE="1")
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertEqual(self.fixture.config.read_text(), original)

    def test_root_service_migration_failure_restores_legacy_definition_and_load(self) -> None:
        for name in ("install-service.sh", "install_service.py", "install_services.py"):
            shutil.copy2(ROOT / "server" / name, self.fixture.repo / "server" / name)
        (self.fixture.repo / "server/healthcheck.py").write_text("raise SystemExit(0)\n")
        legacy = "io.0xnatoshi.jev-router"
        plist = self.fixture.home / "Library/LaunchAgents" / f"{legacy}.plist"
        plist.parent.mkdir(parents=True)
        original = plistlib.dumps({"Label": legacy, "ProgramArguments": [sys.executable,
                                   "/fixture/old/server/jev_server.py"]})
        plist.write_bytes(original)
        registry = self.fixture.base / "loaded.json"
        registry.write_text(json.dumps({legacy: 111}))
        self.fixture.env["SERVICE_REGISTRY"] = str(registry)
        self.fixture._script(self.fixture.commands / "launchctl", '''#!/usr/bin/env python3
import json,os,pathlib,plistlib,sys
file=pathlib.Path(os.environ["SERVICE_REGISTRY"])
data=json.loads(file.read_text())
verb=sys.argv[1]
label=sys.argv[-1].split("/")[-1]
if verb=="print":
 if label not in data: sys.exit(113)
 print("pid =",data[label])
elif verb=="bootout": data.pop(label,None)
elif verb=="bootstrap":
 label=plistlib.loads(pathlib.Path(sys.argv[-1]).read_bytes())["Label"]
 data[label]=111 if label=="io.0xnatoshi.jev-router" else 222
file.write_text(json.dumps(data))
''')
        self.fixture._script(self.fixture.commands / "lsof", '''#!/usr/bin/env python3
import json,os,pathlib
for pid in json.loads(pathlib.Path(os.environ["SERVICE_REGISTRY"]).read_text()).values(): print("p"+str(pid))
''')
        result = self.fixture.run_install(FIXTURE_FAIL_SMOKE="1")
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertEqual(plist.read_bytes(), original)
        self.assertEqual(json.loads(registry.read_text()), {legacy: 111})
        self.assertFalse((plist.parent / "com.thibaultsaintjean.jev-router.plist").exists())
        conflicting = "# BEGIN codex-router-managed\n"
        result = self.late_config_edit(conflicting)
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertIn("restoration needs attention", result.stderr)
        self.assertEqual(self.fixture.config.read_text(), conflicting)
        self.assertEqual(plist.read_bytes(), original)
        self.assertEqual(json.loads(registry.read_text()), {legacy: 111})

    def service_fixture(self, script: str, *, disabled: bool = False,
                        label: str = "io.0xnatoshi.jev-router", definition: dict | None = None
                        ) -> tuple[Path, bytes, Path, dict, Path]:
        """Model launchd's loaded and disabled states independently and strictly."""
        for name in ("install-service.sh", "install_service.py", "install_services.py"):
            shutil.copy2(ROOT / "server" / name, self.fixture.repo / "server" / name)
        (self.fixture.repo / "server/healthcheck.py").write_text("raise SystemExit(0)\n")
        plist = self.fixture.home / "Library/LaunchAgents" / f"{label}.plist"
        plist.parent.mkdir(parents=True)
        original = plistlib.dumps(definition or {"Label": label, "ProgramArguments": [sys.executable, script]})
        plist.write_bytes(original)
        registry = self.fixture.base / "services.json"
        before = {"loaded": {label: 111}, "disabled": [label] if disabled else []}
        registry.write_text(json.dumps(before))
        calls = self.fixture.base / "service-mutations.json"
        calls.write_text("[]")
        self.fixture.env.update(SERVICE_REGISTRY=str(registry), SERVICE_MUTATIONS=str(calls),
                                SERVICE_ORIGINAL_LABEL=label)
        self.fixture._script(self.fixture.commands / "launchctl", '''#!/usr/bin/env python3
import json,os,pathlib,plistlib,sys
file=pathlib.Path(os.environ["SERVICE_REGISTRY"])
data=json.loads(file.read_text())
verb=sys.argv[1]
label=sys.argv[-1].split("/")[-1]
if verb=="print":
 if label not in data["loaded"]: sys.exit(113)
 print("pid =",data["loaded"][label])
elif verb=="print-disabled":
 for item in data["disabled"]: print('"'+item+'" => true')
else:
 log=pathlib.Path(os.environ["SERVICE_MUTATIONS"])
 calls=json.loads(log.read_text())
 calls.append(sys.argv[1:])
 log.write_text(json.dumps(calls))
 if verb=="bootout": data["loaded"].pop(label,None)
 elif verb=="disable":
  if label not in data["disabled"]: data["disabled"].append(label)
 elif verb=="enable":
  if label in data["disabled"]: data["disabled"].remove(label)
 elif verb=="bootstrap":
  label=plistlib.loads(pathlib.Path(sys.argv[-1]).read_bytes())["Label"]
  if label in data["disabled"]: sys.exit(5)
  data["loaded"][label]=111 if label==os.environ["SERVICE_ORIGINAL_LABEL"] else 222
 else: raise AssertionError(verb)
file.write_text(json.dumps(data))
''')
        self.fixture._script(self.fixture.commands / "lsof", '''#!/usr/bin/env python3
import json,os,pathlib
for label,pid in json.loads(pathlib.Path(os.environ["SERVICE_REGISTRY"]).read_text())["loaded"].items():
 if label.endswith(".jev-router"): print("p"+str(pid))
''')
        return plist, original, registry, before, calls

    def test_root_rejects_foreign_jev_service_without_rollback_mutations(self) -> None:
        plist, original, registry, before, calls = self.service_fixture("/fixture/foreign/service.py")
        state_before = {path.relative_to(self.fixture.state): path.read_bytes()
                        for path in self.fixture.state.rglob("*") if path.is_file()}
        result = self.fixture.run_install()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("foreign service definition", result.stderr)
        self.assertEqual(json.loads(calls.read_text()), [], "refusal must not stop or restart a foreign service")
        self.assertEqual(json.loads(registry.read_text()), before)
        self.assertEqual(plist.read_bytes(), original)
        self.assertEqual(self.fixture.config.read_bytes(), self.fixture.original)
        self.assertEqual({path.relative_to(self.fixture.state): path.read_bytes()
                          for path in self.fixture.state.rglob("*") if path.is_file()}, state_before)

    def test_root_failure_restores_service_that_was_loaded_and_disabled(self) -> None:
        plist, original, registry, before, calls = self.service_fixture(
            "/fixture/old/server/jev_server.py", disabled=True)
        result = self.fixture.run_install(FIXTURE_FAIL_SMOKE="1")
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertIn("previous configuration restored", result.stderr)
        self.assertEqual(json.loads(registry.read_text()), before)
        self.assertEqual(plist.read_bytes(), original)
        mutations = json.loads(calls.read_text())
        restored = [call[0] for call in mutations if call[-1].endswith("io.0xnatoshi.jev-router")
                    or call[-1].endswith("io.0xnatoshi.jev-router.plist")]
        self.assertEqual(restored[-3:], ["enable", "bootstrap", "disable"])

    def test_rollback_rejects_concurrent_foreign_service_before_stopping_any_label(self) -> None:
        plist, _, _, _, calls = self.service_fixture("/fixture/old/server/jev_server.py")
        with mock.patch.dict(os.environ, self.fixture.env), mock.patch.object(transaction.sys, "platform", "darwin"):
            backup = transaction.begin()
            foreign = plistlib.dumps({"Label": "io.0xnatoshi.jev-router",
                                     "ProgramArguments": [sys.executable, "/foreign/service.py"]})
            plist.write_bytes(foreign)
            with self.assertRaisesRegex(ValueError, "foreign service definition"):
                transaction.restore(backup)
        self.assertEqual(json.loads(calls.read_text()), [])
        self.assertEqual(plist.read_bytes(), foreign)

    def embedded_definition(self, source: Path) -> dict:
        return {"Label": "io.github.codex-router", "ProgramArguments": ["/fixture/runtime", str(source / "src/start.mjs")],
                "WorkingDirectory": str(source), "EnvironmentVariables": {
                    "CODEX_HOME": str(self.fixture.codex_home),
                    **{key: str(self.fixture.state) for key in (
                        "MODEL_ROUTER_STATE_DIR", "CODEX_ROUTER_STATE_DIR", "KIMI_CODEX_STATE_DIR")}}}

    def test_root_restores_valid_embedded_definition_from_recorded_source(self) -> None:
        source = self.fixture.base / "previous/router"
        (self.fixture.state / "install-manifest.json").write_text(json.dumps({
            "version": 1, "current": {"sourceRoot": str(source)}}))
        definition = self.embedded_definition(source)
        plist, original, registry, before, _ = self.service_fixture(
            "", label="io.github.codex-router", definition=definition)
        result = self.fixture.run_install(FIXTURE_FAIL_SMOKE="1")
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertIn("previous configuration restored", result.stderr)
        self.assertEqual(plist.read_bytes(), original)
        self.assertEqual(json.loads(registry.read_text()), before)

    def test_root_rejects_unanchored_embedded_definition_without_mutations(self) -> None:
        definition = self.embedded_definition(self.fixture.base / "unrelated-program")
        plist, original, registry, before, calls = self.service_fixture(
            "", label="io.github.codex-router", definition=definition)
        result = self.fixture.run_install()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("foreign service definition", result.stderr)
        self.assertEqual(json.loads(calls.read_text()), [])
        self.assertEqual(plist.read_bytes(), original)
        self.assertEqual(json.loads(registry.read_text()), before)

    def test_begin_rejects_unknown_legacy_embedded_definitions(self) -> None:
        agents = self.fixture.home / "Library/LaunchAgents"
        agents.mkdir(parents=True)
        for label in ("io.github.kimi-codex-router", "com.ziwenxu.kimi-codex-proxy"):
            with self.subTest(label=label):
                plist = agents / f"{label}.plist"
                original = plistlib.dumps({"Label": label, "ProgramArguments": ["/fixture/legacy", "/fixture/src/start.mjs"]})
                plist.write_bytes(original)
                with mock.patch.dict(os.environ, self.fixture.env), mock.patch.object(transaction.sys, "platform", "linux"):
                    with self.assertRaisesRegex(ValueError, "legacy service definition"):
                        transaction.begin()
                self.assertEqual(plist.read_bytes(), original)
                plist.unlink()

    def test_embedded_ownership_rejects_changed_runtime_anchors_before_rollback(self) -> None:
        source = ROOT / "router"
        definition = self.embedded_definition(source)
        plist, _, registry, before, calls = self.service_fixture(
            "", label="io.github.codex-router", definition=definition)
        with mock.patch.dict(os.environ, self.fixture.env), mock.patch.object(transaction.sys, "platform", "darwin"):
            backup = transaction.begin()
            definition["EnvironmentVariables"]["MODEL_ROUTER_STATE_DIR"] = "/foreign/state"
            changed = plistlib.dumps(definition)
            plist.write_bytes(changed)
            with self.assertRaisesRegex(ValueError, "foreign service definition"):
                transaction.restore(backup)
        self.assertEqual(json.loads(calls.read_text()), [])
        self.assertEqual(plist.read_bytes(), changed)
        self.assertEqual(json.loads(registry.read_text()), before)

    def test_quoted_marker_text_remains_user_owned(self) -> None:
        original = 'notes = """\n# BEGIN codex-router-managed\nmodel="sample"\n# END codex-router-managed\n"""\n'
        current = 'notes = """changed by user"""\n'
        self.assertEqual(config_rollback.merge(original.encode(), current.encode(), self.fixture.state), current.encode())

    def test_root_owned_catalog_and_url_cleanup_restores_exact_baseline(self) -> None:
        original = ('model = "gpt-6.1-sol"\n'
                    'openai_base_url = "http://127.0.0.1:4202/v1"\n'
                    'model_catalog_json = ' + json.dumps(str(self.fixture.state / "merged-models.json"))
                    + '\npersonality = "pragmatic"\n')
        self.fixture.config.write_text(original)
        result = self.fixture.run_install(FIXTURE_FAIL_SMOKE="1")
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertEqual(self.fixture.config.read_text(), original)

    def test_root_cleanup_merge_preserves_external_model_and_rejects_catalog_overlap(self) -> None:
        catalog = str(self.fixture.state / "merged-models.json")
        original = 'model_catalog_json = ' + json.dumps(catalog) + '\nmodel="gpt-6.1-sol"\n'
        self.fixture.config.write_text(original)
        result = self.late_config_edit('model="gpt-6-astra"\npersonality="friendly"\n')
        self.assertEqual(result.returncode, 7, result.stderr)
        data = tomllib.loads(self.fixture.config.read_text())
        self.assertEqual(data, {"model_catalog_json": catalog, "model": "gpt-6-astra", "personality": "friendly"})
        self.fixture.config.write_text(original)
        concurrent = 'model_catalog_json="/foreign/user-catalog.json"\nmodel="gpt-6.1-sol"\n'
        result = self.late_config_edit(concurrent)
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertIn("restoration needs attention", result.stderr)
        self.assertEqual(self.fixture.config.read_text(), concurrent)

    def test_legacy_loaded_and_unloaded_state_is_snapshotted_and_restored(self) -> None:
        legacy = "io.0xnatoshi.jev-router"
        plist = self.fixture.home / "Library/LaunchAgents" / f"{legacy}.plist"
        plist.parent.mkdir(parents=True)
        original = plistlib.dumps({"Label": legacy, "ProgramArguments": [sys.executable, "/fixture/server/jev_server.py"]})
        for running in (True, False):
            with self.subTest(running=running):
                plist.write_bytes(original)
                commands = []
                loaded = running
                real_run = subprocess.run
                def launchctl(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
                    nonlocal loaded
                    if command[0] != "launchctl":
                        return real_run(command, **kwargs)
                    commands.append(command)
                    if command[1] == "bootout":
                        loaded = False
                    code = 0 if loaded and command[-1].endswith(legacy) else 113
                    return subprocess.CompletedProcess(command, code if command[1] == "print" else 0)
                with mock.patch.dict(os.environ, self.fixture.env), mock.patch.object(transaction.sys, "platform", "darwin"), mock.patch.object(transaction.subprocess, "run", side_effect=launchctl):
                    backup = transaction.begin()
                    self.assertIn(legacy, json.loads((backup / "manifest.json").read_text())["services"])
                    plist.unlink()
                    transaction.restore(backup)
                self.assertEqual(plist.read_bytes(), original)
                starts = [call for call in commands if call[1] == "bootstrap" and call[-1] == str(plist)]
                self.assertEqual(len(starts), int(running))


class ServiceSerializationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = fixture_module.InstallTransactionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.repo = self.fixture.base / 'repo & <safe>'
        (self.repo / "server").mkdir(parents=True)
        for name in ("install-service.sh", "install_service.py", "install_services.py"):
            if (ROOT / "server" / name).exists():
                shutil.copy2(ROOT / "server" / name, self.repo / "server" / name)
        (self.repo / "server/healthcheck.py").write_text("raise SystemExit(0)\n")
        self.home = self.fixture.base / 'home & <safe>'
        (self.home / "Library/LaunchAgents").mkdir(parents=True)
        self.calls = self.fixture.base / "service-calls"
        self.python = self.fixture.base / 'python & <safe>'
        self.python.symlink_to(sys.executable)
        for name in ("pkill", "sleep"):
            self.fixture._script(self.fixture.commands / name,
                '#!/bin/sh\nprintf "%s\\n" "'+name+' $*" >> "$SERVICE_CALLS"\nexit 0\n')
        self.fixture._script(self.fixture.commands / "launchctl", '''#!/bin/sh
printf "%s\\n" "launchctl $*" >> "$SERVICE_CALLS"
case "$1" in
  print) [ -f "$SERVICE_CALLS.loaded" ] || exit 113; printf 'pid = 424242\\n' ;;
  bootstrap) touch "$SERVICE_CALLS.loaded" ;;
  bootout) rm -f "$SERVICE_CALLS.loaded" ;;
esac
''')
        self.fixture._script(self.fixture.commands / "lsof", '''#!/bin/sh
if [ -f "$SERVICE_CALLS.loaded" ]; then printf 'p424242\\n'; else exit 1; fi
''')

    def run_service(self, **overrides: str) -> subprocess.CompletedProcess:
        env = {**self.fixture.env, "HOME": str(self.home), "JEV_PYTHON": str(self.python),
               "JEV_ENV_FILE": str(self.home / ".jev&env"), "SERVICE_CALLS": str(self.calls), **overrides}
        return subprocess.run(["bash", str(self.repo / "server/install-service.sh")],
                              env=env, capture_output=True, text=True, timeout=10)

    def test_special_paths_round_trip_and_no_broad_process_kill(self) -> None:
        result = self.run_service()
        self.assertEqual(result.returncode, 0, result.stderr)
        plist = self.home / "Library/LaunchAgents/com.thibaultsaintjean.jev-router.plist"
        data = plistlib.loads(plist.read_bytes())
        self.assertEqual(data["ProgramArguments"], [str(self.python), str(self.repo.resolve() / "server/jev_server.py")])
        self.assertEqual(data["WorkingDirectory"], str(self.repo.resolve()))
        self.assertEqual(data["StandardOutPath"], str(self.home / "Library/Logs/jev-router.out.log"))
        self.assertEqual(plist.stat().st_mode & 0o777, 0o600)
        self.assertNotIn("pkill", self.calls.read_text())

    def test_invalid_xml_value_fails_before_service_stop(self) -> None:
        result = self.run_service(JEV_ENV_FILE="invalid\x01value")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.calls.exists(), "no launchctl before complete plist validation")
