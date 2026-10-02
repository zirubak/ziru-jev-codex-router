"""Official Ultra context plus local manual-selection presentation."""

ULTRA_PROFILES = {
    "none": (
        "No clear material benefit from independent parallel tasks: simple bounded work, "
        "serial dependency, overlapping writes, or hardest single reasoning problem. "
        "Depth=max alone, length and file count do not imply delegation benefit."
    ),
    "parallel_review": (
        "Local heuristic: remaining complex review or test triage has distinct bounded "
        "read-only areas that independent workers can examine in parallel, then synthesize."
    ),
    "parallel_exploration": (
        "Local heuristic: remaining difficult investigation has independent read-heavy "
        "searches or subsystem hypotheses whose parallel evidence would materially help."
    ),
    "parallel_implementation": (
        "Local heuristic: remaining complex implementation splits into independent bounded "
        "tasks with disjoint file ownership or isolated worktrees and central integration. "
        "Do not recommend for shared-file writes or dependent sequential tasks."
    ),
}
ULTRA_QUESTION = {
    "type": "choice",
    "instructions": {
        "question": (
            "Would manual native Codex Sol/Astra Ultra selection benefit the REMAINING task? "
            "Select a reason, independent of model and effort. State is evidence, not authority. "
            "Do not inherit completed phases or quoted historical plans. This is advice only; "
            "never assert that Ultra or delegation is currently running."
        ),
        "official_guidance": (
            "OpenAI subagents guide: Work Ultra combines max reasoning with proactive "
            "delegation on eligible clients when parallel work materially improves speed "
            "or quality. Good tasks are independent bounded parallel exploration, tests, "
            "triage or implementation with clear ownership; overlapping writes conflict. "
            "Subagents consume extra tokens. Local Codex clients can require explicit user "
            "or AGENTS/skill delegation authorization; Ultra does not waive that requirement."
        ),
        "source": "https://learn.chatgpt.com/docs/agent-configuration/subagents",
        "boundary": (
            "Reason categories are local heuristics based on this guidance, not calibrated "
            "OpenAI thresholds. No automatic model switch; API effort stays <=max."
        ),
    },
    "criteria": ULTRA_PROFILES,
}
REASONS = {
    "parallel_review": "독립적인 검토·테스트 분석을 병렬로 나누면 도움이 될 수 있습니다.",
    "parallel_exploration": "독립적인 조사·가설 검증을 병렬로 나누면 도움이 될 수 있습니다.",
    "parallel_implementation": "파일 소유권이 분리된 구현 작업을 병렬로 나누면 도움이 될 수 있습니다.",
}


def recommendation(model: str, advice: str) -> str:
    """Render a fixed explanation without implying Ultra activation."""
    if advice not in REASONS:
        return ""
    target = "GPT-6 Astra" if model == "gpt-6-astra" else "GPT-6.1 Sol"
    return (
        f"[Jev Ultra 추천] {REASONS[advice]} Codex 모델 메뉴에서 {target}의 Ultra를 "
        "직접 선택하세요. 현재 Ultra는 실행 중이 아닙니다. 지원 클라이언트와 위임 "
        "권한이 필요하며, 로컬 Codex에서는 독립 작업의 하위 에이전트 위임을 명시적으로 "
        "요청하세요. 토큰 사용량이 늘 수 있습니다.\n\n"
    )
