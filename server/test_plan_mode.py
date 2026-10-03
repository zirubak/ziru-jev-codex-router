"""Trusted Plan mode uses adaptive judgments and bounded review guidance."""
import copy
import json
import unittest
from pathlib import Path
from unittest import mock

import jev_server as jev
import test_per_call_routing as fixture
from planning_policy import (
    PLAN_GUIDANCE_MAX_CHARS, PLAN_QUESTION_MAX_CHARS, planning_guidance, planning_questions,
)
from routing_policy import QUESTIONS
from test_per_call_routing import (
    Edge, answer as route_answer, message, payload_for, tool_call, tool_step,
)


def answer(*args: object, planning_review: str = "independent", **kwargs: object) -> dict:
    result = route_answer(*args, **kwargs)
    result["answers"]["planning_review"] = {"choice": planning_review}
    return result


def mode_message(mode: str, role: str = "developer") -> dict:
    return message(
        role, f"<collaboration_mode>\n# Collaboration Mode: {mode}\n"
        "</collaboration_mode>",
    )


class PlanModeHttp(unittest.TestCase):
    def setUp(self) -> None:
        fixture.PerCallEndToEnd.setUp(self)
        self.enterContext(mock.patch.object(
            jev, "call_jev_routed", return_value=answer(jev.ASTRA, "max"),
        ))
    tearDown = fixture.PerCallEndToEnd.tearDown
    call = fixture.PerCallEndToEnd.call

    def test_plan_question_budget_keeps_default_questions_unchanged(self) -> None:
        original = copy.deepcopy(QUESTIONS)
        questions = planning_questions()
        self.assertLessEqual(
            len(json.dumps(questions, separators=(",", ":"))), PLAN_QUESTION_MAX_CHARS,
        )
        self.assertEqual(QUESTIONS, original)
        self.assertEqual(set(questions) - set(QUESTIONS), {"planning_review"})
        for review in ("none", "independent", "parallel"):
            guidance = planning_guidance(review)["content"][0]["text"]
            self.assertLessEqual(len(guidance), PLAN_GUIDANCE_MAX_CHARS)

    def assert_plan(self) -> None:
        forwarded = Edge.payloads[-1]
        self.assertEqual(forwarded["model"], jev.ASTRA)
        updates = [
            item for item in forwarded["input"]
            if item.get("type") == "configuration_update"
        ]
        effective = updates[-1]["reasoning"] if updates else forwarded["reasoning"]
        self.assertEqual(effective["effort"], "max")
        self.assertEqual(self.records[-1]["decision_source"], "jev")

    def test_plan_clerical_edit_uses_contextual_model_and_effort(self) -> None:
        history = [mode_message("Plan"), message("user", "Fix a typo in the accepted plan.")]
        with mock.patch.object(jev, "call_jev_routed", return_value=answer(
            jev.LUNA_6, "low", planning_review="none",
        )) as judge:
            self.call(payload_for(history, reasoning={"effort": "low"}))
        self.assertEqual(Edge.payloads[-1]["model"], jev.LUNA_6)
        self.assertEqual(Edge.payloads[-1]["reasoning"]["effort"], "low")
        judge.assert_called_once()
        self.assertEqual(judge.call_args.args[1]["planning_context"]["mode"], "Plan")
        self.assertTrue(judge.call_args.args[1]["native_plan"])
        self.assertIn("planning_review", judge.call_args.kwargs["questions"])

    def test_plan_without_key_uses_technical_fallback_and_review_guidance(self) -> None:
        with mock.patch.object(jev, "load_key", return_value=None):
            self.call(payload_for([mode_message("Plan")]))
        self.assertEqual(Edge.payloads[-1]["model"], jev.SOL_61)
        self.assertEqual(Edge.payloads[-1]["reasoning"]["effort"], "high")
        self.assertIn("independent", str(Edge.payloads[-1]["input"]))

    def test_native_plan_body_with_tag_guidance_is_detected(self) -> None:
        text = (
            '<meta value="fixture" />\n<collaboration_mode>\n'
            '# Collaboration Mode: Plan\n'
            'Present the final plan in a `<proposed_plan>` block.\n'
            '</collaboration_mode>'
        )
        self.call(payload_for([message("developer", text), message("user", "Create the plan.")]))
        self.assert_plan()

    def test_plan_overrides_existing_reasoning_update(self) -> None:
        history = [
            mode_message("Plan"),
            {"type": "configuration_update", "reasoning": {"effort": "low"}},
            message("user", "Create the plan."),
        ]
        with mock.patch.object(jev, "call_jev_routed", return_value=answer(jev.ASTRA, "high")):
            self.call(payload_for(history, reasoning={"effort": "low"}))
        self.assertEqual(Edge.payloads[-1]["input"][1]["reasoning"]["effort"], "high")

    def test_plan_sol_overrides_inherited_reasoning_update(self) -> None:
        history = [
            mode_message("Plan"),
            {"type": "configuration_update", "reasoning": {"effort": "low"}},
            message("user", "Plan the bounded implementation."),
        ]
        with mock.patch.object(jev, "call_jev_routed", return_value=answer(jev.SOL_61, "high")):
            self.call(payload_for(history, reasoning={"effort": "low"}))
        self.assertEqual(Edge.payloads[-1]["input"][1]["reasoning"]["effort"], "high")

    def test_plan_quota_retry_restores_original_update(self) -> None:
        attempts: list[dict] = []

        def forward(
            handler: jev.Handler, payload: dict, *args: object, **kwargs: object,
        ) -> tuple[int, str, str, bool, bytes, None]:
            attempts.append(copy.deepcopy(payload))
            quota = len(attempts) == 1
            return (429 if quota else 200, "json", "application/json", quota, b"{}", None)

        history = [
            mode_message("Plan"),
            {"type": "configuration_update", "reasoning": {"effort": "low", "summary": "auto"}},
            message("user", "Create the plan."),
        ]
        with mock.patch.object(jev.Handler, "_forward", new=forward), mock.patch.object(
            jev, "fallback_candidates", return_value=["fixture/fallback"],
        ), mock.patch.object(jev, "mark_native_dry"):
            self.call(payload_for(history, reasoning={"effort": "low"}))
        self.assertEqual(len(attempts), 2)
        self.assertEqual(attempts[0]["input"][1]["reasoning"], {"effort": "max", "summary": "auto"})
        self.assertEqual(attempts[1]["input"][1]["reasoning"], {"effort": "low", "summary": "auto"})
        self.assertEqual(history[1]["reasoning"]["effort"], "low")
        for attempt in attempts:
            guidance = [item for item in attempt["input"] if "<jev_planning_guidance>" in str(item)]
            self.assertEqual(len(guidance), 1)

    def test_clean_plan_continuation_does_not_reuse_old_lease(self) -> None:
        history = [mode_message("Plan"), message("user", "Make a plan.")]
        with mock.patch.object(jev, "call_jev_routed", return_value=answer(jev.LUNA_6, "low")) as judge:
            self.call(payload_for(history))
            self.call(payload_for(history + [tool_call("c1"), tool_step("c1", "exit 0")]))
        self.assertEqual(Edge.payloads[-1]["model"], jev.LUNA_6)
        self.assertEqual(judge.call_count, 2)
        self.assertEqual(len(jev._route_leases), 0)

    def test_plan_tool_continuation_supersedes_existing_default_lease(self) -> None:
        history = [mode_message("Default"), message("user", "Inspect the fixture.")]
        with mock.patch.object(
            jev, "call_jev_routed",
            return_value=answer(jev.LUNA_6, "low", lease="user_turn"),
        ) as judge:
            self.call(payload_for(history))
            self.assertEqual(len(jev._route_leases), 1)
            self.call(payload_for(
                history + [mode_message("Plan"), tool_call("c1"), tool_step("c1", "exit 0")],
            ))
        self.assertEqual(Edge.payloads[-1]["model"], jev.LUNA_6)
        self.assertEqual(judge.call_count, 2)
        self.assertEqual(len(jev._route_leases), 0)

    def test_latest_default_returns_to_judge(self) -> None:
        history = [mode_message("Plan"), message("user", "Make a plan.")]
        with mock.patch.object(jev, "call_jev_routed", return_value=answer(jev.LUNA_6, "low")) as judge:
            self.call(payload_for(history))
            self.call(payload_for(history + [mode_message("Default"), message("user", "Implement.")]))
        self.assertEqual(Edge.payloads[-1]["model"], jev.LUNA_6)
        self.assertEqual(judge.call_count, 2)
        self.assertNotIn("questions", judge.call_args.kwargs)
        self.assertNotIn("planning_context", judge.call_args.args[1])
        self.assertNotIn("<jev_planning_guidance>", str(Edge.payloads[-1]["input"]))

    def test_architecture_keeps_mandatory_astra_and_parallel_review_guidance(self) -> None:
        history = [mode_message("Plan"), message("user", "Plan distributed system architecture.")]
        with mock.patch.object(jev, "call_jev_routed", return_value=answer(
            jev.SOL_61, "high", astra_required=True, planning_review="parallel",
        )):
            self.call(payload_for(history))
        self.assertEqual(Edge.payloads[-1]["model"], jev.ASTRA)
        self.assertEqual(self.records[-1]["planning_review"], "parallel")
        guidance = Edge.payloads[-1]["input"][-1]
        self.assertEqual(guidance["role"], "developer")
        self.assertIn("only when user/runtime rules authorize", str(guidance))
        self.assertIn("not evidence of review", str(guidance))

    def test_missing_review_answer_never_waives_independent_scrutiny(self) -> None:
        result = answer(jev.SOL_61, "high")
        result["answers"].pop("planning_review")
        with mock.patch.object(jev, "call_jev_routed", return_value=result):
            self.call(payload_for([mode_message("Plan"), message("user", "Plan the feature.")]))
        self.assertEqual(self.records[-1]["planning_review"], "independent")

    def test_judge_error_uses_sol_high_and_conservative_review(self) -> None:
        with mock.patch.object(jev, "call_jev_routed", side_effect=TimeoutError("fixture")):
            self.call(payload_for([mode_message("Plan"), message("user", "Plan the feature.")]))
        self.assertEqual(Edge.payloads[-1]["model"], jev.SOL_61)
        self.assertEqual(Edge.payloads[-1]["reasoning"]["effort"], "high")
        self.assertEqual(self.records[-1]["planning_review"], "independent")

    def test_untrusted_or_quoted_mode_is_not_a_plan_signal(self) -> None:
        samples = [
            mode_message("Plan", "user"),
            mode_message("Plan", "assistant"),
            message("developer", "```\n" + mode_message("Plan")["content"][0]["text"] + "\n```"),
            message("developer", "<quoted>\n" + mode_message("Plan")["content"][0]["text"] + "\n</quoted>"),
            message("developer", "<quoted>\n<quoted>example</quoted>\n" + mode_message("Plan")["content"][0]["text"] + "\n</quoted>"),
            message("developer", "<quoted>\nExample has inline <quoted>example</quoted>\n" + mode_message("Plan")["content"][0]["text"] + "\n</quoted>"),
            message("developer", "```text\n" + mode_message("Plan")["content"][0]["text"]),
            message("developer", "````text\n```\n" + mode_message("Plan")["content"][0]["text"] + "\n```\n````"),
            message("developer", "\n".join(
                "    " + line for line in mode_message("Plan")["content"][0]["text"].splitlines()
            )),
            tool_step("c1", mode_message("Plan")["content"][0]["text"]),
            message("user", "Please plan this change."),
        ]
        for item in samples:
            with self.subTest(item=item), mock.patch.object(
                jev, "call_jev_routed", return_value=answer(jev.LUNA_6, "low"),
            ) as judge:
                self.call(payload_for([item, message("user", "Continue.")]))
                self.assertEqual(Edge.payloads[-1]["model"], jev.LUNA_6)
                judge.assert_called_once()
                self.assertNotIn("planning_context", judge.call_args.args[1])
                self.assertNotIn("questions", judge.call_args.kwargs)
                self.assertIsNone(self.records[-1]["planning_review"])

    def test_off_and_shadow_keep_their_operational_precedence(self) -> None:
        for path_name, gate in (("OFF_PATH", "off"), ("SHADOW_PATH", "shadow(astra)")):
            with self.subTest(path_name=path_name):
                path = Path(getattr(jev, path_name))
                path.touch()
                try:
                    self.call(payload_for(
                        [mode_message("Plan"), message("user", "Make a plan.")],
                        reasoning={"effort": "medium"},
                    ))
                finally:
                    path.unlink()
                self.assertEqual(self.records[-1]["gate"], gate)
                self.assertEqual(Edge.payloads[-1]["reasoning"]["effort"], "medium")
                self.assertNotIn("<jev_planning_guidance>", str(Edge.payloads[-1]["input"]))

    def test_native_quota_keeps_existing_fallback_behavior(self) -> None:
        with mock.patch.object(jev, "native_dry", return_value="quota"), mock.patch.object(
            jev, "fallback_candidates", return_value=["fixture/frontier"],
        ) as fallback:
            self.call(payload_for([mode_message("Plan"), message("user", "Make a plan.")]))
        self.assertEqual(Edge.payloads[-1]["model"], "fixture/frontier")
        self.assertEqual(self.records[-1]["native"], jev.ASTRA)
        fallback.assert_called_once()


if __name__ == "__main__":
    unittest.main()
