"""Adaptive planning judgments and bounded executor guidance."""
import copy

from routing_policy import QUESTIONS, _validated_choice

PLAN_QUESTION_MAX_CHARS = 6500
PLAN_GUIDANCE_MAX_CHARS = 1800

REVIEW_PROFILES = {
    "none": "Clerical change to an accepted plan, with no substantive design or risk change.",
    "independent": (
        "Substantive plan: challenge assumptions, acceptance, dependencies and risks "
        "independently before treating the plan as complete."
    ),
    "parallel": (
        "Substantive plan with separable technical concerns where parallel independent "
        "reviews improve coverage; only when delegation is authorized and supported."
    ),
}


def planning_questions() -> dict:
    """Preserve the default question budget; extend only native Plan requests."""
    questions = copy.deepcopy(QUESTIONS)
    questions["model"]["instructions"] += (
        " Native Plan mode prioritizes robust planning quality. Substantive uncertain "
        "design needs strong capability; trivial clerical changes to an accepted plan "
        "can use a lighter model. Retain mandatory Astra architecture/final/risk policy. "
        "Do not equate every plan with architecture."
    )
    questions["effort"]["instructions"] += (
        " For substantive planning assess uncertainty, interacting constraints, alternatives "
        "and failure impact; use high or greater when useful. Clerical plan edits can "
        "use low. Select max only when additional depth is justified."
    )
    questions["planning_review"] = {
        "type": "choice",
        "instructions": (
            "Select the plan completion review need. None is only for clerical edits to "
            "an accepted plan. Substantive work requires independent scrutiny; parallel "
            "is a recommendation conditional on user authorization and available tools. "
            "This answer never establishes that a review was performed."
        ),
        "criteria": REVIEW_PROFILES,
    }
    return questions


def planning_review(answers: object) -> str:
    """Missing or malformed review judgments never waive substantive scrutiny."""
    try:
        selected, _, _ = _validated_choice(answers, "planning_review", REVIEW_PROFILES)
        return selected
    except ValueError:
        return "independent"


def planning_guidance(review: str) -> dict:
    """Recommend bounded completion checks without granting execution authority."""
    text = (
        "<jev_planning_guidance>\n"
        f"Recommended planning review: {review}. This is guidance, not evidence of review. "
        "Before finalizing a substantive plan, check goals, explicit acceptance criteria, "
        "assumptions, dependencies, alternatives, failure risks and verification steps. "
        "Keep the smallest viable scope and explicit non-goals. Present ordered implementation "
        "steps, their dependencies and per-step acceptance and verification. "
        "Identify unresolved decisions rather than asserting completion. Independent "
        "scrutiny is required for substantive work even if the recommendation is none. "
        "For parallel review, delegate only when user/runtime rules authorize it and "
        "tools exist; otherwise perform local critical review and disclose its limitation. "
        "Use distinct bounded perspectives such as architecture, implementation, "
        "verification/risk and scope simplification only when relevant. Consolidate "
        "findings into one coherent plan; agent count is not a quality target. "
        "Respect Plan read-only rules; do not implement before native Plan approval. "
        "Respect user constraints and mandatory review gates. "
        "Do not claim an independent reviewer participated unless observed.\n"
        "</jev_planning_guidance>"
    )
    return {"type": "message", "role": "developer",
            "content": [{"type": "input_text", "text": text}]}
