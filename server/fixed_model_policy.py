"""Jev determines depth within a model boundary already chosen by the user."""
import copy

from routing_policy import (EFFORTS, LEASE_PROFILES, MODEL_IDS, MODEL_PROFILES,
                            POLICY_VERSION, QUESTIONS, _validated_choice)
from routing_reference import REFERENCE_SHA256, REFERENCE_VERSION


def fixed_questions() -> dict:
    """Only judgments that can affect this route are sent to TypeSafe."""
    questions = {name: copy.deepcopy(QUESTIONS[name]) for name in ("effort", "lease")}
    questions["effort"]["instructions"] += (
        " The user selected state.fixed_model and its fixed_model_profile. "
        "Choose depth for this exact model; model selection is not available. "
        "Higher effort does not replace required checks or missing capability."
    )
    return questions


def fixed_profile(model: str) -> str:
    return MODEL_PROFILES[next(key for key, value in MODEL_IDS.items() if value == model)]


def fixed_decision(answers: object, model: str) -> dict:
    """Ignore legacy model answers rather than falsely attributing user choice."""
    effort, effort_probs, effort_conf = _validated_choice(answers, "effort", EFFORTS)
    lease, lease_probs, lease_conf = _validated_choice(answers, "lease", LEASE_PROFILES)
    confidences = [value for value in (effort_conf, lease_conf) if value is not None]
    probabilities = [probs[choice] for probs, choice in
                     ((effort_probs, effort), (lease_probs, lease)) if probs is not None]
    return {
        "model": model, "base_model": model, "astra_policy": None,
        "effort": effort, "lease": lease, "speed": "default", "gate": "apply",
        "confidence": min(confidences) if confidences else None,
        "probabilities": {"effort": effort_probs, "lease": lease_probs},
        "chosen_probability": min(probabilities) if probabilities else None,
        "policy_version": POLICY_VERSION,
        "reference_version": REFERENCE_VERSION, "reference_sha256": REFERENCE_SHA256,
    }
