"""User-selected models survive every effort and operational routing branch."""
import copy
import json
from pathlib import Path
import time
import unittest
import urllib.error
from unittest import mock

import jev_server as jev
import test_per_call_routing as fixture
from test_per_call_routing import Edge, message, payload_for, tool_call, tool_step
from test_plan_mode import mode_message


def effort_answer(effort: str, lease: str = "one_call") -> dict:
    return {"answers": {
        "effort": {"choice": effort, "confidence": 0.4},
        "lease": {"choice": lease, "confidence": 0.4},
    }}


class FixedModelHttp(unittest.TestCase):
    def setUp(self) -> None:
        fixture.PerCallEndToEnd.setUp(self)
        self.judge = self.enterContext(mock.patch.object(
            jev, "call_jev_routed", return_value=effort_answer("low"),
        ))

    tearDown = fixture.PerCallEndToEnd.tearDown
    call = fixture.PerCallEndToEnd.call

    def test_each_model_and_effort_uses_only_effort_questions(self) -> None:
        for slug, model in (("sol", jev.SOL_61), ("astra", jev.ASTRA)):
            for effort in jev.EFFORTS:
                with self.subTest(slug=slug, effort=effort):
                    self.judge.return_value = effort_answer(effort)
                    history = [message("user", "Independently review this architecture")]
                    status, _ = self.call(payload_for(
                        history, model=f"jev/{slug}", reasoning={"effort": "auto"},
                    ))
                    self.assertEqual(status, 200)
                    sent = Edge.payloads[-1]
                    self.assertEqual(sent["model"], model)
                    self.assertEqual(sent["reasoning"]["effort"], effort)
                    self.assertEqual(sent["input"], history)
                    self.assertEqual(sent["service_tier"], "default")
                    self.assertEqual(set(self.judge.call_args.kwargs["questions"]), {"effort", "lease"})
                    self.assertEqual(self.judge.call_args.args[1]["fixed_model"], model)
                    self.assertEqual(self.records[-1]["model_source"], "user")
                    self.assertEqual(self.records[-1]["effort"], effort)
                    headers = {k.lower(): v for k, v in Edge.headers_seen[-1].items()}
                    self.assertEqual(headers["x-codex-router-exact-route"], "1")

    def test_aliases_and_conflicting_old_model_answers_do_not_change_selection(self) -> None:
        response = effort_answer("medium")
        response["answers"].update({"model": {"choice": "invalid"},
                                    "astra_policy": {"choice": "astra"}})
        self.judge.return_value = response
        for slug, model in (("sol", jev.SOL_61), ("astra", jev.ASTRA)):
            for alias in (slug, f"jev-{slug}", f"jev/{slug}"):
                with self.subTest(alias=alias):
                    self.call(payload_for([message("user", "Inspect")], model=alias))
                    self.assertEqual(Edge.payloads[-1]["model"], model)
                    self.assertEqual(Edge.payloads[-1]["reasoning"]["effort"], "medium")
                    self.assertEqual(self.records[-1]["decision_source"], "jev")

    def test_astra_effective_effort_uses_configuration_update(self) -> None:
        self.call(payload_for([message("user", "Inspect")], model="astra",
                              reasoning={"effort": "max"}))
        sent = Edge.payloads[-1]
        self.assertEqual(sent["model"], jev.ASTRA)
        self.assertEqual(sent["reasoning"]["effort"], "max")
        self.assertEqual(sent["input"][0]["type"], "configuration_update")
        self.assertEqual(sent["input"][0]["reasoning"]["effort"], "low")
        self.assertEqual(self.records[-1]["effort"], "low")

    def test_missing_task_uses_selected_model_high_without_judge(self) -> None:
        self.call(payload_for([], model="astra"))
        self.judge.assert_not_called()
        self.assertEqual(Edge.payloads[-1]["model"], jev.ASTRA)
        self.assertEqual(Edge.payloads[-1]["reasoning"]["effort"], "high")

    def test_technical_failures_keep_selected_model_high(self) -> None:
        for slug, model in (("sol", jev.SOL_61), ("astra", jev.ASTRA)):
            for response in ({"answers": {}}, effort_answer("ultra"), effort_answer("low")):
                with self.subTest(slug=slug, response=response):
                    self.judge.return_value = response
                    self.judge.side_effect = RuntimeError("fixture") if response == effort_answer("low") else None
                    self.call(payload_for([message("user", "Inspect")], model=slug))
                    self.assertEqual(Edge.payloads[-1]["model"], model)
                    self.assertEqual(Edge.payloads[-1]["reasoning"]["effort"], "high")
                    self.assertEqual(self.records[-1]["decision_source"], "technical_fallback")
            self.judge.side_effect = None
            with mock.patch.object(jev, "load_key", return_value=None):
                self.call(payload_for([message("user", "Inspect")], model=slug))
            self.assertEqual(Edge.payloads[-1]["model"], model)
            self.assertEqual(Edge.payloads[-1]["reasoning"]["effort"], "high")

    def test_off_shadow_and_stale_updates_keep_model_high(self) -> None:
        for slug, model in (("sol", jev.SOL_61), ("astra", jev.ASTRA)):
            for flags in (("OFF_PATH",), ("SHADOW_PATH",), ("OFF_PATH", "SHADOW_PATH")):
                for stale in ("auto", "low", "max"):
                    with self.subTest(slug=slug, flags=flags, stale=stale):
                        paths = [Path(getattr(jev, flag)) for flag in flags]
                        for path in paths:
                            path.touch()
                        self.judge.reset_mock()
                        try:
                            self.call(payload_for([
                                {"type": "configuration_update", "reasoning": {"effort": stale}},
                                message("user", "Inspect"),
                            ], model=slug, reasoning={"effort": "max"}))
                        finally:
                            for path in paths:
                                path.unlink()
                        sent = Edge.payloads[-1]
                        self.assertEqual(sent["model"], model)
                        self.assertEqual(sent["reasoning"]["effort"], "high")
                        self.assertEqual(sent["input"][0]["reasoning"]["effort"], "high")
                        if "OFF_PATH" in flags:
                            self.judge.assert_not_called()
                            self.assertEqual(self.records[-1]["gate"], "off")
                        else:
                            self.assertEqual(self.records[-1]["would"]["effort"], "low")

    def test_plan_preserves_model_and_rejudges_with_review_guidance(self) -> None:
        for slug, model in (("sol", jev.SOL_61), ("astra", jev.ASTRA)):
            self.judge.return_value = effort_answer("high", "user_turn")
            history = [mode_message("Plan"), message("user", "Design migration")]
            self.call(payload_for(history, model=slug, reasoning={"effort": "low"}))
            self.assertEqual(Edge.payloads[-1]["model"], model)
            self.assertEqual(set(self.judge.call_args.kwargs["questions"]),
                             {"effort", "lease", "planning_review"})
            self.assertTrue(any("jev_planning_guidance" in json.dumps(item)
                                for item in Edge.payloads[-1]["input"]))
            before = self.judge.call_count
            self.call(payload_for(history + [tool_call("c1"), tool_step("c1", "ok")], model=slug))
            self.assertEqual(self.judge.call_count, before + 1)

    def test_model_switch_invalidates_lease_but_clean_continuation_reuses_it(self) -> None:
        self.judge.return_value = effort_answer("medium", "user_turn")
        history = [message("user", "Inspect fixture")]
        self.call(payload_for(history, model="sol"))
        continuation = history + [tool_call("c1"), tool_step("c1", "ok")]
        self.call(payload_for(continuation, model="jev-sol"))
        self.assertEqual(self.judge.call_count, 1)
        self.assertEqual(self.records[-1]["decision_source"], "lease")
        self.call(payload_for(continuation, model="astra"))
        self.assertEqual(self.judge.call_count, 2)
        self.assertEqual(Edge.payloads[-1]["model"], jev.ASTRA)

    def test_native_error_never_discovers_or_calls_another_model(self) -> None:
        def refuse(edge: Edge) -> None:
            body = json.loads(edge.rfile.read(int(edge.headers["Content-Length"])))
            Edge.payloads.append(body)
            raw = b'{"error":{"code":"usage_limit_reached","message":"usage limit reached"}}'
            edge.send_response(429)
            edge.send_header("Content-Type", "application/json")
            edge.send_header("Content-Length", str(len(raw)))
            edge.end_headers()
            edge.wfile.write(raw)

        for slug, model in (("sol", jev.SOL_61), ("astra", jev.ASTRA)):
            before = len(Edge.payloads)
            with mock.patch.object(Edge, "do_POST", new=refuse), mock.patch.object(
                jev, "fallback_candidates", return_value=["fixture/fallback"],
            ) as candidates, mock.patch.object(jev, "mark_native_dry"), self.assertRaises(
                urllib.error.HTTPError,
            ) as error:
                self.call(payload_for([message("user", "Inspect")], model=slug))
            self.assertEqual(error.exception.code, 503)
            self.assertIn(model, error.exception.read().decode())
            error.exception.close()
            candidates.assert_not_called()
            self.assertEqual(len(Edge.payloads), before + 1)
            self.assertEqual(Edge.payloads[-1]["model"], model)

    def test_automatic_quota_rechecks_once_and_clears_on_success(self) -> None:
        with mock.patch.object(jev, "native_dry", new=self.saved[3]), mock.patch.object(
            jev, "fallback_candidates", return_value=["fixture/fallback"],
        ) as candidates:
            for slug in ("sol", "astra"):
                for lite in (False, True):
                    self.assertTrue(jev.mark_native_dry("quota", time.time() + 3600))
                    headers = {"x-openai-internal-codex-responses-lite": "true"} if lite else {}
                    before = len(Edge.payloads)
                    self.call(payload_for([message("user", "Inspect")], model=slug), headers)
                    self.assertEqual(len(Edge.payloads), before + 1)
                    self.assertFalse(Path(jev.DRY_STATE_PATH).exists())
            candidates.assert_not_called()

    def test_manual_dry_has_zero_native_attempts(self) -> None:
        for slug, model in (("sol", jev.SOL_61), ("astra", jev.ASTRA)):
            with mock.patch.object(jev, "native_dry", return_value="manual"), mock.patch.object(
                jev, "fallback_candidates",
            ) as candidates, self.assertRaises(urllib.error.HTTPError) as error:
                self.call(payload_for([message("user", "Inspect")], model=slug))
            self.assertEqual(error.exception.code, 503)
            self.assertIn(model, error.exception.read().decode())
            error.exception.close()
            candidates.assert_not_called()
        self.assertEqual(Edge.payloads, [])

    def test_canonical_image_tool_replay_and_lite_header_are_preserved(self) -> None:
        history = [message("user", "Inspect image")]
        history[0]["content"].append({"type": "input_image", "image_url": "data:image/png;base64,fixture"})
        history.extend([tool_call("c1"), tool_step("c1", "result")])
        original = payload_for(history, model="sol")
        self.call(copy.deepcopy(original), {"x-openai-internal-codex-responses-lite": "true"})
        sent = Edge.payloads[-1]
        for name in ("input", "tools", "instructions", "prompt_cache_key", "prompt_cache_options"):
            self.assertEqual(sent[name], original[name])
        headers = {k.lower(): v for k, v in Edge.headers_seen[-1].items()}
        self.assertEqual(headers["x-openai-internal-codex-responses-lite"], "true")


if __name__ == "__main__":
    unittest.main()
