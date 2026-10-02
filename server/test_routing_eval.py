"""Routing samples check effort and retain the evidence needed to interpret results."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from routing_policy import EFFORTS, TIERS
from routing_reference import REFERENCE_SHA256, REFERENCE_VERSION


EVAL_PATH = Path(__file__).resolve().parents[1] / "poc/eval_routing.py"
SPEC = importlib.util.spec_from_file_location("routing_eval", EVAL_PATH)
routing_eval = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(routing_eval)


class RoutingEval(unittest.TestCase):
    def run_sample(self, case: dict[str, object], decision: dict[str, str]
                   ) -> tuple[int, list[dict[str, object]]]:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cases.json"
            path.write_text(json.dumps([case]), encoding="utf-8")
            output = io.StringIO()
            with (mock.patch.object(sys, "argv", [str(EVAL_PATH), "--live", "--cases", str(path)]),
                  mock.patch.object(routing_eval.jev, "load_key", return_value="fixture-key"),
                  mock.patch.object(routing_eval.jev, "call_jev_routed", return_value={}),
                  mock.patch.object(routing_eval.jev, "decision_from_answers", return_value=decision),
                  contextlib.redirect_stdout(output)):
                code = routing_eval.main()
        return code, [json.loads(line) for line in output.getvalue().splitlines()]

    @staticmethod
    def sample_case() -> dict[str, object]:
        return {"id": "mechanical", "input": "Apply the approved rename.",
                "models": ["gpt-6-luna"], "policy": "normal", "efforts": ["low", "medium"]}

    @staticmethod
    def sample_decision() -> dict[str, str]:
        return {"model": "gpt-6-luna", "effort": "low", "astra_policy": "normal"}

    def test_live_rejects_effort_outside_case_expectation(self) -> None:
        decision = self.sample_decision() | {"effort": "max"}
        code, rows = self.run_sample(self.sample_case(), decision)
        self.assertEqual(code, 1)
        self.assertFalse(rows[0]["passed"])
        self.assertEqual(rows[-1]["passed"], 0)

    def test_live_accepts_each_effort_in_case_expectation(self) -> None:
        for effort in ("low", "medium"):
            with self.subTest(effort=effort):
                code, rows = self.run_sample(self.sample_case(),
                                             self.sample_decision() | {"effort": effort})
                self.assertEqual(code, 0)
                self.assertTrue(rows[0]["passed"])

    def test_legacy_case_without_efforts_remains_compatible(self) -> None:
        case = self.sample_case()
        del case["efforts"]
        code, rows = self.run_sample(case, self.sample_decision() | {"effort": "max"})
        self.assertEqual(code, 0)
        self.assertTrue(rows[0]["passed"])

    def test_model_and_policy_expectations_remain_required(self) -> None:
        for change in ({"model": "gpt-6-astra"}, {"astra_policy": "astra"}):
            with self.subTest(change=change):
                code, rows = self.run_sample(self.sample_case(), self.sample_decision() | change)
                self.assertEqual(code, 1)
                self.assertFalse(rows[0]["passed"])

    def test_expectation_helper_allows_omitted_policy_and_efforts(self) -> None:
        self.assertTrue(routing_eval.matches_expectations(
            self.sample_decision(), {"id": "legacy", "input": [], "models": ["gpt-6-luna"]}))

    def test_expectation_helper_does_not_treat_empty_efforts_as_omitted(self) -> None:
        self.assertFalse(routing_eval.matches_expectations(
            self.sample_decision(),
            {"id": "empty", "input": [], "models": ["gpt-6-luna"], "efforts": []}))

    def test_bundled_cases_have_valid_efforts_and_local_rationale(self) -> None:
        cases = json.loads(EVAL_PATH.with_name("routing_cases.json").read_text(encoding="utf-8"))
        self.assertEqual(len({case["id"] for case in cases}), len(cases))
        for case in cases:
            with self.subTest(case=case["id"]):
                self.assertTrue(case["efforts"])
                self.assertTrue(set(case["efforts"]).issubset(EFFORTS))
                self.assertTrue(set(case["models"]).issubset(TIERS))
                self.assertTrue(case["rationale"].strip())

    def test_live_records_reference_identity_and_interpretation_limit(self) -> None:
        _, rows = self.run_sample(self.sample_case(), self.sample_decision())
        for row in rows:
            self.assertEqual(row["reference_version"], REFERENCE_VERSION)
            self.assertEqual(row["reference_sha256"], REFERENCE_SHA256)
        self.assertEqual(rows[-1]["note"],
                         "classification regression sample, not local calibration or executor quality")

    def test_live_records_typed_validation_failure_without_raw_answers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cases.json"
            path.write_text(json.dumps([self.sample_case()]), encoding="utf-8")
            output = io.StringIO()
            with (mock.patch.object(sys, "argv", [str(EVAL_PATH), "--live", "--cases", str(path)]),
                  mock.patch.object(routing_eval.jev, "load_key", return_value="fixture-key"),
                  mock.patch.object(routing_eval.jev, "call_jev_routed",
                                    return_value={"answers": {"untrusted": "fixture-private"}}),
                  contextlib.redirect_stdout(output)):
                code = routing_eval.main()
        row = json.loads(output.getvalue().splitlines()[0])
        self.assertEqual(code, 1)
        self.assertEqual(row["validation_error"], "missing astra_policy decision")
        self.assertNotIn("fixture-private", output.getvalue())


if __name__ == "__main__":
    unittest.main()
