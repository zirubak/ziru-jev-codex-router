"""The optional launcher is private, reversible, and never changes Codex defaults."""
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import install_desktop


class DesktopInstallationTests(unittest.TestCase):
    def test_install_is_idempotent_and_preserves_base_and_protected_backup(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            codex = root / "codex"
            codex.mkdir()
            config = codex / "config.toml"
            config.write_text('model = "gpt-6.1-sol"\n[preferences]\nkeep = true\n')
            backup = codex / "config.toml.backup.20261002-130745"
            backup.write_bytes(b"protected backup")
            (codex / "jev.config.toml").write_text(
                '[model_providers.jev-router]\nname="Jev"\n'
                'base_url="http://127.0.0.1:4202/v1"\n'
                'wire_api="responses"\nrequires_openai_auth=false\n')
            state = root / "state"
            state.mkdir(mode=0o700)
            app = root / "ChatGPT.app"
            original = (config.read_bytes(), backup.read_bytes())
            with patch.object(install_desktop, "verify_app", return_value=install_desktop.SUPPORTED_HASHES):
                install_desktop.install(codex, state, app, Path("/source"), Path("/bin/node"))
                first = {p.name: p.read_bytes() for p in (state / "desktop").iterdir()}
                install_desktop.install(codex, state, app, Path("/source"), Path("/bin/node"))
            self.assertEqual(first, {p.name: p.read_bytes() for p in (state / "desktop").iterdir()})
            self.assertEqual(original, (config.read_bytes(), backup.read_bytes()))
            manifest = json.loads((state / "desktop/manifest.json").read_text())
            self.assertTrue(manifest["nativeBinary"].endswith("CodexCLI.app/Contents/MacOS/codex"))
            self.assertEqual(Path(manifest["routeStateDirectory"]), codex.resolve() / "jev-desktop-thread-routes")
            self.assertFalse(Path(manifest["routeStateDirectory"]).exists(), "The bridge owns route-state initialization")
            self.assertFalse(Path(manifest["routeStateDirectory"]).is_relative_to(state))
            routes = Path(manifest["routeStateDirectory"])
            routes.mkdir(mode=0o700)
            record = routes / "fixture.json"
            record.write_bytes(b"latest route revision")
            with patch.object(install_desktop, "verify_app", return_value=install_desktop.SUPPORTED_HASHES):
                install_desktop.install(codex, state, app, Path("/source"), Path("/bin/node"))
                self.assertEqual(record.read_bytes(), b"latest route revision")
                for overlapping in (codex, routes, routes / "child"):
                    with self.assertRaisesRegex(ValueError, "separate"):
                        install_desktop.install(codex, overlapping, app, Path("/source"), Path("/bin/node"))
                (codex / "jev-install-backups").symlink_to(routes, target_is_directory=True)
                with self.assertRaisesRegex(ValueError, "separate"):
                    install_desktop.install(codex, state, app, Path("/source"), Path("/bin/node"))
            self.assertNotIn("model_catalog_json", manifest)
            self.assertEqual(manifest["provider"]["base_url"], "http://127.0.0.1:4202/v1")
            self.assertEqual((state / "desktop/manifest.json").stat().st_mode & 0o777, 0o600)
            self.assertEqual((state / "desktop/Jev Codex.command").stat().st_mode & 0o777, 0o700)

    def test_native_payload_change_is_rejected_when_wrapper_is_unchanged(self) -> None:
        import hashlib
        with tempfile.TemporaryDirectory() as name:
            app = Path(name)
            files = {"expectedAppSha256": app / "Contents/Resources/app.asar",
                     "expectedNativeSha256": app / "Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex"}
            wrapper = app / "Contents/Resources/codex-cli/bin/codex"
            wrapper.parent.mkdir(parents=True)
            wrapper.write_bytes(b"unchanged trampoline")
            for file in files.values():
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(b"verified payload")
            hashes = {key: hashlib.sha256(file.read_bytes()).hexdigest() for key, file in files.items()}
            with patch.object(install_desktop, "SUPPORTED_HASHES", hashes), patch.object(install_desktop.subprocess, "run"):
                self.assertEqual(install_desktop.verify_app(app), hashes)
                files["expectedNativeSha256"].write_bytes(b"updated payload")
                with self.assertRaisesRegex(ValueError, "Unverified"):
                    install_desktop.verify_app(app)
            self.assertEqual(wrapper.read_bytes(), b"unchanged trampoline")

    def test_unknown_app_is_rejected_before_any_install_write(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            with patch.object(install_desktop, "verify_app", side_effect=ValueError("Unverified Desktop build")):
                with self.assertRaisesRegex(ValueError, "Unverified"):
                    install_desktop.install(root, root / "state", root / "app", root, Path("/bin/node"))
            self.assertFalse((root / "state").exists())

    def test_check_only_verifies_app_without_installing(self) -> None:
        with patch.object(install_desktop, "verify_app", return_value=install_desktop.SUPPORTED_HASHES) as verify, \
                patch.object(install_desktop, "install") as install, \
                patch("sys.argv", ["install_desktop.py", "--check"]):
            install_desktop.main()
        verify.assert_called_once_with(Path("/Applications/ChatGPT.app"))
        install.assert_not_called()

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
