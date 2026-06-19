"""Reachy Mini SDK client adapter.

The public MCP API intentionally exposes only high-level actions. This module is the
only place that should know about SDK-specific names and object shapes. The adapter
uses cautious best-effort calls because Reachy Mini SDK versions differ; unsupported
features return clear, user-facing messages instead of crashing the MCP server.
"""

from __future__ import annotations

import importlib
from typing import Any

from .schemas import DirectionResult, FrameResult, MotionResult, ToolError, utc_now_iso


class ReachyClient:
    """Best-effort Reachy Mini SDK wrapper."""

    def __init__(self, media_backend: str = "default") -> None:
        self.media_backend = media_backend
        self._mini: Any = None
        self._init_error: str | None = None
        try:
            mini_cls = self._load_reachy_mini_class()
            self._mini = mini_cls(media_backend=media_backend)
        except Exception as exc:  # pragma: no cover - depends on installed hardware SDK
            self._init_error = str(exc)

    @property
    def connected(self) -> bool:
        return self._mini is not None and self._init_error is None

    def get_status(self) -> dict[str, object]:
        mini = self._mini
        return {
            "connected": self.connected,
            "media_backend": self.media_backend,
            "camera_available": _has_path(mini, "media.get_frame") or _has_path(mini, "cameras"),
            "audio_available": _has_path(mini, "media") or _has_path(mini, "audio"),
            "imu_available": _has_path(mini, "imu") or _has_path(mini, "sensors.imu"),
            "motion_available": mini is not None
            and any(hasattr(mini, name) for name in ("head", "antenna", "antennas", "body_yaw")),
            "recorded_emotions_available": False,
            "dances_available": False,
            "head_tracking_available": any(
                _has_path(mini, path) for path in ("head_tracking", "tracking", "head.track")
            ),
            "mock_mode": False,
            "error": self._init_error,
        }

    def get_imu(self) -> dict[str, object]:
        if self._mini is None:
            return {
                "orientation": {"roll": 0.0, "pitch": 0.0, "yaw": 0.0},
                "motion_state": "unknown",
                "timestamp": utc_now_iso(),
                "message": self._not_connected_message(),
            }
        imu = _get_path(self._mini, "imu") or _get_path(self._mini, "sensors.imu")
        orientation = {"roll": 0.0, "pitch": 0.0, "yaw": 0.0}
        if imu is not None:
            for key in orientation:
                value = getattr(imu, key, None)
                if callable(value):
                    value = value()
                if isinstance(value, int | float):
                    orientation[key] = float(value)
        return {"orientation": orientation, "motion_state": "stable", "timestamp": utc_now_iso()}

    def get_frame(self) -> FrameResult:
        if self._mini is None:
            raise ToolError(self._not_connected_message())
        media = getattr(self._mini, "media", None)
        if media is None or not hasattr(media, "get_frame"):
            raise ToolError("Reachy Mini SDK does not expose media.get_frame() in this environment.")
        frame = media.get_frame()
        return FrameResult(data=frame)

    def look(self, direction: str, intensity: str) -> MotionResult:
        return self._motion_stub("look", direction=direction, intensity=intensity)

    def look_at_image_region(self, region: str, intensity: str) -> MotionResult:
        return self._motion_stub("look_at_image_region", region=region, intensity=intensity)

    def gesture(self, gesture: str, times: int, intensity: str) -> MotionResult:
        return self._motion_stub("gesture", gesture=gesture, times=times, intensity=intensity)

    def turn_body(self, direction: str, amount: str) -> MotionResult:
        return self._motion_stub("turn_body", direction=direction, amount=amount)

    def reset_pose(self, include_antennas: bool = True, include_body: bool = True) -> MotionResult:
        return self._motion_stub(
            "reset_pose", include_antennas=include_antennas, include_body=include_body
        )

    def track_head(self, enabled: bool, mode: str, duration_seconds: float) -> MotionResult:
        return self._motion_stub(
            "track_head", enabled=enabled, mode=mode, duration_seconds=duration_seconds
        )

    def listen_direction(self, duration_seconds: float) -> DirectionResult:
        if self._mini is None:
            raise ToolError(self._not_connected_message())
        return DirectionResult(
            speech_detected=False,
            confidence="low",
            direction=None,
            angle_radians=None,
        )

    def play_expression(
        self,
        expression: str,
        intensity: str,
        duration_seconds: float,
        say_message: bool = False,
        message: str | None = None,
    ) -> MotionResult:
        return self._motion_stub(
            "play_expression",
            expression=expression,
            intensity=intensity,
            duration_seconds=duration_seconds,
            say_message=say_message,
            message=message,
        )

    def stop_expression(self) -> MotionResult:
        return self._motion_stub("stop_expression")

    def dance(self, dance: str, repeat: int) -> MotionResult:
        return self._motion_stub("dance", dance=dance, repeat=repeat)

    def stop_dance(self) -> MotionResult:
        return self._motion_stub("stop_dance")

    def listen_audio_sample(self, duration_seconds: float) -> dict[str, object]:
        raise ToolError("Audio capture is not implemented for this Reachy Mini SDK adapter yet.")

    def play_audio(self, audio_bytes: bytes, mime_type: str, wobble: bool = False) -> MotionResult:
        if self._mini is None:
            raise ToolError(self._not_connected_message())
        media = getattr(self._mini, "media", None)
        for method_name in ("push_audio", "play_audio", "push"):
            method = getattr(media, method_name, None) if media is not None else None
            if callable(method):
                method(audio_bytes)
                return MotionResult(
                    action="play_audio",
                    details={"bytes": len(audio_bytes), "mime_type": mime_type, "wobble": wobble},
                )
        raise ToolError("Audio playback is not implemented for this Reachy Mini SDK adapter yet.")

    def say_text(self, text: str, voice: str, wobble: bool = True) -> MotionResult:
        return MotionResult(
            status="unavailable",
            action="say_text",
            message=(
                "No TTS backend is configured. Set REACHY_MINI_TTS_BACKEND and provide an "
                "adapter, or synthesize audio externally and call reachy_play_audio."
            ),
            details={"text": text, "voice": voice, "wobble": wobble},
        )

    def close(self) -> None:
        close = getattr(self._mini, "close", None)
        if callable(close):
            close()

    def _motion_stub(self, action: str, **details: object) -> MotionResult:
        if self._mini is None:
            raise ToolError(self._not_connected_message())
        # Conservative fallback: do not guess low-level SDK calls. Hardware-specific
        # mappings can be added here without changing MCP tool schemas.
        return MotionResult(
            status="unavailable",
            action=action,
            message=(
                f"{action} is available in the MCP API, but this SDK adapter does not yet "
                "have a verified safe hardware mapping for the installed SDK version."
            ),
            details=details,
        )

    def _not_connected_message(self) -> str:
        base = "Reachy Mini SDK is unavailable or failed to initialize."
        if self._init_error:
            return f"{base} Original error: {self._init_error}"
        return base

    @staticmethod
    def _load_reachy_mini_class() -> type[Any]:
        candidates = (
            ("reachy_mini", "ReachyMini"),
            ("reachy2_sdk.reachy_sdk", "ReachySDK"),
        )
        errors: list[str] = []
        for module_name, class_name in candidates:
            try:
                module = importlib.import_module(module_name)
                cls = getattr(module, class_name)
                return cls
            except Exception as exc:  # pragma: no cover - import availability varies
                errors.append(f"{module_name}.{class_name}: {exc}")
        raise ImportError("Could not import a supported Reachy Mini SDK class: " + "; ".join(errors))


def _get_path(obj: object, path: str) -> object | None:
    current = obj
    for part in path.split("."):
        if current is None or not hasattr(current, part):
            return None
        current = getattr(current, part)
    return current


def _has_path(obj: object, path: str) -> bool:
    return _get_path(obj, path) is not None
