"""Reinstall and rollback must observe launchd removal before replacing state."""
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest import mock

import desktop_session
import install_services
import test_desktop_session
import test_install_rollback


class ShutdownIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = test_install_rollback.RollbackSafetyTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def delayed_service(self) -> tuple[Path, bytes, Path, dict, Path]:
        result = self.fixture.service_fixture("/fixture/old/server/jev_server.py",
                                              label=install_services.JEV_LABEL)
        command = self.fixture.fixture.commands / "launchctl"
        script = command.read_text().replace(
            'if verb=="print":\n',
            'if verb=="print":\n'
            ' pending=data.get("stopping",{})\n'
            ' if label in pending:\n'
            '  pending[label]-=1\n'
            '  if pending[label]==0:\n'
            '   data["loaded"].pop(label,None)\n'
            '   del pending[label]\n'
            '  file.write_text(json.dumps(data))\n')
        script = script.replace('sys.exit(1)', 'sys.exit(113)')
        script = script.replace('if verb=="bootout": data["loaded"].pop(label,None)',
                                'if verb=="bootout": data.setdefault("stopping",{})[label]=2')
        script = script.replace('if label in data["disabled"]: sys.exit(5)',
                                'if label in data["loaded"]: sys.exit(37)\n'
                                '  if label in data["disabled"]: sys.exit(5)')
        command.write_text(script)
        return result

    def test_root_install_waits_for_previous_service_removal(self) -> None:
        _, _, registry, _, _ = self.delayed_service()
        result = self.fixture.fixture.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads(registry.read_text())
        self.assertEqual(state["loaded"], {install_services.JEV_LABEL: 111})
        self.assertEqual(state.get("stopping"), {})

    def test_root_failure_waits_for_all_writers_before_restoring_state(self) -> None:
        plist, original, registry, before, _ = self.delayed_service()
        result = self.fixture.fixture.run_install(FIXTURE_FAIL_SMOKE="1")
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertIn("previous configuration restored", result.stderr)
        self.assertEqual(plist.read_bytes(), original)
        state = json.loads(registry.read_text())
        self.assertEqual(state["loaded"], before["loaded"])
        self.assertEqual(state.get("stopping"), {})


class DesktopShutdownTests(unittest.TestCase):
    def test_changed_registration_and_rollback_wait_for_removal(self) -> None:
        fixture = test_desktop_session.SessionTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        pending = 0

        def launchctl(arguments: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            nonlocal pending
            verb = arguments[1]
            if verb == "print" and pending:
                pending -= 1
                fixture.loaded = pending != 0
            if verb == "bootstrap" and fixture.loaded:
                return subprocess.CompletedProcess(arguments, 37, stdout="", stderr="")
            result = fixture.launchctl(arguments, **kwargs)
            if verb == "bootout":
                pending = 2
                fixture.loaded = True
            return result

        with mock.patch.object(desktop_session.subprocess, "run", side_effect=launchctl):
            desktop_session.install(fixture.manifest, fixture.home)
            previous = desktop_session.snapshot(fixture.home, fixture.desktop.parent)
            plist = fixture.home / "Library/LaunchAgents" / f"{desktop_session.LABEL}.plist"
            original = plist.read_bytes()
            data = json.loads(fixture.manifest.read_text())
            data["session"]["script"] = "/new-source/server/desktop_session.py"
            fixture.manifest.write_text(json.dumps(data))
            desktop_session.install(fixture.manifest, fixture.home)
            desktop_session.prepare_restore(previous, fixture.home, original)
            self.assertFalse(fixture.loaded, "state restoration requires a stopped writer")
            desktop_session.finish_restore(previous, fixture.home, original)
            self.assertTrue(fixture.loaded)
            self.assertEqual(plist.read_bytes(), original)


class ShutdownDeadlineTests(unittest.TestCase):
    def test_stop_deadline_is_bounded(self) -> None:
        with mock.patch.object(install_services.subprocess, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "shutdown deadline"):
                install_services.wait_stopped("fixture", timeout=0)
        run.assert_not_called()

    def test_query_error_is_not_treated_as_removal(self) -> None:
        with mock.patch.object(install_services.subprocess, "run", return_value=
                               subprocess.CompletedProcess([], 5)):
            with self.assertRaisesRegex(RuntimeError, "verify service removal"):
                install_services.wait_stopped("fixture")

    def test_only_absent_service_confirms_removal(self) -> None:
        with mock.patch.object(install_services.subprocess, "run", side_effect=[
            subprocess.CompletedProcess([], 0), subprocess.CompletedProcess([], 113)
        ]) as run, mock.patch.object(install_services.Event, "wait"):
            install_services.wait_stopped("fixture")
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args.args[0], ["launchctl", "print", f"gui/{os.getuid()}/fixture"])
