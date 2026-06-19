"""Audio helpers for the Reachy Mini MCP extension."""

from __future__ import annotations

import base64
import binascii

from .schemas import ToolError

ALLOWED_AUDIO_MIME_TYPES = {"audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp3", "audio/ogg"}
MAX_AUDIO_BYTES = 2_000_000


def decode_audio_base64(audio_base64: str, mime_type: str) -> bytes:
    """Validate and decode a short audio payload."""

    if mime_type not in ALLOWED_AUDIO_MIME_TYPES:
        raise ToolError(
            f"Unsupported audio MIME type {mime_type!r}. Allowed: {sorted(ALLOWED_AUDIO_MIME_TYPES)}"
        )
    try:
        payload = base64.b64decode(audio_base64, validate=True)
    except binascii.Error as exc:
        raise ToolError("audio_base64 must be valid base64 data.") from exc
    if len(payload) > MAX_AUDIO_BYTES:
        raise ToolError(f"Audio payload is too large ({len(payload)} bytes > {MAX_AUDIO_BYTES} bytes).")
    if not payload:
        raise ToolError("Audio payload is empty.")
    return payload


def tts_missing_result(text: str, voice: str, wobble: bool) -> dict[str, object]:
    """Return a graceful result when no TTS backend has been configured."""

    return {
        "status": "unavailable",
        "action": "say_text",
        "message": (
            "TTS backend is not configured. Set REACHY_MINI_TTS_BACKEND, or synthesize a "
            "short audio clip externally and call reachy_play_audio."
        ),
        "details": {"text": text, "voice": voice, "wobble": wobble, "tts_backend": None},
    }
