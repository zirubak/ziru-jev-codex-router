"""Fixed speed is independent from model and Jev effort."""
import json
import unittest
import urllib.error
from unittest import mock
import jev_server as jev
import test_per_call_routing as fixture
from test_fixed_model_routes import effort_answer

class FastRoutes(unittest.TestCase):
    def setUp(self) -> None:
        fixture.PerCallEndToEnd.setUp(self)
        self.judge = self.enterContext(mock.patch.object(jev, "call_jev_routed", return_value=effort_answer("low")))
    tearDown = fixture.PerCallEndToEnd.tearDown
    call = fixture.PerCallEndToEnd.call

    def test_fixed_speed_is_opt_in(self) -> None:
        for mode in ("sol", "astra"):
            for tier, expected in ((None, "default"), ("default", "default"), ("fast", "priority"), ("priority", "priority")):
                with self.subTest(mode=mode, tier=tier):
                    self.call(fixture.payload_for([fixture.message("user", "Inspect")], model=mode, service_tier=tier))
                    self.assertEqual(fixture.Edge.payloads[-1]["service_tier"], expected)
                    self.assertEqual(self.records[-1]["requested_speed"], expected)
                    self.assertEqual(self.records[-1]["effort"], "low")

    def test_invalid_tiers_fail_before_inference(self) -> None:
        for tier in ("ultrafast", "flex", "auto", "", 1, {}, []):
            with self.subTest(tier=tier), self.assertRaises(urllib.error.HTTPError) as error:
                self.call(fixture.payload_for([], model="sol", service_tier=tier))
            self.assertEqual(error.exception.code, 400)
        self.judge.assert_not_called()
        self.assertEqual(fixture.Edge.payloads, [])

    def test_technical_fallback_keeps_fast_and_model(self) -> None:
        self.judge.side_effect = RuntimeError("synthetic judge failure")
        self.call(fixture.payload_for([fixture.message("user", "Inspect")], model="astra", service_tier="priority"))
        self.assertEqual(fixture.Edge.payloads[-1]["model"], jev.ASTRA)
        self.assertEqual(fixture.Edge.payloads[-1]["service_tier"], "priority")
        self.assertEqual(self.records[-1]["effort"], "high")

    def test_tool_continuation_can_change_speed(self) -> None:
        history = [fixture.message("user", "Inspect"), fixture.tool_call("call-1"), fixture.tool_step("call-1", "ok")]
        for tier in ("priority", "default"):
            self.call(fixture.payload_for(history, model="sol", service_tier=tier))
            self.assertEqual(fixture.Edge.payloads[-1]["service_tier"], tier)
            self.assertEqual(fixture.Edge.payloads[-1]["model"], jev.SOL_61)

    def test_served_speed_is_observed_not_inferred(self) -> None:
        for stream in (True, False):
            for served in ("priority", "default", None):
                with self.subTest(stream=stream, served=served):
                    events = [json.loads(line[6:]) for line in fixture.COMPLETED.splitlines() if line.startswith(b'data: {')]
                    if served is not None:
                        events[-1]["response"]["service_tier"] = served
                    data = b''.join(b'data: ' + json.dumps(event).encode() + b'\n\n' for event in events)
                    with mock.patch.object(fixture, "COMPLETED", data):
                        self.call(fixture.payload_for([fixture.message("user", "Inspect")], model="sol", service_tier="fast", stream=stream))
                    attempt = self.records[-1]["attempts"][-1]
                    self.assertEqual(attempt["requested_speed"], "priority")
                    self.assertEqual(attempt["served_speed"], served)
                    self.assertEqual(attempt["speed"], served)
                    self.assertEqual(self.records[-1]["speed"], served)
