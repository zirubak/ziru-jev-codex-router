"""Selection modes enforce user controls through the real localhost relay."""
import copy
import json
from pathlib import Path
import unittest
import urllib.error
import urllib.request
from unittest import mock

import jev_server as jev
import test_per_call_routing as fixture
from test_per_call_routing import Edge, answer, message, payload_for, tool_call, tool_step
from test_plan_mode import mode_message


class SelectionModeHttp(unittest.TestCase):
    def setUp(self) -> None:
        fixture.PerCallEndToEnd.setUp(self)
        self.judge = self.enterContext(mock.patch.object(
            jev, "call_jev_routed", return_value=answer(jev.SOL_61, "low", lease="user_turn"),
        ))

    tearDown = fixture.PerCallEndToEnd.tearDown
    call = fixture.PerCallEndToEnd.call

    def test_manual_all_efforts_override_judge(self) -> None:
        for effort in ("low", "medium", "high", "xhigh", "max"):
            with self.subTest(effort=effort):
                self.call(payload_for([message("user", "Inspect fixture")], model="manual",
                                      reasoning={"effort": effort}))
                self.assertEqual(Edge.payloads[-1]["reasoning"]["effort"], effort)
                self.assertEqual(self.judge.call_args.args[1]["selection_mode"], "manual")
                self.assertEqual(self.judge.call_args.args[1]["user_effort"], effort)
                self.assertEqual(self.records[-1]["selection_mode"], "manual")

    def test_manual_missing_effort_defaults_medium(self) -> None:
        self.call(payload_for([message("user", "Inspect fixture")], model="jev/manual"))
        self.assertEqual(Edge.payloads[-1]["reasoning"]["effort"], "medium")

    def test_manual_invalid_effort_rejected_before_judge(self) -> None:
        for effort in ("auto", "ultra", "light", "", None, 1):
            request = urllib.request.Request(
                f"http://127.0.0.1:{self.server.server_address[1]}/v1/responses",
                data=json.dumps(payload_for([message("user", "Inspect")], model="manual",
                                           reasoning={"effort": effort})).encode(),
                headers={"Authorization": "Bearer fixture-local", "Content-Type": "application/json"},
            )
            with self.subTest(effort=effort), self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(request)
            self.assertEqual(error.exception.code, 400)
            error.exception.close()
        self.judge.assert_not_called()
        self.assertEqual(Edge.payloads, [])

    def test_models_publish_both_truthful_names(self) -> None:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{self.server.server_address[1]}/v1/models",
        ) as response:
            rows = json.load(response)["data"]
        self.assertEqual([(row["id"], row["name"]) for row in rows], [
            ("auto", "Jev Codex Router by Auto"), ("manual", "Jev Codex Router"),
        ])

    def test_auto_sentinel_is_removed(self) -> None:
        self.call(payload_for([message("user", "Inspect")], reasoning={"effort": "auto"}))
        self.assertEqual(Edge.payloads[-1]["reasoning"]["effort"], "low")

    def test_manual_plan_normalizes_existing_update(self) -> None:
        self.call(payload_for([
            mode_message("Plan"), {"type": "configuration_update", "reasoning": {"effort": "low"}},
            message("user", "Plan fixture"),
        ], model="jev-manual", reasoning={"effort": "max"}))
        self.assertEqual(Edge.payloads[-1]["reasoning"]["effort"], "max")
        self.assertEqual(Edge.payloads[-1]["input"][1]["reasoning"]["effort"], "max")

    def test_manual_plan_advises_stronger_effort_without_overriding(self) -> None:
        self.judge.return_value = answer(jev.SOL_61, "high")
        self.call(payload_for([mode_message("Plan"), message("user", "Design migration")],
                              model="manual", reasoning={"effort": "low"}))
        sent = Edge.payloads[-1]
        self.assertEqual(sent["reasoning"]["effort"], "low")
        advice = [item for item in sent["input"] if item.get("role") == "developer"]
        self.assertTrue(any("recommended effort high" in json.dumps(item) for item in advice))

    def test_mode_or_effort_switch_invalidates_lease(self) -> None:
        history = [message("user", "Inspect fixture")]
        self.call(payload_for(history))
        continuation = history + [tool_call("c1"), tool_step("c1", "ok")]
        self.call(payload_for(continuation, model="manual", reasoning={"effort": "low"}))
        self.call(payload_for(continuation, model="manual", reasoning={"effort": "max"}))
        self.assertEqual(self.judge.call_count, 3)

    def test_manual_technical_fallback_honors_effort(self) -> None:
        with mock.patch.object(jev, "load_key", return_value=None):
            self.call(payload_for([message("user", "Inspect")], model="manual",
                                  reasoning={"effort": "max"}))
        self.assertEqual(Edge.payloads[-1]["model"], jev.SOL_61)
        self.assertEqual(Edge.payloads[-1]["reasoning"]["effort"], "max")

    def test_manual_quota_retry_retains_exact_effort(self) -> None:
        attempts: list[dict] = []

        def forward(handler: jev.Handler, payload: dict, *args: object, **kwargs: object) -> tuple:
            attempts.append(copy.deepcopy(payload))
            quota = len(attempts) == 1
            return (429 if quota else 200, "json", "application/json", quota, b"{}", None)

        with mock.patch.object(jev.Handler, "_forward", new=forward), mock.patch.object(
            jev, "fallback_candidates", return_value=["fixture/fallback"],
        ) as candidates, mock.patch.object(jev, "mark_native_dry"):
            self.call(payload_for([mode_message("Plan"), message("user", "Plan")],
                                  model="manual", reasoning={"effort": "medium"}))
        self.assertEqual([entry["reasoning"]["effort"] for entry in attempts], ["medium", "medium"])
        self.assertEqual(candidates.call_args.kwargs, {"user_effort": "medium"})

    def test_auto_quota_retry_reconciles_stale_update_on_each_route(self) -> None:
        attempts: list[dict] = []

        def forward(handler: jev.Handler, payload: dict, *args: object, **kwargs: object) -> tuple:
            attempts.append(copy.deepcopy(payload))
            quota = len(attempts) == 1
            return (429 if quota else 200, "json", "application/json", quota, b"{}", None)

        with mock.patch.object(jev.Handler, "_forward", new=forward), mock.patch.object(
            jev, "fallback_candidates", return_value=["fixture/fallback"],
        ), mock.patch.object(jev, "mark_native_dry"):
            self.call(payload_for([
                {"type": "configuration_update", "reasoning": {"effort": "max"}},
                message("user", "Inspect"),
            ], reasoning={"effort": "auto"}))
        self.assertEqual(len(attempts), 2)
        for sent in attempts:
            self.assertEqual(sent["input"][0]["reasoning"]["effort"], sent["reasoning"]["effort"])

    def test_operational_bypass_never_forwards_auto_sentinel(self) -> None:
        for path_name in ("OFF_PATH", "SHADOW_PATH"):
            path = Path(getattr(jev, path_name))
            path.touch()
            try:
                self.call(payload_for([message("user", "Inspect")], reasoning={"effort": "auto"}))
            finally:
                path.unlink()
            self.assertEqual(Edge.payloads[-1]["reasoning"]["effort"], "high")

    def test_auto_update_sentinel_never_reaches_model(self) -> None:
        self.call(payload_for([
            {"type": "configuration_update", "reasoning": {"effort": "auto"}},
            message("user", "Inspect"),
        ], reasoning={"effort": "auto"}))
        self.assertEqual(Edge.payloads[-1]["input"][0]["reasoning"]["effort"], "low")

    def test_auto_stale_valid_updates_follow_each_judgment(self) -> None:
        for inherited, selected in (("max", "low"), ("low", "high")):
            with self.subTest(inherited=inherited, selected=selected):
                self.judge.return_value = answer(jev.SOL_61, selected)
                self.call(payload_for([
                    {"type": "configuration_update", "reasoning": {"effort": inherited}},
                    message("user", "Inspect"),
                ], reasoning={"effort": "auto"}))
                sent = Edge.payloads[-1]
                self.assertEqual(sent["reasoning"]["effort"], selected)
                self.assertEqual(sent["input"][0]["reasoning"]["effort"], selected)

    def test_bypass_auto_update_uses_valid_inherited_effort(self) -> None:
        for name in ("OFF_PATH", "SHADOW_PATH"):
            marker = Path(getattr(jev, name))
            marker.touch()
            try:
                self.call(payload_for([
                    {"type": "configuration_update", "reasoning": {"effort": "auto"}},
                    message("user", "Inspect"),
                ], reasoning={"effort": "max"}))
            finally:
                marker.unlink()
            sent = Edge.payloads[-1]
            self.assertEqual(sent["reasoning"]["effort"], "max")
            self.assertEqual(sent["input"][0]["reasoning"]["effort"], "max")

    def test_manual_quota_without_compatible_candidate_errors(self) -> None:
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.server.server_address[1]}/v1/responses",
            data=json.dumps(payload_for([message("user", "Inspect")], model="manual",
                                       reasoning={"effort": "max"})).encode(),
            headers={"Authorization": "Bearer fixture-local", "Content-Type": "application/json"},
        )
        with mock.patch.object(jev, "native_dry", return_value="quota"), mock.patch.object(
            jev, "fallback_candidates", return_value=[],
        ), self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request)
        self.assertEqual(error.exception.code, 503)
        self.assertIn("manual effort max", error.exception.read().decode())
        error.exception.close()
        self.assertEqual(Edge.payloads, [])

    def test_lite_known_quota_rejects_external_execution(self) -> None:
        for mode in ("auto", "manual"):
            for header_only in (False, True):
                with self.subTest(mode=mode, header_only=header_only):
                    history = [message("user", "Inspect")]
                    if not header_only:
                        history.insert(0, {"type": "additional_tools", "role": "developer",
                                           "tools": [{"type": "web_search"}]})
                    headers = {"x-openai-internal-codex-responses-lite": "true"} if header_only else {}
                    with mock.patch.object(jev, "native_dry", return_value="quota"), mock.patch.object(
                        jev, "fallback_candidates", return_value=["fixture/fallback"],
                    ) as candidates, self.assertRaises(urllib.error.HTTPError) as error:
                        self.call(payload_for(history, model=mode, reasoning={"effort": "medium"}), headers)
                    self.assertEqual(error.exception.code, 503)
                    self.assertIn("Responses-lite", error.exception.read().decode())
                    error.exception.close()
                    candidates.assert_not_called()
                    self.assertEqual(Edge.payloads, [])

    def test_lite_observed_quota_rejects_external_retry(self) -> None:
        def limited(edge: Edge) -> None:
            body = json.loads(edge.rfile.read(int(edge.headers["Content-Length"])))
            Edge.payloads.append(body)
            raw = b'{"error":{"code":"usage_limit_reached","message":"usage limit reached"}}'
            edge.send_response(429)
            edge.send_header("Content-Type", "application/json")
            edge.send_header("Content-Length", str(len(raw)))
            edge.end_headers()
            edge.wfile.write(raw)

        history = [{"type": "additional_tools", "role": "developer",
                    "tools": [{"type": "function", "name": "spawn_agent"}]},
                   message("user", "Inspect")]
        with mock.patch.object(Edge, "do_POST", new=limited), mock.patch.object(
            jev, "fallback_candidates", return_value=["fixture/fallback"],
        ) as candidates, mock.patch.object(jev, "mark_native_dry"), self.assertRaises(urllib.error.HTTPError) as error:
            self.call(payload_for(history), {"x-openai-internal-codex-responses-lite": "true"})
        self.assertEqual(error.exception.code, 503)
        self.assertIn("Responses-lite", error.exception.read().decode())
        error.exception.close()
        candidates.assert_not_called()
        self.assertEqual(len(Edge.payloads), 1)
        self.assertIn(Edge.payloads[0]["model"], jev.TIERS)
        self.assertEqual(Edge.payloads[0]["input"], history)

    def test_unknown_route_rejected_before_judge(self) -> None:
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.server.server_address[1]}/v1/responses",
            data=json.dumps(payload_for([message("user", "Inspect")], model="other")).encode(),
            headers={"Authorization": "Bearer fixture-local", "Content-Type": "application/json"},
        )
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request)
        self.assertEqual(error.exception.code, 400)
        error.exception.close()
        self.judge.assert_not_called()


if __name__ == "__main__":
    unittest.main()
