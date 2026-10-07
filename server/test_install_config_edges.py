"""Rollback read failures and TOML boundaries preserve independent user state."""
import errno
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest import mock

import install_config_rollback as rollback
import install_transaction as transaction


BLOCK = ('# BEGIN codex-router-managed\n'
         'model_provider = "codex-router"\n'
         '# END codex-router-managed\n')
ENV_HEADER = '[plugins."codex-app-tools@openai-bundled".mcp_servers.codex_app.env]\n'
RUNTIME_BLOCK = ('# BEGIN jev-desktop-app-tools-runtime v1\n'
                 'CODEX_MCP_NODE_PATH = "/Applications/ChatGPT.app/Contents/Resources/cua_node/bin/node"\n'
                 '# END jev-desktop-app-tools-runtime v1\n')


class ConfigBoundaryTests(unittest.TestCase):
    def restored(self, original: str, current: str) -> str:
        value = rollback.merge(original.encode(), current.encode(), Path("/synthetic/state"))
        self.assertIsNotNone(value)
        return value.decode()

    def test_multiline_basic_string_preserves_user_notes_and_restores_root(self) -> None:
        original = 'notes = """\n[fake]\noriginal\n"""\n' + BLOCK + 'personality="pragmatic"\n'
        current = 'notes = """\n[fake]\n[other]\nuser edit\n"""\npersonality="friendly"\n'
        merged = self.restored(original, current)
        self.assertEqual(merged, current + BLOCK)
        self.assertEqual(tomllib.loads(merged), {**tomllib.loads(current), "model_provider": "codex-router"})

    def test_multiline_literal_string_does_not_create_table_context(self) -> None:
        original = "notes = '''\n[fake]\noriginal\n'''\n" + BLOCK
        current = "notes = '''\n[fake]\n[other]\nuser edit\n'''\n[features]\nfixture=true\n"
        merged = self.restored(original, current)
        expected = current.replace('[features]\n', BLOCK + '[features]\n')
        self.assertEqual(merged, expected)
        self.assertEqual(tomllib.loads(merged)['notes'], tomllib.loads(current)['notes'])
        self.assertEqual(tomllib.loads(merged)['model_provider'], "codex-router")

    def test_array_continuations_do_not_create_table_boundaries(self) -> None:
        original = 'matrix = [\n[1, 2],\n[3, 4],\n]\n' + BLOCK + '[features]\nfixture=true\n'
        current = 'matrix = [\n[5, 6],\n[7, 8],\n]\n[features]\nfixture=false\n'
        merged = self.restored(original, current)
        self.assertEqual(merged, current.replace('[features]\n', BLOCK + '[features]\n'))
        self.assertEqual(tomllib.loads(merged)['matrix'], [[5, 6], [7, 8]])
        self.assertEqual(tomllib.loads(merged)['model_provider'], "codex-router")

    def test_real_table_context_ignores_string_and_array_lines(self) -> None:
        original = '[features]\nnotes="""\n[fake]\n"""\n' + BLOCK + '[other]\nfixture=true\n'
        current = '[features]\nnotes="""\n[fake]\n[another]\n"""\nmatrix=[\n[1],\n]\n[other]\nfixture=false\n'
        merged = self.restored(original, current)
        self.assertEqual(merged, current.replace('[other]\n', BLOCK + '[other]\n'))
        data = tomllib.loads(merged)
        self.assertEqual(data['features']['notes'], tomllib.loads(current)['features']['notes'])
        self.assertEqual(data['features']['model_provider'], "codex-router")

    def test_escaped_quotes_and_four_quote_close_leave_real_table_visible(self) -> None:
        original = 'notes="""escaped \\"\n[fake]\ntext""""\n' + BLOCK
        current = 'notes="""changed \\"\n[fake]\ntext""""\n[features]\nfixture=true\n'
        merged = self.restored(original, current)
        self.assertEqual(merged, current.replace('[features]\n', BLOCK + '[features]\n'))
        self.assertEqual(tomllib.loads(merged)['notes'], tomllib.loads(current)['notes'])

    def test_table_identity_tolerates_comments_and_quoted_equivalent_name(self) -> None:
        original = '[features] # original\nfixture=true\n' + BLOCK + '[other]\nvalue=1\n'
        current = '["features"] # user comment\nfixture=false\n[other]\nvalue=2\n'
        self.assertEqual(self.restored(original, current), current.replace('[other]\n', BLOCK + '[other]\n'))

    def test_repeated_array_table_context_is_refused_without_guessing(self) -> None:
        original = '[[features]]\nfixture=true\n' + BLOCK
        current = '[[features]]\nfixture=false\n[[features]]\nfixture=true\n'
        with self.assertRaisesRegex(ValueError, "configuration.*conflict"):
            self.restored(original, current)

    def test_marker_comments_within_array_are_not_installer_owned(self) -> None:
        original = 'matrix=[\n# BEGIN codex-router-managed\n1,\n# END codex-router-managed\n]\n'
        current = 'matrix=[\n2,\n]\n'
        self.assertEqual(self.restored(original, current), current)


class ConfigReadFailureTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name).resolve()
        self.home = self.base / "home"
        self.codex = self.home / ".codex"
        self.state = self.codex / "codex-router"
        self.state.mkdir(parents=True)
        self.backup = self.codex / "backup"
        self.backup.mkdir(mode=0o700)
        self.config = self.codex / "config.toml"
        self.config.write_text('personality="current"\n')
        (self.backup / "config.toml").write_text('personality="original"\n')
        self.env = {"HOME": str(self.home), "CODEX_HOME": str(self.codex),
                    "MODEL_ROUTER_STATE_DIR": str(self.state)}

    def assert_conflict_record(self, captured: bytes | None) -> None:
        result = self.backup / "result.json"
        self.assertEqual(json.loads(result.read_text())["status"], "configuration_conflict")
        self.assertEqual(result.stat().st_mode & 0o777, 0o600)
        snapshot = self.backup / "config-current.toml"
        if captured is None:
            self.assertFalse(snapshot.exists())
        else:
            self.assertEqual(snapshot.read_bytes(), captured)
            self.assertEqual(snapshot.stat().st_mode & 0o777, 0o600)

    def test_linked_current_is_not_followed_and_becomes_actionable_conflict(self) -> None:
        target = self.base / "private-target"
        target.write_text('private="synthetic-unrelated-content"\n')
        contents = target.read_bytes()
        self.config.unlink()
        self.config.symlink_to(target)
        with self.assertRaisesRegex(ValueError, "configuration.*conflict") as error:
            rollback.restore(self.config, self.backup, self.state)
        self.assertNotIn("synthetic-unrelated-content", str(error.exception))
        self.assertTrue(self.config.is_symlink())
        self.assertEqual(target.read_bytes(), contents)
        self.assert_conflict_record(None)

    def test_unreadable_original_preserves_safe_current_snapshot(self) -> None:
        original_read = rollback.read
        original = self.backup / "config.toml"
        captured = self.config.read_bytes()
        def refuse(path: Path) -> bytes | None:
            if path == original:
                raise PermissionError(errno.EACCES, "synthetic-private-original")
            return original_read(path)
        with mock.patch.object(rollback, "read", side_effect=refuse):
            with self.assertRaisesRegex(ValueError, "configuration.*conflict") as error:
                rollback.restore(self.config, self.backup, self.state)
        self.assertNotIn("synthetic-private-original", str(error.exception))
        self.assertEqual(self.config.read_bytes(), captured)
        self.assert_conflict_record(captured)

    def test_conflict_handler_read_failure_does_not_replace_conflict_with_oserror(self) -> None:
        (self.backup / "config.toml").write_text(BLOCK)
        concurrent = BLOCK.replace('"codex-router"', '"foreign"').encode()
        self.config.write_bytes(concurrent)
        original_read = rollback.read
        reads = 0
        def refuse_second_read(path: Path) -> bytes | None:
            nonlocal reads
            if path == self.config:
                reads += 1
                if reads > 1:
                    raise PermissionError(errno.EACCES, "synthetic-private-current")
            return original_read(path)
        with mock.patch.object(rollback, "read", side_effect=refuse_second_read):
            with self.assertRaisesRegex(ValueError, "configuration.*conflict") as error:
                rollback.restore(self.config, self.backup, self.state)
        self.assertNotIn("synthetic-private-current", str(error.exception))
        self.assertEqual(self.config.read_bytes(), concurrent)
        self.assert_conflict_record(None)

    def recovery_fixture(self) -> tuple[Path, bytes, list[list[str]]]:
        legacy = "io.0xnatoshi.jev-router"
        plist = self.home / "Library/LaunchAgents" / f"{legacy}.plist"
        plist.parent.mkdir(parents=True)
        original = plistlib.dumps({"Label": legacy, "ProgramArguments": [sys.executable, "/fixture/old/server/jev_server.py"]})
        (self.backup / f"{legacy}.plist").write_bytes(original)
        (self.backup / "state").mkdir()
        (self.backup / "state/prior").write_text("prior state")
        (self.state / "failed").write_text("failed state")
        (self.backup / "jev.config.toml").write_text('model="jev/auto"\n')
        (self.codex / "jev.config.toml").write_text('model="failed-install"\n')
        manifest = {"codex_home": str(self.codex), "state": str(self.state),
                    "state_present": True, "profile_present": True,
                    "services": {legacy: {"present": True, "running": True, "disabled": False}}}
        (self.backup / "manifest.json").write_text(json.dumps(manifest))
        calls: list[list[str]] = []
        return plist, original, calls

    def assert_independent_recovery(self, plist: Path, original: bytes) -> None:
        self.assertEqual(plist.read_bytes(), original)
        self.assertEqual((self.state / "prior").read_text(), "prior state")
        self.assertFalse((self.state / "failed").exists())
        self.assertEqual((self.backup / "failed-state/failed").read_text(), "failed state")
        self.assertEqual((self.codex / "jev.config.toml").read_text(), 'model="jev/auto"\n')

    def test_linked_current_conflict_allows_independent_transaction_recovery(self) -> None:
        plist, original, calls = self.recovery_fixture()
        target = self.base / "private-target"
        target.write_text('personality="unrelated"\n')
        self.config.unlink()
        self.config.symlink_to(target)
        label = plist.stem
        def service(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            self.assertEqual(command[0], "launchctl")
            self.assertIn(command[1], {"print", "enable", "bootstrap"})
            self.assertEqual(command[-1], str(plist) if command[1] == "bootstrap" else f"gui/{os.getuid()}/{label}")
            calls.append(command)
            return subprocess.CompletedProcess(command, 1 if command[1] == "print" else 0)
        with mock.patch.dict(os.environ, self.env), mock.patch.object(transaction.sys, "platform", "darwin"), mock.patch.object(transaction.subprocess, "run", side_effect=service):
            with self.assertRaisesRegex(ValueError, "configuration.*conflict"):
                transaction.restore(self.backup)
        self.assertTrue(self.config.is_symlink())
        self.assertEqual(target.read_text(), 'personality="unrelated"\n')
        self.assert_independent_recovery(plist, original)
        self.assertEqual([call[1] for call in calls], ["print", "enable", "bootstrap"])
        self.assert_conflict_record(None)

    def test_read_and_conflict_record_failure_still_allows_independent_recovery(self) -> None:
        plist, original, calls = self.recovery_fixture()
        current = self.config.read_bytes()
        original_read, original_write = rollback.read, rollback.private_write
        def refuse_read(path: Path) -> bytes | None:
            if path == self.config:
                raise PermissionError(errno.EACCES, "synthetic-private-current")
            return original_read(path)
        def refuse_result(path: Path, contents: bytes) -> None:
            if path == self.backup / "result.json":
                raise PermissionError(errno.EACCES, "synthetic-private-result")
            original_write(path, contents)
        def service(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            self.assertEqual(command[0], "launchctl")
            self.assertIn(command[1], {"print", "enable", "bootstrap"})
            self.assertEqual(command[-1], str(plist) if command[1] == "bootstrap" else f"gui/{os.getuid()}/{plist.stem}")
            calls.append(command)
            return subprocess.CompletedProcess(command, 1 if command[1] == "print" else 0)
        with mock.patch.dict(os.environ, self.env), mock.patch.object(transaction.sys, "platform", "darwin"), mock.patch.object(transaction.subprocess, "run", side_effect=service), mock.patch.object(rollback, "read", side_effect=refuse_read), mock.patch.object(rollback, "private_write", side_effect=refuse_result):
            with self.assertRaisesRegex(ValueError, "configuration.*conflict") as error:
                transaction.restore(self.backup)
        self.assertNotIn("synthetic-private", str(error.exception))
        self.assertEqual(self.config.read_bytes(), current)
        self.assert_independent_recovery(plist, original)
        self.assertEqual([call[1] for call in calls], ["print", "enable", "bootstrap"])
        self.assertFalse((self.backup / "result.json").exists())


class DesktopScaffoldOwnershipTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.state = Path(directory.name)
        desktop = self.state / "desktop"
        desktop.mkdir()
        provider = {"name": "Jev", "base_url": "http://127.0.0.1:4202/v1",
                    "wire_api": "responses", "requires_openai_auth": False,
                    "auth": {"command": "/fixture/node",
                             "args": ["/fixture/src/caller-key-auth-command.mjs", "/fixture/caller-secret"]}}
        (desktop / "manifest.json").write_text(json.dumps({
            "provider": provider, "appExecutable": "/Applications/ChatGPT.app/Contents/MacOS/ChatGPT"}))

    def restored(self, original: str, current: str, planned: str | None = None) -> str:
        value = rollback.merge(original.encode(), current.encode(), self.state,
                               None if planned is None else planned.encode())
        self.assertIsNotNone(value)
        return value.decode()

    def test_multiline_user_header_is_preserved_without_owned_desktop_block(self) -> None:
        original = 'notes="old"\n'
        current = 'notes="""\n' + ENV_HEADER + '[fake]\nuser edit\n"""\n'
        self.assertFalse(rollback.blocks(current))
        self.assertEqual(self.restored(original, current), current)

    def test_new_user_empty_env_table_is_preserved_without_owned_desktop_block(self) -> None:
        original = 'notes="old"\n'
        current = original + ENV_HEADER
        self.assertFalse(rollback.blocks(current))
        self.assertEqual(self.restored(original, current), current)

    def test_runtime_leaf_removal_preserves_header_without_creation_metadata(self) -> None:
        import install_desktop
        original = 'notes="old"\n'
        updated = 'notes="user edit"\n'
        node = Path("/Applications/ChatGPT.app/Contents/Resources/cua_node/bin/node")
        expected = updated + ENV_HEADER
        for writer_input in (updated, expected):
            with self.subTest(user_created_header=writer_input == expected):
                installed = install_desktop.app_tools_config(writer_input, node)
                self.assertEqual(installed, expected + RUNTIME_BLOCK)
                self.assertEqual(self.restored(original, installed), expected)

    def test_original_multiline_header_is_not_a_structural_owned_table(self) -> None:
        original = 'notes="""\n' + ENV_HEADER + '[fake]\noriginal\n"""\n'
        updated = original.replace('original', 'user edit')
        installed = updated + ENV_HEADER + RUNTIME_BLOCK
        self.assertEqual(self.restored(original, installed), updated + ENV_HEADER)
        self.assertEqual(tomllib.loads(updated)['notes'], tomllib.loads(self.restored(original, installed))['notes'])

    def test_original_quoted_env_table_is_preserved_after_runtime_removal(self) -> None:
        quoted_header = "[plugins.'codex-app-tools@openai-bundled'.mcp_servers.codex_app.env]\n"
        original = 'notes="old"\n' + quoted_header
        updated = 'notes="user edit"\n' + ENV_HEADER
        self.assertEqual(self.restored(original, updated + RUNTIME_BLOCK), updated)

    def test_foreign_comments_and_entries_survive_runtime_removal(self) -> None:
        original = 'notes="old"\n'
        for outside in ('# user comment\n', 'USER_SETTING="keep"\n', '\n# user comment\n\n'):
            with self.subTest(outside=outside):
                updated = 'notes="user edit"\n' + ENV_HEADER + outside
                self.assertEqual(self.restored(original, updated + RUNTIME_BLOCK), updated)

    def test_user_inline_header_comment_survives_runtime_removal(self) -> None:
        original = 'notes="old"\n'
        updated = original + ENV_HEADER.rstrip('\n') + ' # user context\n'
        self.assertEqual(self.restored(original, updated + RUNTIME_BLOCK), updated)

    def test_recovery_provider_removal_does_not_own_runtime_scaffold(self) -> None:
        original = 'notes="old"\n'
        updated = 'notes="user edit"\n' + ENV_HEADER
        providers = rollback.desktop_expected(self.state)[rollback.DESKTOP_BLOCKS[0]]
        self.assertEqual(self.restored(original, updated + providers), updated)

    def test_exact_runtime_bytes_inside_foreign_table_are_a_conflict(self) -> None:
        current = 'notes="old"\n[preferences]\n' + RUNTIME_BLOCK
        with self.assertRaisesRegex(ValueError, "configuration.*conflict"):
            self.restored('notes="old"\n', current)

    def test_unprojected_user_formatting_is_preserved_when_restoring_owned_block(self) -> None:
        original = '\n' + BLOCK + '\nnotes="old"\n\n'
        current = 'notes="old"\n'
        self.assertEqual(self.restored(original, current), current + BLOCK)

    def test_exact_read_only_cleanup_projection_restores_original_owned_layout(self) -> None:
        original = '\n' + BLOCK + '\nnotes="old"\n\n'
        planned = 'notes="old"\n'
        self.assertEqual(self.restored(original, planned, planned), original)


if __name__ == "__main__":
    unittest.main()
