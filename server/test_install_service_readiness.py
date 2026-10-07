"""Service readiness is bounded and belongs to the installed launchd process."""
import subprocess
import unittest
from unittest import mock
from pathlib import Path

import install_service as service


class ServiceReadinessTests(unittest.TestCase):
    def test_delayed_listener_waits_for_owned_pid_and_health(self) -> None:
        with mock.patch.object(service, "service_pid", return_value=123, create=True), mock.patch.object(
            service, "listener_pids", side_effect=[set(), {123}, {123}], create=True
        ), mock.patch.object(service.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as check, mock.patch.object(
            service, "pause", create=True
        ):
            service.wait_ready("fixture", "/fixture/python", Path("/fixture/repo"), timeout=1)
        check.assert_called_once()

    def test_foreign_listener_never_counts_as_healthy(self) -> None:
        with mock.patch.object(service, "service_pid", return_value=123, create=True), mock.patch.object(
            service, "listener_pids", return_value={456}, create=True
        ), mock.patch.object(service.subprocess, "run") as check:
            with self.assertRaisesRegex(RuntimeError, "another process"):
                service.wait_ready("fixture", "/fixture/python", Path("/fixture/repo"), timeout=1)
        check.assert_not_called()

    def test_unready_service_reports_bounded_failure(self) -> None:
        with mock.patch.object(service, "service_pid", return_value=None, create=True), mock.patch.object(
            service, "listener_pids", return_value=set(), create=True
        ):
            with self.assertRaisesRegex(RuntimeError, "readiness"):
                service.wait_ready("fixture", "/fixture/python", Path("/fixture/repo"), timeout=0)
