"""Small, dated public evidence; never account calibration or executable policy."""
import copy
import hashlib
import json

_REFERENCE: dict[str, object] = {
    "version": "research-20261027-terra-v3",
    "checked_at": "2026-10-27",
    "status": "external_priors_not_local_calibration",
    "objective": "Meet acceptance/control failure risk; minimize project-wide "
    "tokens including reasoning/tools/routing/reviews/rework. Never omit required checks.",
    "bounds": [
        "External priors, not calibrated locally. Judge remaining work and "
        "failures; missing requirements/tests stay unknown.",
        "Match model/effort/task/harness/verifier. No cross-generation transfer. "
        "Effort is not equal compute across models.",
        "Compare acceptance/regressions/scope/rework/time. "
        "API prices are not subscription usage; no local quality/savings proof.",
    ],
    "studies": [
        {
            "id": "luna_rewrite",
            "kind": "community_experiment",
            "url": "https://vulcanbench.com/benchmarks/swe-v4-gpt6-luna-v316.html",
            "finding": "23 rewrites: Luna low/medium/high/xhigh/max passed 0/0/2/11/12.",
            "limit": "Single attempts, private tasks; xhigh/max timed out 2/4 times at 3h.",
        },
        {
            "id": "frontiercode_method",
            "kind": "benchmark_methodology",
            "url": "https://cognition.com/frontiercode",
            "finding": "Mergeability includes correctness, tests, scope/style; no model winner.",
        },
        {
            "id": "terra_61_visual",
            "kind": "official_evaluation",
            "url": "https://openai.com/index/introducing-gpt-6-1-terra/",
            "finding": "Terra 6.1: detailed visual reasoning/computer use; evaluations include "
            "drawings to 3D models.",
            "limit": "Aggregate benchmarks, no Blender/SolidCraft-specific or local geometry-quality proof. "
            "Keep native reopening, geometry and export verification.",
        },
        {
            "id": "official_coding_start",
            "kind": "official_guidance",
            "url": "https://learn.chatgpt.com/docs/models",
            "finding": "Codex starts: Luna high, Astra low, Sol 6.1 client default. "
            "Lighter settings may suffice.",
            "limit": "Starting points, not fixed floors or measured winners. "
            "Luna low-risk scope is local policy.",
        },
        {
            "id": "official_effort",
            "kind": "official_guidance",
            "url": "https://developers.openai.com/api/docs/guides/reasoning",
            "finding": "Medium: agentic planning; high: debugging. "
            "Evaluate xhigh time/cost gains, max vs xhigh. "
            "No monotonic quality guarantee.",
        },
        {
            "id": "bug_hunt_20261001",
            "kind": "community_experiment",
            "url": "https://github.com/phuryn/bug-hunt-bench/blob/main/README.md",
            "finding": "105 defects/2 repos: Sol 6.1 high/xhigh/max fixed "
            "36.5/42.7/44.3, took 70/99/139 min (n=2/3/3); Astra max 45 (n=3).",
            "limit": "Small CLI sample, model-judged diffs. "
            "No universal ranking.",
        },
        {
            "id": "overthinking",
            "kind": "paper",
            "url": "https://arxiv.org/html/2502.08235v1",
            "finding": "SWE-bench/OpenHands: o1 high beat low; feedback "
            "and harness mattered.",
            "limit": "Older models, not current calibration.",
        },
        {
            "id": "verifier_limits",
            "kind": "paper",
            "url": "https://arxiv.org/html/2411.17501v3",
            "finding": "HumanEval/MBPP resampling can pass weak yet fail expanded "
            "tests. Narrow checks alone cannot justify weaker models.",
            "limit": "Resampling is not effort; pass@k is not patch success.",
        },
    ],
}

REFERENCE_VERSION = str(_REFERENCE["version"])
REFERENCE_SHA256 = hashlib.sha256(
    json.dumps(_REFERENCE, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()


def routing_reference() -> dict[str, object]:
    """Give each dossier its own copy so caller mutations cannot poison later calls."""
    return copy.deepcopy(_REFERENCE)
