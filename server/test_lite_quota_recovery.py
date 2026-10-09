"""Responses-lite can recheck automatic quota without losing canonical replay."""
import copy
import json
from pathlib import Path
import time
import unittest
import urllib.error
from unittest import mock

import jev_server as jev
import test_per_call_routing as fixture
from test_per_call_routing import Edge, answer, message, payload_for, tool_call, tool_step


class LiteQuotaRecoveryHttp(unittest.TestCase):
    def setUp(self) -> None:
        fixture.PerCallEndToEnd.setUp(self)
        self.judge = self.enterContext(mock.patch.object(
            jev, "call_jev_routed", return_value=answer(jev.SOL_61, "high"),
        ))

    def tearDown(self) -> None:
        fixture.PerCallEndToEnd.tearDown(self)

    call = fixture.PerCallEndToEnd.call

    def lite_request(
        self, mode: str, detector: str,
    ) -> tuple[dict[str, object], dict[str, str], str]:
        history: list[dict[str, object]] = [
            message("user", "Continue the fixture inspection."),
            tool_call("fixture-call"),
            tool_step("fixture-call", "fixture result"),
        ]
        headers: dict[str, str] = {}
        if detector == "input":
            history.insert(0, {
                "type": "additional_tools", "role": "developer",
                "tools": [{"type": "function", "name": "spawn_agent"}],
            })
        else:
            headers["x-openai-internal-codex-responses-lite"] = "true"
        effort = "max" if mode == "manual" else "auto"
        payload = payload_for(history, model=mode, reasoning={"effort": effort})
        if detector == "input":
            # Desktop lite requests can declare tools solely in input history.
            del payload["tools"]
        return payload, headers, "max" if mode == "manual" else "high"

    def test_lite_auto_quota_native_success_clears_state_preserves_request(self) -> None:
        with mock.patch.object(jev, "native_dry", new=self.saved[3]), mock.patch.object(
            jev, "fallback_candidates", return_value=["fixture/fallback"],
        ) as candidates:
            for mode in ("auto", "manual"):
                for detector in ("header", "input"):
                    with self.subTest(mode=mode, detector=detector):
                        self.assertTrue(jev.mark_native_dry("quota", time.time() + 3600))
                        self.assertEqual(jev.native_dry(), "quota")
                        payload, headers, effort = self.lite_request(mode, detector)
                        original = copy.deepcopy(payload)
                        before = len(Edge.payloads)
                        status, _ = self.call(payload, headers)
                        self.assertEqual(status, 200)
                        self.assertEqual(len(Edge.payloads), before + 1)
                        sent = Edge.payloads[-1]
                        self.assertEqual(sent["model"], jev.SOL_61)
                        self.assertEqual(sent["reasoning"]["effort"], effort)
                        for name in ("input", "instructions", "prompt_cache_key", "prompt_cache_options"):
                            self.assertEqual(sent[name], original[name])
                        self.assertEqual("tools" in sent, "tools" in original)
                        self.assertEqual(sent.get("tools"), original.get("tools"))
                        forwarded_headers = {key.lower(): value for key, value in Edge.headers_seen[-1].items()}
                        self.assertEqual(forwarded_headers.get("x-codex-router-canonical-replay"), "1")
                        self.assertEqual(
                            forwarded_headers.get("x-openai-internal-codex-responses-lite"),
                            headers.get("x-openai-internal-codex-responses-lite"),
                        )
                        self.assertNotIn("x-codex-router-exact-route", forwarded_headers)
                        self.assertFalse(Path(jev.DRY_STATE_PATH).exists())
                        self.assertIsNone(jev.native_dry())
            candidates.assert_not_called()

    def test_lite_auto_quota_native_recheck_429_refreshes_each_request(self) -> None:
        announced_reset = 0

        def limited(edge: Edge) -> None:
            body = json.loads(edge.rfile.read(int(edge.headers["Content-Length"])))
            Edge.payloads.append(body)
            Edge.headers_seen.append(dict(edge.headers))
            raw = b'{"error":{"code":"usage_limit_reached","message":"usage limit reached"}}'
            edge.send_response(429)
            edge.send_header("Content-Type", "application/json")
            edge.send_header("x-codex-primary-reset-at", str(announced_reset))
            edge.send_header("Content-Length", str(len(raw)))
            edge.end_headers()
            edge.wfile.write(raw)

        with mock.patch.object(jev, "native_dry", new=self.saved[3]), mock.patch.object(
            Edge, "do_POST", new=limited,
        ), mock.patch.object(
            jev, "fallback_candidates", return_value=["fixture/fallback"],
        ) as candidates:
            for mode in ("auto", "manual"):
                self.assertTrue(jev.mark_native_dry("quota", time.time() + 3600))
                payload, headers, effort = self.lite_request(mode, "header")
                for seconds in (900, 1200):
                    with self.subTest(mode=mode, reset_after=seconds):
                        announced_reset = int(time.time()) + seconds
                        before = len(Edge.payloads)
                        with self.assertRaises(urllib.error.HTTPError) as error:
                            self.call(payload, headers)
                        self.assertEqual(error.exception.code, 503)
                        self.assertIn("Responses-lite", error.exception.read().decode())
                        error.exception.close()
                        self.assertEqual(len(Edge.payloads), before + 1)
                        sent = Edge.payloads[-1]
                        self.assertEqual(sent["model"], jev.SOL_61)
                        self.assertEqual(sent["reasoning"]["effort"], effort)
                        self.assertEqual(sent["input"], payload["input"])
                        state = json.loads(Path(jev.DRY_STATE_PATH).read_text())
                        self.assertEqual(state["reason"], "quota")
                        self.assertAlmostEqual(
                            state["until"], announced_reset + jev.DRY_RESET_SKEW_S, delta=2,
                        )
                        self.assertEqual(jev.native_dry(), "quota")
            candidates.assert_not_called()

    def test_lite_manual_quota_marker_blocks_native_and_external(self) -> None:
        marker = Path(jev.DRY_MANUAL_PATH)
        marker.touch()
        with mock.patch.object(jev, "native_dry", new=self.saved[3]), mock.patch.object(
            jev, "fallback_candidates", return_value=["fixture/fallback"],
        ) as candidates:
            for mode in ("auto", "manual"):
                for detector in ("header", "input"):
                    with self.subTest(mode=mode, detector=detector):
                        self.assertTrue(jev.mark_native_dry("quota", time.time() + 3600))
                        previous_state = Path(jev.DRY_STATE_PATH).read_bytes()
                        self.assertEqual(jev.native_dry(), "manual")
                        payload, headers, _ = self.lite_request(mode, detector)
                        with self.assertRaises(urllib.error.HTTPError) as error:
                            self.call(payload, headers)
                        self.assertEqual(error.exception.code, 503)
                        self.assertIn("Responses-lite", error.exception.read().decode())
                        error.exception.close()
                        self.assertEqual(Edge.payloads, [])
                        self.assertTrue(marker.exists())
                        self.assertEqual(Path(jev.DRY_STATE_PATH).read_bytes(), previous_state)
                        self.assertEqual(jev.native_dry(), "manual")
            candidates.assert_not_called()


if __name__ == "__main__":
    unittest.main()
