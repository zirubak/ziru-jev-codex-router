"""Small, dated public evidence; never account calibration or executable policy."""
import copy
import hashlib
import json

_REFERENCE: dict[str, object] = {
    "version": "research-20261001-v2",
    "checked_at": "2026-10-01",
    "status": "external_priors_not_local_calibration",
    "objective": "Meet software acceptance and control failure risk; minimize project-wide "
    "tokens including reasoning, tools, routing, reviews and rework. Never omit required checks.",
    "bounds": [
        "External priors, not calibrated on this user's code. Judge remaining work and "
        "observed failures; missing requirements/tests stay unknown.",
        "Match model+effort+task+harness+verifier. No cross-generation score transfer. "
        "Effort is adaptive, not fixed tokens or equal compute across models.",
        "Compare acceptance, regressions, scope, rework and total time. "
        "API prices are not subscription usage; no local quality/savings proof.",
    ],
    "studies": [
        {
            "id": "official_coding_start",
            "kind": "official_guidance",
            "url": "https://learn.chatgpt.com/docs/models",
            "finding": "Codex starts: Luna high, Astra low, Sol 6.1 client default. "
            "Task-specific lighter settings can suffice. Ultra is a subagent mode.",
            "limit": "Starting points, not fixed floors or measured winners. "
            "Luna low-risk scope is local policy, not a proven ability ceiling.",
        },
        {
            "id": "official_effort",
            "kind": "official_guidance",
            "url": "https://developers.openai.com/api/docs/guides/reasoning",
            "finding": "Medium: agentic planning; high: complex debugging. "
            "Evaluate xhigh gains against time/cost, max against xhigh. "
            "No monotonic quality guarantee.",
        },
        {
            "id": "bug_hunt_20261001",
            "kind": "community_experiment",
            "url": "https://github.com/phuryn/bug-hunt-bench/blob/main/README.md",
            "finding": "105 defects/2 TS repos: Sol 6.1 high/xhigh/max fixed "
            "36.5/42.7/44.3, took 70/99/139 min (n=2/3/3); Astra max 45 (n=3).",
            "limit": "Small repeated CLI sample, model-judged diffs, differing clients. "
            "Minutes sum both repos; no universal ranking.",
        },
        {
            "id": "luna_rewrite",
            "kind": "community_experiment",
            "url": "https://vulcanbench.com/benchmarks/swe-v4-gpt6-luna-v316.html",
            "finding": "23 legacy rewrites, Luna low/medium/high/xhigh/max passed "
            "0/0/2/11/12; xhigh/max timed out 2/4 times at 3h.",
            "limit": "One attempt/task/effort; private prompts/patches. "
            "Task-specific gains and timeout tradeoff, not a default max rule.",
        },
        {
            "id": "overthinking",
            "kind": "paper",
            "url": "https://arxiv.org/html/2502.08235v1",
            "finding": "SWE-bench/OpenHands: o1 high beat low; environment feedback "
            "and tool harness also mattered. Reasoning cannot replace observations.",
            "limit": "Older models; not current effort calibration or proof high is worse.",
        },
        {
            "id": "verifier_limits",
            "kind": "paper",
            "url": "https://arxiv.org/html/2411.17501v3",
            "finding": "HumanEval/MBPP resampling can pass weak tests yet fail expanded "
            "tests. Passing narrow checks alone does not justify a weaker model.",
            "limit": "Resampling is not effort; pass@k is not selected-patch success.",
        },
        {
            "id": "frontiercode_method",
            "kind": "benchmark_methodology",
            "url": "https://cognition.com/frontiercode",
            "finding": "Mergeability includes correctness, test quality, scope, style "
            "and repo standards; methodology only, no model winner.",
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
