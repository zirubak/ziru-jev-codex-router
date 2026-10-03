"""GUI session registration survives app replacement without taking foreign state."""
import json
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import desktop_session as session


class SessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.desktop = self.home / "state/desktop"
        self.desktop.mkdir(parents=True, mode=0o700)
        self.wrapper = self.desktop / "jev-codex"
        self.wrapper.write_text("#!/bin/sh\nexit 0\n")
        self.wrapper.chmod(0o700)
        self.manifest = self.desktop / "manifest.json"
        self.manifest.write_text(json.dumps({"version": 1, "bridgeLauncher": str(self.wrapper),
            "session": {"label": session.LABEL, "python": "/usr/bin/python3", "script": "/source/server/desktop_session.py"}}))
        self.manifest.chmod(0o600)
        self.environment = ""
        self.loaded = False
        self.commands = []

    def launchctl(self, arguments: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        self.commands.append(arguments)
        command = arguments[4:] if arguments[1] == "asuser" else arguments[1:]
        result = ""
        code = 0
        if command[0] == "getenv":
            result = self.environment + "\n"
        elif command[0] == "setenv":
            self.environment = command[2]
        elif command[0] == "unsetenv":
            self.environment = ""
        elif command[0] == "print":
            code = 0 if self.loaded else 113
        elif command[0] == "bootstrap":
            self.loaded = True
        elif command[0] == "bootout":
            self.loaded = False
        return subprocess.CompletedProcess(arguments, code, stdout=result, stderr="")

    def test_activate_is_persistent_idempotent_and_deactivate_is_owned(self) -> None:
        with patch.object(session.subprocess, "run", side_effect=self.launchctl):
            session.install(self.manifest, self.home)
            session.install(self.manifest, self.home)
            self.assertEqual(self.environment, str(self.wrapper))
            self.assertTrue(session.status(self.manifest)["active"])
            plist = self.home / "Library/LaunchAgents" / f"{session.LABEL}.plist"
            data = plistlib.loads(plist.read_bytes())
            self.assertEqual(data["ProgramArguments"][-2:], ["activate", str(self.manifest)])
            self.assertTrue(data["RunAtLoad"])
            self.assertEqual(plist.stat().st_mode & 0o777, 0o600)
            session.deactivate(self.manifest, self.home)
            session.deactivate(self.manifest, self.home)
            self.assertEqual(self.environment, "")
            self.assertFalse(plist.exists())
            self.assertFalse(self.loaded)
        self.assertFalse(any("kill" in arg or "ChatGPT" in arg for args in self.commands for arg in args))

    def test_foreign_environment_and_service_are_preserved(self) -> None:
        with patch.object(session.subprocess, "run", side_effect=self.launchctl):
            self.environment = "/foreign/codex"
            with self.assertRaisesRegex(ValueError, "CODEX_CLI_PATH"):
                session.install(self.manifest, self.home)
            self.assertEqual(self.environment, "/foreign/codex")
            with self.assertRaises(ValueError):
                session.deactivate(self.manifest, self.home)
            self.environment = ""
            plist = self.home / "Library/LaunchAgents" / f"{session.LABEL}.plist"
            plist.parent.mkdir(parents=True)
            plist.write_bytes(plistlib.dumps({"Label": session.LABEL, "ProgramArguments": ["/foreign/run"]}))
            plist.chmod(0o600)
            before = plist.read_bytes()
            with self.assertRaisesRegex(ValueError, "foreign"):
                session.install(self.manifest, self.home)
            self.assertEqual(plist.read_bytes(), before)
            self.assertEqual(self.environment, "")

    def test_foreign_environment_whitespace_is_preserved_exactly(self) -> None:
        with patch.object(session.subprocess, "run", side_effect=self.launchctl):
            for value in (" ", " /foreign/codex ", "/foreign/codex\n"):
                with self.subTest(value=value):
                    self.environment = value
                    self.assertEqual(session.environment(), value)
                    with self.assertRaisesRegex(ValueError, "foreign"):
                        session.activate(self.manifest)
                    self.assertEqual(self.environment, value)

    def test_concurrent_owned_activation_is_idempotent(self) -> None:
        with patch.object(session, "environment", side_effect=["", str(self.wrapper)]), \
                patch.object(session, "run") as run:
            session.activate(self.manifest)
            run.assert_not_called()
        with patch.object(session, "environment", side_effect=["", "/foreign/concurrent"]), \
                patch.object(session, "run") as run:
            with self.assertRaisesRegex(ValueError, "foreign"):
                session.activate(self.manifest)
            run.assert_not_called()

    def test_rollback_restores_only_owned_environment_and_service(self) -> None:
        with patch.object(session.subprocess, "run", side_effect=self.launchctl):
            previous = session.snapshot(self.home, self.desktop.parent)
            session.install(self.manifest, self.home)
            session.prepare_restore(previous, self.home, None)
            session.finish_restore(previous, self.home, None)
            self.assertEqual(self.environment, "")
            self.assertFalse(self.loaded)
            self.assertFalse((self.home / "Library/LaunchAgents" / f"{session.LABEL}.plist").exists())

    def test_snapshot_rejects_loaded_registration_with_missing_environment(self) -> None:
        with patch.object(session.subprocess, "run", side_effect=self.launchctl):
            session.install(self.manifest, self.home)
            self.environment = ""
            with self.assertRaisesRegex(ValueError, "inactive"):
                session.snapshot(self.home, self.desktop.parent)
            self.assertEqual(self.environment, "")
            self.assertTrue(self.loaded)

    def test_reinstall_rollback_restores_prior_owned_registration(self) -> None:
        with patch.object(session.subprocess, "run", side_effect=self.launchctl):
            session.install(self.manifest, self.home)
            previous = session.snapshot(self.home, self.desktop.parent)
            plist = self.home / "Library/LaunchAgents" / f"{session.LABEL}.plist"
            original = plist.read_bytes()
            data = json.loads(self.manifest.read_text())
            data["session"]["script"] = "/new-source/server/desktop_session.py"
            self.manifest.write_text(json.dumps(data))
            session.install(self.manifest, self.home)
            self.assertNotEqual(original, plist.read_bytes())
            session.prepare_restore(previous, self.home, original)
            self.assertFalse(self.loaded)
            self.assertEqual(self.environment, str(self.wrapper))
            session.finish_restore(previous, self.home, original)
            self.assertTrue(self.loaded)
            self.assertEqual(plist.read_bytes(), original)

    def test_rollback_refuses_concurrent_foreign_environment_and_service(self) -> None:
        with patch.object(session.subprocess, "run", side_effect=self.launchctl):
            previous = session.snapshot(self.home, self.desktop.parent)
            session.install(self.manifest, self.home)
            self.environment = "/foreign/new-value"
            with self.assertRaisesRegex(ValueError, "concurrently"):
                session.prepare_restore(previous, self.home, None)
            self.assertEqual(self.environment, "/foreign/new-value")
            self.environment = str(self.wrapper)
            plist = self.home / "Library/LaunchAgents" / f"{session.LABEL}.plist"
            foreign = plistlib.dumps({"Label": session.LABEL, "ProgramArguments": ["/foreign/new-agent"]})
            plist.write_bytes(foreign)
            with self.assertRaisesRegex(ValueError, "foreign"):
                session.prepare_restore(previous, self.home, None)
            self.assertEqual(plist.read_bytes(), foreign)
            self.assertEqual(self.environment, str(self.wrapper))

    def test_readback_failure_and_unsafe_manifest_fail_closed(self) -> None:
        with patch.object(session.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, stdout="", stderr="")):
            with self.assertRaisesRegex(RuntimeError, "readback"):
                session.activate(self.manifest)
        self.manifest.chmod(0o644)
        with self.assertRaises(ValueError):
            session.activate(self.manifest)
