"""Desktop installation qualifies contracts and owns only its recovery integration."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import tomllib
import unittest
from unittest.mock import patch

import install_desktop
from test_desktop_provider_registry import provider


QUALIFIED = {"expectedAppSha256": "a" * 64, "expectedNativeSha256": "b" * 64,
             "contractVersion": 1, "nativeVersion": "codex-cli 0.160.0", "contractDigest": "c" * 64}


class DesktopInstallationTests(unittest.TestCase):
    def test_new_signed_build_uses_contract_probe_without_static_allowlist(self) -> None:
        with patch.object(install_desktop.shutil, "which", return_value="/runtime/node"), \
                patch.object(install_desktop.subprocess, "run", return_value=subprocess.CompletedProcess(
                    [], 0, stdout=json.dumps(QUALIFIED), stderr="")) as probe:
            self.assertEqual(install_desktop.verify_app(Path("/new/ChatGPT.app")), QUALIFIED)
        arguments = probe.call_args.args[0]
        self.assertEqual(arguments[0], "/runtime/node")
        self.assertTrue(arguments[1].endswith("/router/src/desktop-compatibility.mjs"))
        self.assertEqual(arguments[-2:], ["--app", "/new/ChatGPT.app"])
        self.assertEqual(probe.call_args.kwargs["timeout"], 90)

    def test_invalid_or_failed_probe_is_rejected_without_exposing_process_output(self) -> None:
        documents = [{**QUALIFIED, "expectedNativeSha256": "invalid"},
                     {**QUALIFIED, "contractVersion": True}, {**QUALIFIED, "nativeVersion": ""}]
        with patch.object(install_desktop.shutil, "which", return_value="/runtime/node"):
            for document in documents:
                with patch.object(install_desktop.subprocess, "run", return_value=subprocess.CompletedProcess(
                        [], 0, stdout=json.dumps(document), stderr="synthetic-sensitive-output")):
                    with self.assertRaises(ValueError) as error:
                        install_desktop.verify_app(Path("/app"))
                    self.assertNotIn("synthetic-sensitive-output", str(error.exception))
            with patch.object(install_desktop.subprocess, "run", return_value=subprocess.CompletedProcess(
                    [], 1, stdout="", stderr="synthetic-sensitive-output")):
                with self.assertRaisesRegex(ValueError, "compatibility"):
                    install_desktop.verify_app(Path("/app"))

    @unittest.skipUnless(os.environ.get("JEV_DESKTOP_TEST_APP"), "Requires separately acquired signed Desktop")
    def test_acquired_desktop_passes_real_contract_and_signature_checks(self) -> None:
        result = install_desktop.verify_app(Path(os.environ["JEV_DESKTOP_TEST_APP"]))
        self.assertEqual(result["contractVersion"], 1)

    def test_install_is_idempotent_preserves_native_settings_and_private_routes(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            codex = root / "codex"
            codex.mkdir()
            config = codex / "config.toml"
            original = b'model = "gpt-6.1-sol"\n[preferences]\nkeep = true\n'
            config.write_bytes(original)
            config.chmod(0o600)
            backup = codex / "config.toml.backup.protected"
            backup.write_bytes(b"protected backup")
            profile = provider()
            (codex / "jev.config.toml").write_text(
                '[model_providers.jev-router]\nname="Jev"\nbase_url="http://127.0.0.1:4202/v1"\n'
                'wire_api="responses"\nrequires_openai_auth=false\n[model_providers.jev-router.auth]\n'
                'command="/runtime/node"\nargs=["/source/src/caller-key-auth-command.mjs","/private/caller-secret"]\n')
            state = root / "state"
            state.mkdir(mode=0o700)
            with patch.object(install_desktop, "verify_app", return_value=QUALIFIED), \
                    patch.object(install_desktop.desktop_session, "install") as session:
                for _ in range(2):
                    install_desktop.install(codex, state, root / "ChatGPT.app", Path("/source"), Path("/bin/node"))
                    current = {p.name: p.read_bytes() for p in (state / "desktop").iterdir()}
                    if _ == 0:
                        first = current
                        config_first = config.read_bytes()
                self.assertEqual(first, current)
                self.assertEqual(config_first, config.read_bytes())
                self.assertEqual(session.call_count, 2)
                manifest = json.loads((state / "desktop/manifest.json").read_text())
                routes = Path(manifest["routeStateDirectory"])
                self.assertFalse(routes.exists())
                routes.mkdir(mode=0o700)
                record = routes / "fixture.json"
                record.write_bytes(b"latest route revision")
                install_desktop.install(codex, state, root / "ChatGPT.app", Path("/source"), Path("/bin/node"))
                self.assertEqual(record.read_bytes(), b"latest route revision")
                for overlapping in (codex, routes, routes / "child"):
                    with self.assertRaisesRegex(ValueError, "separate"):
                        install_desktop.install(codex, overlapping, root / "app", Path("/source"), Path("/bin/node"))
            self.assertTrue(config.read_bytes().startswith(original))
            self.assertEqual(backup.read_bytes(), b"protected backup")
            self.assertNotIn("model_provider", tomllib.loads(config.read_text()))
            self.assertEqual(manifest["provider"], profile)
            self.assertEqual(manifest["codexHome"], str(codex.resolve()))
            self.assertEqual(manifest["bridgeLauncher"], str(state / "desktop/jev-codex"))
            wrapper = Path(manifest["bridgeLauncher"])
            self.assertIn('"$@"', wrapper.read_text())
            self.assertIn("JEV_DESKTOP_CONFIG=", wrapper.read_text())
            self.assertEqual(wrapper.stat().st_mode & 0o777, 0o700)
            self.assertEqual((state / "desktop/manifest.json").stat().st_mode & 0o777, 0o600)

    def test_unknown_app_is_rejected_before_any_install_write(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            with patch.object(install_desktop, "verify_app", side_effect=ValueError("Unverified Desktop compatibility")):
                with self.assertRaisesRegex(ValueError, "Unverified"):
                    install_desktop.install(root, root / "state", root / "app", root, Path("/bin/node"))
            self.assertFalse((root / "state").exists())

    def test_check_only_verifies_app_without_installing(self) -> None:
        with patch.object(install_desktop, "verify_app", return_value=QUALIFIED) as verify, \
                patch.object(install_desktop, "install") as install, \
                patch("sys.argv", ["install_desktop.py", "--check"]):
            install_desktop.main()
        verify.assert_called_once_with(Path("/Applications/ChatGPT.app"))
        install.assert_not_called()

    def test_unsafe_existing_destination_is_rejected_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "manifest.json"
            path.write_bytes(b"original")
            path.chmod(0o666)
            with self.assertRaises(ValueError):
                install_desktop.private_write(path, b"replacement", 0o600)
            self.assertEqual(path.read_bytes(), b"original")

    def test_symlink_destination_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            destination = root / "manifest.json"
            target = root / "protected"
            target.write_bytes(b"unchanged")
            destination.symlink_to(target)
            with self.assertRaises(ValueError):
                install_desktop.private_write(destination, b"replacement", 0o600)
            self.assertEqual(target.read_bytes(), b"unchanged")
