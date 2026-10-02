"""Classification regression samples; --live spends only Jev input credits."""
import argparse
from collections.abc import Mapping
import json
from pathlib import Path
import sys
import time
from typing import NotRequired, TypedDict

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import jev_server as jev


class RoutingCase(TypedDict):
    id: str
    input: object
    models: list[str]
    policy: NotRequired[str]
    efforts: NotRequired[list[str]]
    rationale: NotRequired[str]


def matches_expectations(decision: Mapping[str, object], case: RoutingCase) -> bool:
    """Keep legacy fixtures valid while checking any declared effort expectation."""
    return (decision["model"] in case["models"]
            and ("policy" not in case or decision["astra_policy"] == case["policy"])
            and ("efforts" not in case or decision["effort"] in case["efforts"]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--cases", type=Path, default=Path(__file__).with_name("routing_cases.json"))
    args = parser.parse_args()
    with args.cases.open(encoding="utf-8") as source:
        cases: list[RoutingCase] = json.load(source)
    key = jev.load_key() if args.live else None
    if args.live and not key:
        raise SystemExit("TypeSafe key not configured")
    reference = {"reference_version": jev.REFERENCE_VERSION,
                 "reference_sha256": jev.REFERENCE_SHA256}
    passed = 0
    for case in cases:
        state = jev.decision_dossier({"input": case["input"]})
        row = {"id": case["id"], "dossier_chars": len(json.dumps(state)),
               "policy_version": jev.POLICY_VERSION, **reference}
        if args.live:
            start = time.monotonic()
            try:
                result = jev.call_jev_routed(key, state, timeout=15)
                try:
                    decision = jev.decision_from_answers(result.get("answers"))
                except ValueError as error:
                    # This validator emits fixed contract errors, never raw answer values.
                    row["validation_error"] = str(error)
                    raise
                ok = matches_expectations(decision, case)
                row.update(model=decision["model"], effort=decision["effort"],
                           astra_policy=decision["astra_policy"], passed=ok,
                           input_tokens=(result.get("usage") or {}).get("input_tokens"),
                           ms=round(1000 * (time.monotonic() - start)))
                passed += int(ok)
            except Exception as error:
                row.update(passed=False, error_type=type(error).__name__)
        print(json.dumps(row))
    if args.live:
        print(json.dumps({"passed": passed, "total": len(cases), **reference,
                          "note": "classification regression sample, not local calibration or executor quality"}))
    return int(args.live and passed != len(cases))


if __name__ == "__main__":
    raise SystemExit(main())
