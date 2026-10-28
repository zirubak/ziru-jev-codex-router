"""Exact user controls are enforced locally, independently of Jev judgments."""
from dataclasses import dataclass

MANUAL_EFFORTS = ("low", "medium", "high", "xhigh", "max")
AUTO_ROUTES = frozenset({"auto", "jev-auto", "jev/auto"})
MANUAL_ROUTES = frozenset({"manual", "jev-manual", "jev/manual"})
FIXED_ROUTES = {
    alias: model
    for slug, model in (("sol", "gpt-6.1-sol"), ("astra", "gpt-6-astra"))
    for alias in (slug, f"jev-{slug}", f"jev/{slug}")
}
SELECTION_POLICY_VERSION = "split-v22-terra-visual-modeling"


@dataclass(frozen=True)
class Selection:
    mode: str
    user_effort: str | None = None
    fixed_model: str | None = None

    def state(self) -> dict:
        result = {"selection_mode": self.mode}
        if self.user_effort is not None:
            result["user_effort"] = self.user_effort
        if self.fixed_model is not None:
            result.update(fixed_model=self.fixed_model, model_source="user")
        return result


def resolve_selection(payload: dict) -> Selection:
    """Validate explicit effort before either inference or model execution."""
    route = payload.get("model", "auto")
    if isinstance(route, str) and route in AUTO_ROUTES:
        return Selection("auto")
    if isinstance(route, str) and route in FIXED_ROUTES:
        return Selection("fixed", fixed_model=FIXED_ROUTES[route])
    if not isinstance(route, str) or route not in MANUAL_ROUTES:
        raise ValueError("unknown Jev selection route")
    reasoning = payload.get("reasoning")
    if reasoning is not None and not isinstance(reasoning, dict):
        raise ValueError("manual reasoning must be an object")
    effort = reasoning.get("effort", "medium") if isinstance(reasoning, dict) else "medium"
    if not isinstance(effort, str) or effort not in MANUAL_EFFORTS:
        raise ValueError("manual effort must be low, medium, high, xhigh or max")
    return Selection("manual", effort)


def selection_scope(payload: dict) -> str:
    selection = resolve_selection(payload)
    return f"{selection.mode}:{selection.fixed_model or selection.user_effort or ''}"


def normalized_updates(items: list, effort: str) -> list:
    """Configuration updates cannot silently override an explicit effort."""
    return [
        {**item, "reasoning": {**(item.get("reasoning") or {}), "effort": effort}}
        if isinstance(item, dict) and item.get("type") == "configuration_update"
        and isinstance(item.get("reasoning", {}), dict) else item
        for item in items
    ]
