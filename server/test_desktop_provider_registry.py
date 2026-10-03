"""Durable recovery providers preserve native defaults and unrelated TOML."""
from pathlib import Path
import tempfile
import tomllib
import unittest

import desktop_provider_registry as registry


def provider(command: str = "/runtime/node") -> dict[str, object]:
    return {"name": "Jev", "base_url": "http://127.0.0.1:4202/v1",
            "wire_api": "responses", "requires_openai_auth": False,
            "auth": {"command": command, "args": ["/source/src/caller-key-auth-command.mjs", "/private/caller-secret"]}}


class RegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "config.toml"
        self.original = b'# Keep my settings\nmodel = "gpt-6.1-sol"\n[preferences]\nkeep = true\n'
        self.path.write_bytes(self.original)
        self.path.chmod(0o600)

    def test_recovery_registration_preserves_defaults_bytes_and_refreshes_auth(self) -> None:
        registry.install(self.path, provider())
        first = self.path.read_bytes()
        self.assertTrue(first.startswith(self.original))
        data = tomllib.loads(first.decode())
        self.assertEqual(data["model"], "gpt-6.1-sol")
        self.assertNotIn("model_provider", data)
        self.assertEqual(set(data["model_providers"]), {"jev-router-auto", "jev-router-manual"})
        for value in data["model_providers"].values():
            self.assertEqual(value["http_headers"], {"x-jev-desktop-recovery": "required"})
        registry.install(self.path, provider())
        self.assertEqual(first, self.path.read_bytes())
        registry.install(self.path, provider("/new/node"))
        self.assertTrue(self.path.read_bytes().startswith(self.original))
        self.assertIn('"/new/node"', self.path.read_text())
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_foreign_or_tampered_managed_provider_is_rejected_without_write(self) -> None:
        for content in (self.original + b'\n[model_providers.jev-router-auto]\nname="foreign"\n',
                        self.original + b'\n["model_providers"."jev-router-manual"]\nname="foreign"\n'):
            self.path.write_bytes(content)
            with self.assertRaises(ValueError):
                registry.install(self.path, provider())
            self.assertEqual(self.path.read_bytes(), content)
        self.path.write_bytes(self.original)
        registry.install(self.path, provider())
        content = self.path.read_bytes().replace(b'requires_openai_auth = false', b'requires_openai_auth = true')
        self.path.write_bytes(content)
        with self.assertRaises(ValueError):
            registry.install(self.path, provider())
        self.assertEqual(self.path.read_bytes(), content)

    def test_actual_isolated_profile_capabilities_and_auth_timing_are_preserved(self) -> None:
        value = {**provider(), "supports_standalone_web_search": True}
        value["auth"] = {**value["auth"], "timeout_ms": 5000, "refresh_interval_ms": 0}
        registry.install(self.path, value)
        parsed = tomllib.loads(self.path.read_text())
        for entry in parsed["model_providers"].values():
            self.assertEqual(entry["auth"], value["auth"])
            self.assertTrue(entry["supports_standalone_web_search"])

    def test_markers_inside_multiline_user_text_do_not_claim_ownership(self) -> None:
        text = 'description = """\n' + registry.render(provider()) + '"""\n'
        self.path.write_text(text)
        with self.assertRaises(ValueError):
            registry.install(self.path, provider())
        self.assertEqual(self.path.read_text(), text)

    def test_unsafe_file_and_inline_secrets_are_rejected(self) -> None:
        self.path.chmod(0o666)
        with self.assertRaises(ValueError):
            registry.install(self.path, provider())
        self.path.chmod(0o600)
        original = self.path.read_bytes()
        with self.assertRaises(ValueError):
            registry.install(self.path, {**provider(), "api_key": "synthetic-secret"})
        self.assertEqual(original, self.path.read_bytes())
        link = self.path.with_name("link")
        link.symlink_to(self.path)
        with self.assertRaises(ValueError):
            registry.install(link, provider())

    def test_missing_final_newline_and_unrelated_tail_survive_reinstall(self) -> None:
        self.path.write_bytes(b'model = "gpt-6.1-sol"')
        registry.install(self.path, provider())
        self.path.write_bytes(self.path.read_bytes() + b'\n[projects."/mine"]\ntrust_level="trusted"\n')
        before = self.path.read_bytes()
        registry.install(self.path, provider())
        self.assertEqual(before, self.path.read_bytes())
