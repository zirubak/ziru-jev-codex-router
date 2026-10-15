"""Explicit serving speed is a user control, never a Jev judgment."""


def requested_speed(payload: dict, fixed_model: str | None) -> str:
    if not fixed_model:
        return "default"
    tier = payload.get("service_tier")
    if tier is None or tier == "default":
        return "default"
    if isinstance(tier, str) and tier in ("fast", "priority"):
        return "priority"
    raise ValueError("fixed route service_tier must be default, fast or priority")


def served_speed(response: dict | None) -> str | None:
    tier = response.get("service_tier") if isinstance(response, dict) else None
    return tier if isinstance(tier, str) and tier in ("default", "fast", "priority") else None
