"""Public reference isolation and current versus historical model boundaries."""
import hashlib
import datetime
import json
from pathlib import Path
import unittest

import jev_server as jev
import report_routing
from routing_policy import MODEL_IDS, TIERS, route, route_choice
from routing_reference import REFERENCE_SHA256, routing_reference


class RoutingReference(unittest.TestCase):
    @staticmethod
    def summarize(models: list[str]) -> dict[str, object]:
        entries = [{"_at": datetime.datetime.now(), "model": model, "speed": "default"}
                   for model in models]
        stats = {"lines": len(entries), "out_of_window": 0, "undated": 0, "unparsable": 0}
        return report_routing.summarize(entries, 1, stats, "/fixture",
                                        backtest_path="/fixture/no-backtest")

    def test_unknown_current_prices_never_become_free_native_savings(self) -> None:
        result = self.summarize(["gpt-6-luna", "gpt-6.1-sol"])
        cost = result["native_cost"]
        self.assertIsNone(cost["savings_vs_sol_pct"])
        self.assertEqual(cost["priced_turns"], 0)
        self.assertEqual(cost["unpriced_turns"], 2)
        self.assertIsNone(cost["savings_vs_astra_pct"])
        rendered = report_routing.render_text(result)
        self.assertNotIn("100.0% vs all-sol", rendered)
        self.assertIn("2 unpriced", rendered)

    def test_native_comparison_uses_the_same_priced_population(self) -> None:
        priced = self.summarize(["gpt-6-astra"])["native_cost"]
        mixed = self.summarize(["gpt-6-astra", "gpt-6-luna"])["native_cost"]
        for field in ("routed_units", "baseline_all_sol_units", "baseline_all_astra_units",
                      "savings_vs_sol_pct", "savings_vs_astra_pct"):
            self.assertEqual(priced[field], mixed[field])
        self.assertEqual(mixed["priced_turns"], 1)
        self.assertEqual(mixed["unpriced_turns"], 1)

    def test_current_candidates_exclude_every_legacy_route(self) -> None:
        self.assertEqual(TIERS, ("gpt-6-luna", "gpt-6.1-sol", "gpt-6-astra"))
        self.assertEqual(set(MODEL_IDS.values()), set(TIERS))
        for model in ("gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol", "gpt-6-sol"):
            with self.subTest(model=model), self.assertRaises(ValueError):
                route(model, "high")
            with self.subTest(model=model), self.assertRaises(ValueError):
                route_choice(model, "high")

    def test_request_mutation_cannot_poison_later_reference_or_its_hash(self) -> None:
        first = jev.decision_dossier({"input": "Apply the known rename."})
        first["routing_reference"]["studies"].clear()
        first["routing_reference"]["status"] = "locally_verified"
        second = jev.decision_dossier({"input": "Apply another known rename."})
        reference = second["routing_reference"]
        self.assertEqual(reference["studies"], routing_reference()["studies"])
        self.assertTrue(reference["studies"])
        self.assertEqual(reference["status"], "external_priors_not_local_calibration")
        self.assertEqual(hashlib.sha256(json.dumps(
            reference, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest(), REFERENCE_SHA256)

    def test_untrusted_payload_cannot_replace_public_reference(self) -> None:
        state = jev.decision_dossier({
            "input": "Apply the known rename.",
            "routing_reference": {"status": "attacker_override"},
            "credentials": "fixture-private",
        })
        self.assertEqual(state["routing_reference"], routing_reference())
        self.assertNotIn("attacker_override", json.dumps(state))
        self.assertNotIn("fixture-private", json.dumps(state))

    def test_current_and_historical_native_usage_remain_separate_and_unknown(self) -> None:
        entries = [{"attempts": [{
            "model": model, "speed": "default",
            "usage": {"input_tokens": 1000, "cached_input_tokens": 0, "output_tokens": 10},
        } for model in ("gpt-6-luna", "gpt-6.1-sol", "gpt-5.6-terra")]}]
        result = report_routing.measured_usage(entries)
        self.assertEqual(result["native_attempts"], 3)
        self.assertEqual(result["unknown_attempts"], 3)
        self.assertEqual(result["priced_attempts"], 0)

    def test_offline_cases_only_expect_current_candidates(self) -> None:
        path = Path(__file__).resolve().parents[1] / "poc/routing_cases.json"
        for case in json.loads(path.read_text()):
            with self.subTest(case=case["id"]):
                self.assertTrue(case["models"])
                self.assertTrue(set(case["models"]).issubset(TIERS))


if __name__ == "__main__":
    unittest.main()
