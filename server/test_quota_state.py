"""Concurrent quota refusals preserve private, usable fallback cooldown state."""
import concurrent.futures
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock
from typing import TextIO

import jev_server as jev


NOW = 1_700_000_000.0
LONG_RESET = NOW + 3_600.123456
SHORT_RESET = NOW + 7_200.0
COMPLETED = (
    b'data: {"type":"response.created","response":{"id":"resp_quota"}}\n\n'
    b'data: {"type":"response.completed","response":{"id":"resp_quota",'
    b'"status":"completed","output":[]}}\n\n'
    b'data: [DONE]\n\n'
)


class QuotaEdge(BaseHTTPRequestHandler):
    """Synthetic native refusal and configured fallback over real loopback HTTP."""

    def log_message(self, *args: object) -> None:
        pass

    def do_POST(self) -> None:
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        with self.server.attempt_lock:
            self.server.attempts.append(payload["model"])
        if payload["model"] in jev.TIERS:
            self.server.refusals.wait(timeout=5)
            text = payload["input"][0]["content"][0]["text"]
            reset = LONG_RESET if text == "long-reset" else SHORT_RESET
            data = b'{"error":{"message":"native quota exhausted"}}'
            self.send_response(429)
            self.send_header("Content-Type", "application/json")
            self.send_header("x-codex-primary-reset-at", str(reset))
        else:
            data = COMPLETED
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class ConcurrentQuotaHttp(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        for name in ("OFF_PATH", "SHADOW_PATH", "DEBUG_PATH", "SIGNATURE_PATH",
                     "LOG_PATH", "DRY_STATE_PATH", "DRY_MANUAL_PATH"):
            self.enterContext(mock.patch.object(jev, name, str(self.directory / name)))
        self.enterContext(mock.patch.object(jev, "STATE", str(self.directory)))
        self.enterContext(mock.patch.object(jev, "local_secret", return_value="fixture-local"))
        self.enterContext(mock.patch.object(jev, "caller_secret", return_value="fixture-caller"))
        self.enterContext(mock.patch.object(jev, "load_key", return_value="fixture-key"))
        self.enterContext(mock.patch.object(jev, "call_jev_routed", return_value={
            "answers": {
                "astra_policy": {"choice": "normal"}, "model": {"choice": "sol"},
                "effort": {"choice": "high"}, "lease": {"choice": "one_call"},
            },
        }))
        self.enterContext(mock.patch.object(
            jev, "fallback_candidates", side_effect=lambda *args, **kwargs: ["fixture/standard"],
        ))
        self.enterContext(mock.patch.object(jev.time, "time", return_value=NOW))
        self.records: list[dict] = []
        self.logged = threading.Condition()

        def record(entry: dict) -> None:
            with self.logged:
                self.records.append(entry)
                self.logged.notify_all()

        self.enterContext(mock.patch.object(jev, "log_line", side_effect=record))
        self.edge = ThreadingHTTPServer(("127.0.0.1", 0), QuotaEdge)
        self.edge.attempts = []
        self.edge.attempt_lock = threading.Lock()
        self.edge.refusals = threading.Barrier(2)
        self.enterContext(mock.patch.object(jev, "ROUTER", self.edge.server_address))
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), jev.Handler)
        for server in (self.edge, self.server):
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)

    def call(self, text: str) -> int:
        payload = {
            "model": "auto", "stream": False,
            "input": [{"type": "message", "role": "user", "content": [
                {"type": "input_text", "text": text},
            ]}],
        }
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.server.server_address[1]}/v1/responses",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Authorization": "Bearer fixture-local"},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            response.read()
            return response.status

    def test_concurrent_refusals_keep_state_and_next_call_uses_fallback(self) -> None:
        opened = threading.Barrier(2)
        written = threading.Barrier(2)
        long_written = threading.Event()
        original_dump = json.dump
        temporary_paths: list[str] = []

        def interleaved_dump(value: dict, handle: TextIO) -> None:
            temporary_paths.append(str(handle.name))
            opened.wait(timeout=5)
            if value["until"] == SHORT_RESET + jev.DRY_RESET_SKEW_S:
                self.assertTrue(long_written.wait(timeout=5))
            original_dump(value, handle)
            handle.flush()
            if value["until"] == LONG_RESET + jev.DRY_RESET_SKEW_S:
                long_written.set()
            written.wait(timeout=5)

        with mock.patch.object(jev.json, "dump", side_effect=interleaved_dump):
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(self.call, ("long-reset", "short-reset")))
        self.assertEqual(results, [200, 200])
        try:
            state = json.loads(Path(jev.DRY_STATE_PATH).read_text(encoding="utf-8"))
            valid_state = state["until"] > NOW
        except json.JSONDecodeError:
            valid_state = False
        reason = jev.native_dry()
        # Any extra native probe should finish deterministically, then be counted.
        self.edge.refusals = threading.Barrier(1)
        status = self.call("following request")
        with self.logged:
            self.assertTrue(self.logged.wait_for(lambda: len(self.records) == 3, timeout=5))
        native_attempts = sum(model in jev.TIERS for model in self.edge.attempts)
        self.assertEqual(
            (valid_state, reason, native_attempts, status),
            (True, "quota", 2, 200),
            f"temporary paths: {temporary_paths}; attempts: {self.edge.attempts}",
        )
        self.assertEqual(self.edge.attempts.count("fixture/standard"), 3)
        self.assertEqual(len(set(temporary_paths)), 2)
        self.assertEqual(list(self.directory.glob("DRY_STATE_PATH.*.tmp")), [])


