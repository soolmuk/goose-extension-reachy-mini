"""Allowlists and intent mappings for expressions and dances.

This module deliberately exposes stable intent names rather than raw recorded-move
paths or arbitrary keyframe data.
"""

from __future__ import annotations

EXPRESSION_INTENTS = {
    "happy",
    "excited",
    "loving",
    "grateful",
    "success",
    "welcoming",
    "greeting",
    "goodbye",
    "helpful",
    "attentive",
    "thinking",
    "confused",
    "uncertain",
    "curious",
    "sad",
    "downcast",
    "lonely",
    "angry",
    "irritated",
    "displeased",
    "disgusted",
    "scared",
    "anxious",
    "surprised",
    "amazed",
    "calming",
    "relief",
    "impatient",
    "embarrassed",
    "bored",
    "tired",
    "sleepy",
    "yes",
    "yes_understanding",
    "no",
    "no_sad",
    "no_excited",
    "no_firm",
    "go_away",
    "electric",
    "dying",
    "random",
}

DANCE_ALLOWLIST = {"random", "happy_wiggle", "celebration", "silly", "groove"}

EXPRESSION_FALLBACK_GESTURE = {
    "greeting": "yes",
    "welcoming": "yes_understanding",
    "happy": "small_bounce",
    "success": "small_bounce",
    "thinking": "thinking_wobble_short",
    "curious": "curious_tilt_left",
    "confused": "curious_tilt_right",
    "surprised": "antenna_perk_up",
    "yes": "yes",
    "yes_understanding": "yes_understanding",
    "no": "no",
    "no_firm": "no_firm",
    "sleepy": "antenna_relax",
    "tired": "antenna_relax",
}


def fallback_gesture_for_expression(expression: str) -> str | None:
    """Return a safe gesture preset for an expression fallback, if one is known."""

    return EXPRESSION_FALLBACK_GESTURE.get(expression)
