"""Ultra is a manual native-client recommendation, never an API effort."""
import json
import unittest
from pathlib import Path
from unittest import mock

import jev_server as jev
from routing_policy import decision_from_answers
import test_per_call_routing as fixture
from test_per_call_routing import Edge, answer, message, payload_for, tool_call, tool_step


class UltraAdvisoryHTTP(unittest.TestCase):
    setUp = fixture.PerCallEndToEnd.setUp
    tearDown = fixture.PerCallEndToEnd.tearDown
    call = fixture.PerCallEndToEnd.call

    def test_stream_first_delta_shows_actual_route_and_manual_advice(self) -> None:
        Path(jev.SIGNATURE_PATH).touch()
        choice = answer(jev.ASTRA, "max", astra_required=True)
        choice["answers"]["ultra_advice"] = {"choice": "parallel_review"}
        events = [
            {"type": "response.output_text.delta", "item_id": "msg",
             "content_index": 0, "delta": "Ready"},
            {"type": "response.completed", "response": {
                "status": "completed", "output": [{"id": "msg", "type": "message",
                 "role": "assistant", "content": [{"type": "output_text", "text": "Ready"}]}],
            }},
        ]
        raw = "".join("data: " + json.dumps(e) + "\n\n" for e in events).encode()
        with mock.patch.object(jev, "call_jev_routed", return_value=choice), \
             mock.patch("test_per_call_routing.COMPLETED", raw):
            _, body = self.call(payload_for([message("user", "Review independent subsystems.")]))
        delta = next(json.loads(line[6:])["delta"] for line in body.decode().splitlines()
                     if line.startswith("data: ") and "output_text.delta" in line)
        self.assertTrue(delta.startswith("[gpt-6-astra / max]\n\n[Jev Ultra 추천]"))
        self.assertIn("GPT-6 Astra", delta)
        self.assertNotIn('"effort": "ultra"', json.dumps(Edge.payloads[-1]))
    def test_fresh_advisory_is_visible_and_api_effort_stays_valid(self) -> None:
        choice = answer(jev.SOL_61, "max", lease="user_turn")
        choice["answers"]["ultra_advice"] = {"choice": "parallel_exploration"}
        response = ("data: " + json.dumps({
            "type": "response.completed",
            "response": {"status": "completed", "output": [{
                "id": "msg", "type": "message", "role": "assistant",
                "content": [{"type": "output_text", "text": "Ready"}],
            }]},
        }) + "\n\ndata: [DONE]\n\n").encode()
        opening = [message("user", "Investigate three independent subsystem failures.")]
        with mock.patch.object(jev, "call_jev_routed", return_value=choice), \
             mock.patch("test_per_call_routing.COMPLETED", response):
            # Nonstream path uses the same local authenticated HTTP relay.
            _, body = self.call(payload_for(opening, stream=False))
            rendered = json.loads(body)["output"][0]["content"][0]["text"]
            self.assertIn("Ultra", rendered)
            self.assertIn("직접 선택", rendered)
            self.assertNotIn("/ ultra]", rendered)
            self.assertEqual(Edge.payloads[-1]["reasoning"]["effort"], "max")
            _, continued = self.call(payload_for(
                opening + [tool_call("c0"), tool_step("c0", "ok")], stream=False))
            self.assertNotIn("Ultra", continued.decode())
        self.assertEqual(self.records[0]["ultra_advice"], "parallel_exploration")

    def test_missing_or_invalid_optional_advisory_does_not_change_route(self) -> None:
        for optional in (None, {"choice": "bad"}, {"choice": "parallel_review",
                         "probabilities": {"parallel_review": 1}}):
            choice = answer(jev.SOL_61, "medium")
            if optional is not None:
                choice["answers"]["ultra_advice"] = optional
            result = decision_from_answers(choice["answers"])
            self.assertEqual(result["model"], jev.SOL_61)
            self.assertEqual(result["ultra_advice"], "none")

    def test_json_presentation_and_replay_preserve_original_data(self) -> None:
        shown = {"model": jev.SOL_61, "effort": "max", "ultra_advice": "parallel_review"}
        with mock.patch.object(jev.os.path, "exists", return_value=True):
            header = jev.presentation_signature({}, shown)
            self.assertIn("Ultra", header)
            self.assertIsNone(jev.presentation_signature(
                {"text": {"format": {"type": "json_schema"}}}, shown))
        payload = {"input": [{"role": "assistant", "content": header + "Ready"}]}
        self.assertEqual(jev.strip_signatures(payload), 1)
        self.assertEqual(payload["input"][0]["content"], "Ready")

    def test_technical_fallback_never_carries_ultra_advice(self) -> None:
        with mock.patch.object(jev, "call_jev_routed", side_effect=TimeoutError()):
            self.call(payload_for([message("user", "Investigate parallel components.")]))
        self.assertEqual(self.records[-1]["ultra_advice"], "none")
        self.assertEqual(Edge.payloads[-1]["reasoning"]["effort"], "high")

    def test_quota_refusal_clears_unserved_advisory_in_log(self) -> None:
        choice = answer(jev.SOL_61, "max")
        choice["answers"]["ultra_advice"] = {"choice": "parallel_exploration"}
        refused = b'{"error":{"message":"rate limit reached"}}'
        with mock.patch.object(jev, "call_jev_routed", return_value=choice), \
             mock.patch.object(jev.Handler, "_forward",
                               return_value=(429, "json", "application/json", True,
                                             refused, None)), \
             mock.patch.object(jev, "mark_native_dry"), \
             mock.patch.object(jev, "fallback_candidates", return_value=[]):
            with self.assertRaises(fixture.urllib.error.HTTPError):
                self.call(payload_for([message("user", "Investigate separate components.")]))
        self.assertTrue(self.logged.wait(3))
        self.assertEqual(self.records[-1]["ultra_advice"], "none")