class QuotaStatePersistence(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.state = self.directory / "dry.json"
        self.manual = self.directory / "manual"
        self.enterContext(mock.patch.object(jev, "DRY_STATE_PATH", str(self.state)))
        self.enterContext(mock.patch.object(jev, "DRY_MANUAL_PATH", str(self.manual)))
        self.enterContext(mock.patch.object(jev.time, "time", return_value=NOW))

    def test_temp_and_published_state_are_private_under_open_umask(self) -> None:
        modes: list[int] = []
        original_dump = json.dump

        def record_mode(value: dict, handle: TextIO) -> None:
            modes.append(os.fstat(handle.fileno()).st_mode & 0o777)
            original_dump(value, handle)

        self.state.write_text("old state", encoding="utf-8")
        self.state.chmod(0o644)
        previous_umask = os.umask(0)
        try:
            with mock.patch.object(jev.json, "dump", side_effect=record_mode):
                self.assertTrue(jev.mark_native_dry("quota"))
        finally:
            os.umask(previous_umask)
        self.assertEqual(modes, [0o600])
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o600)
        self.assertEqual(jev.native_dry(), "quota")

    def test_legacy_shared_temp_symlink_is_never_opened(self) -> None:
        target = self.directory / "unrelated"
        target.write_text("preserve this content", encoding="utf-8")
        Path(str(self.state) + ".tmp").symlink_to(target)
        self.assertTrue(jev.mark_native_dry("quota"))
        self.assertEqual(target.read_text(encoding="utf-8"), "preserve this content")
        self.assertEqual(jev.native_dry(), "quota")

    def test_write_failure_preserves_previous_state_and_cleans_private_temp(self) -> None:
        self.assertTrue(jev.mark_native_dry("quota", LONG_RESET))
        previous = self.state.read_bytes()
        stderr = io.StringIO()
        with mock.patch.object(jev.os, "replace", side_effect=PermissionError("private-detail")), \
                mock.patch.object(jev.sys, "stderr", stderr):
            self.assertFalse(jev.mark_native_dry("different-private-reason", SHORT_RESET))
        self.assertEqual(self.state.read_bytes(), previous)
        self.assertEqual(list(self.directory.glob("dry.json.*.tmp")), [])
        self.assertEqual(stderr.getvalue(), "[jev-router] quota state write failed: PermissionError\n")

    def test_temp_creation_failure_is_reported_without_path_or_contents(self) -> None:
        stderr = io.StringIO()
        with mock.patch.object(jev, "DRY_STATE_PATH", str(self.directory / "missing" / "private.json")), \
                mock.patch.object(jev.sys, "stderr", stderr):
            self.assertFalse(jev.mark_native_dry("private-reason"))
        self.assertEqual(stderr.getvalue(), "[jev-router] quota state write failed: FileNotFoundError\n")
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_serialization_failure_removes_owned_temp_and_propagates(self) -> None:
        with mock.patch.object(jev.json, "dump", side_effect=TypeError("invalid reason")):
            with self.assertRaisesRegex(TypeError, "invalid reason"):
                jev.mark_native_dry("quota")
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_clear_removes_only_auto_state_and_missing_state_is_success(self) -> None:
        self.assertTrue(jev.mark_native_dry("quota"))
        self.manual.touch()
        self.assertTrue(jev.clear_native_dry())
        self.assertFalse(self.state.exists())
        self.assertTrue(self.manual.exists())
        self.assertEqual(jev.native_dry(), "manual")
        self.assertTrue(jev.clear_native_dry())

    def test_clear_failure_is_reported_and_preserves_previous_state(self) -> None:
        self.assertTrue(jev.mark_native_dry("quota"))
        previous = self.state.read_bytes()
        stderr = io.StringIO()
        with mock.patch.object(jev.os, "remove", side_effect=PermissionError("private-detail")), \
                mock.patch.object(jev.sys, "stderr", stderr):
            self.assertFalse(jev.clear_native_dry())
        self.assertEqual(self.state.read_bytes(), previous)
        self.assertEqual(stderr.getvalue(), "[jev-router] quota state clear failed: PermissionError\n")

    def test_clear_during_preparation_precedes_writer_publication(self) -> None:
        self.assertTrue(jev.mark_native_dry("old quota"))
        prepared = threading.Event()
        release = threading.Event()
        original_dump = json.dump

        def delayed_dump(value: dict, handle: TextIO) -> None:
            original_dump(value, handle)
            prepared.set()
            self.assertTrue(release.wait(timeout=5))

        with mock.patch.object(jev.json, "dump", side_effect=delayed_dump):
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                writer = executor.submit(jev.mark_native_dry, "new quota")
                try:
                    self.assertTrue(prepared.wait(timeout=5))
                    self.assertTrue(jev.clear_native_dry())
                    self.assertFalse(self.state.exists())
                finally:
                    release.set()
                self.assertTrue(writer.result(timeout=5))
        self.assertEqual(jev.native_dry(), "new quota")

    def test_clear_waits_for_atomic_publication_then_removes_it(self) -> None:
        publishing = threading.Event()
        release = threading.Event()
        cleared = threading.Event()
        original_replace = os.replace
        original_remove = os.remove

        def delayed_replace(source: str, destination: str) -> None:
            publishing.set()
            self.assertTrue(release.wait(timeout=5))
            original_replace(source, destination)

        def record_remove(path: str) -> None:
            if path == str(self.state):
                cleared.set()
            original_remove(path)

        with mock.patch.object(jev.os, "replace", side_effect=delayed_replace), \
                mock.patch.object(jev.os, "remove", side_effect=record_remove):
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                writer = executor.submit(jev.mark_native_dry, "quota")
                try:
                    self.assertTrue(publishing.wait(timeout=5))
                    clearer = executor.submit(jev.clear_native_dry)
                    self.assertFalse(cleared.wait(timeout=0.1))
                finally:
                    release.set()
                self.assertTrue(writer.result(timeout=5))
                self.assertTrue(clearer.result(timeout=5))
        self.assertTrue(cleared.is_set())
        self.assertFalse(self.state.exists())


if __name__ == "__main__":
    unittest.main()
