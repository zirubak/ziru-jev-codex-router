"""Installation verifies quota recovery through the native lite HTTP relay."""
import contextlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import threading
import time
import unittest
from unittest import mock

import healthcheck
import jev_server as jev
import smoke
import test_per_call_routing as fixture
from test_per_call_routing import Edge, answer


class SmokeRecoveryHttp(unittest.TestCase):
    def setUp(self) -> None:
        fixture.PerCallEndToEnd.setUp(self)
        jev.native_dry = self.saved[3]
        self.enterContext(mock.patch.object(
            jev, "call_jev_routed", return_value=answer(jev.SOL_61, "low"),
        ))
        self.enterContext(mock.patch.object(
            fixture, "COMPLETED", fixture.COMPLETED.replace(
                b'"id":"resp_call"', b'"id":"resp_call","model":"gpt-6.1-sol"',
            ),
        ))
        self.candidates = self.enterContext(mock.patch.object(
            jev, "fallback_candidates", return_value=[],
        ))
        self.enterContext(mock.patch.object(smoke, "STATE", jev.STATE))
        Path(jev.STATE, "caller-secret").write_text("fixture-caller")
        self.assertTrue(jev.mark_native_dry("quota", time.time() + 3600))
        connection_type = http.client.HTTPConnection
        server_port = self.server.server_address[1]

        class Parent(BaseHTTPRequestHandler):
            def log_message(self, *args: object) -> None:
                pass

            def do_POST(self) -> None:
                if self.path != "/_codex-router/fixture-caller/v1/responses":
                    self.send_error(404)
                    return
                body = self.rfile.read(int(self.headers["Content-Length"]))
                headers = dict(self.headers)
                headers["Authorization"] = "Bearer fixture-local"
                connection = connection_type("127.0.0.1", server_port, timeout=5)
                try:
                    connection.request("POST", "/v1/responses", body, headers)
                    response = connection.getresponse()
                    data = response.read()
                    self.send_response(response.status)
                    self.send_header("Content-Type", response.getheader("Content-Type"))
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                finally:
                    connection.close()

        self.parent = ThreadingHTTPServer(("127.0.0.1", 0), Parent)
        threading.Thread(target=self.parent.serve_forever, daemon=True).start()

        parent_port = self.parent.server_address[1]

        class LocalConnection(connection_type):
            def __init__(self, host: str, port: int | None = None, **kwargs: object) -> None:
                destination = {4319: server_port, 4202: parent_port}.get(port, port)
                super().__init__(host, destination, **kwargs)

        self.enterContext(mock.patch.object(smoke.http.client, "HTTPConnection", LocalConnection))
        self.enterContext(mock.patch.object(
            smoke, "healthy", side_effect=lambda: healthcheck.healthy(
                f"http://127.0.0.1:{server_port}/health"),
        ))

    def tearDown(self) -> None:
        self.parent.shutdown()
        self.parent.server_close()
        fixture.PerCallEndToEnd.tearDown(self)

    def test_smoke_cached_quota_recovers_native_lite_and_clears_state(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            smoke.main()
        self.assertTrue(self.logged.wait(3), "wait for the call log record")
        result = json.loads(output.getvalue())
        self.assertEqual(result["http"], 200)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["model"], jev.SOL_61)
        self.assertEqual(len(Edge.payloads), 1)
        self.assertEqual(Edge.payloads[0]["reasoning"]["context"], "all_turns")
        self.assertIs(Edge.payloads[0]["parallel_tool_calls"], False)
        headers = {key.lower(): value for key, value in Edge.headers_seen[0].items()}
        self.assertEqual(headers["x-openai-internal-codex-responses-lite"], "true")
        self.assertFalse(Path(jev.DRY_STATE_PATH).exists())
        self.candidates.assert_not_called()

    def test_smoke_checks_both_fixed_native_routes(self) -> None:
        original_post = Edge.do_POST

        def native(edge: Edge) -> None:
            data = edge.rfile.read(int(edge.headers["Content-Length"]))
            body = json.loads(data)
            edge.rfile = io.BytesIO(data)
            with mock.patch.object(fixture, "COMPLETED", fixture.COMPLETED.replace(
                b'"model":"gpt-6.1-sol"', f'"model":"{body["model"]}"'.encode(),
            )):
                original_post(edge)

        for route, model in (("sol", jev.SOL_61), ("astra", jev.ASTRA)):
            with self.subTest(route=route), mock.patch.object(Edge, "do_POST", native):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    smoke.main(f"jev/{route}")
                result = json.loads(output.getvalue())
                self.assertEqual(result["model"], model)
                self.assertEqual(result["status"], "completed")
        self.candidates.assert_not_called()

    def test_fast_smoke_requires_reported_fast_service(self) -> None:
        original_post = Edge.do_POST
        for tier in ("priority", "fast", "default", None):
            def native(edge: Edge) -> None:
                events = fixture.COMPLETED.split(b'\n\n')
                completed = json.loads(events[1][6:])
                if tier is not None:
                    completed["response"]["service_tier"] = tier
                events[1] = b'data: ' + json.dumps(completed).encode()
                with mock.patch.object(fixture, "COMPLETED", b'\n\n'.join(events)):
                    original_post(edge)

            with self.subTest(tier=tier), mock.patch.object(Edge, "do_POST", native):
                output = io.StringIO()
                if tier in ("priority", "fast"):
                    with contextlib.redirect_stdout(output):
                        smoke.main("jev/sol", "fast")
                    self.assertEqual(json.loads(output.getvalue())["service_tier"], tier)
                else:
                    with self.assertRaisesRegex(RuntimeError, "did not confirm Fast service"):
                        smoke.main("jev/sol", "fast")

    def test_smoke_fresh_quota_refusal_fails_without_external_execution(self) -> None:
        def limited(edge: Edge) -> None:
            Edge.payloads.append(json.loads(edge.rfile.read(int(edge.headers["Content-Length"]))))
            raw = b'{"error":{"code":"usage_limit_reached"}}'
            edge.send_response(429)
            edge.send_header("Content-Type", "application/json")
            edge.send_header("Content-Length", str(len(raw)))
            edge.end_headers()
            edge.wfile.write(raw)

        with mock.patch.object(Edge, "do_POST", limited), self.assertRaisesRegex(
            RuntimeError, "parent router returned HTTP 503",
        ):
            smoke.main()
        self.assertTrue(self.logged.wait(3), "wait for the call log record")
        self.assertEqual(len(Edge.payloads), 1)
        self.assertEqual(jev.native_dry(), "quota")
        self.candidates.assert_not_called()

    def test_smoke_rejects_wrong_or_missing_terminal_native_model(self) -> None:
        original_post = Edge.do_POST
        for terminal_model in (jev.ASTRA, None):
            def mismatched(edge: Edge) -> None:
                events = fixture.COMPLETED.split(b'\n\n')
                completed = json.loads(events[1][6:])
                if terminal_model is None:
                    completed["response"].pop("model", None)
                else:
                    completed["response"]["model"] = terminal_model
                events[1] = b'data: ' + json.dumps(completed).encode()
                with mock.patch.object(fixture, "COMPLETED", b'\n\n'.join(events)):
                    original_post(edge)

            with self.subTest(terminal_model=terminal_model), mock.patch.object(
                Edge, "do_POST", mismatched,
            ), contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(
                RuntimeError, "native response did not confirm the selected model",
            ):
                smoke.main("jev/sol")


if __name__ == "__main__":
    unittest.main()
