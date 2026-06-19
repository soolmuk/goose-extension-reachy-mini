"""Safety policy for high-level Reachy Mini MCP tools."""

from __future__ import annotations

from typing import Protocol

from .schemas import Settings, ToolError


class ImuProvider(Protocol):
    """Subset of a Reachy client needed by the safety layer."""

    def get_imu(self) -> dict[str, object]: ...


class SafetyPolicy:
    """Central guard for camera, audio, and motion actions."""

    def __init__(self, settings: Settings, client: ImuProvider) -> None:
        self.settings = settings
        self.client = client

    def assert_camera_allowed(self, action: str) -> None:
        if not self.settings.enable_camera:
            raise ToolError(f"Camera is disabled by REACHY_MINI_ENABLE_CAMERA for {action}.")

    def assert_audio_allowed(self, action: str) -> None:
        if not self.settings.enable_audio:
            raise ToolError(f"Audio is disabled by REACHY_MINI_ENABLE_AUDIO for {action}.")

    def assert_tracking_allowed(self, action: str) -> None:
        self.assert_motion_allowed(action)
        if not self.settings.enable_tracking:
            raise ToolError(f"Tracking is disabled by REACHY_MINI_ENABLE_TRACKING for {action}.")

    def assert_motion_allowed(self, action: str) -> None:
        if not self.settings.enable_motion:
            raise ToolError(f"Motion is disabled by REACHY_MINI_ENABLE_MOTION for {action}.")
        imu = self.client.get_imu()
        if str(imu.get("motion_state", "stable")) != "stable":
            raise ToolError(
                f"Motion action {action} was blocked because the robot IMU state is "
                f"{imu.get('motion_state')!r}. Place Reachy Mini stably and try again."
            )

    def clamp_gesture_times(self, times: int) -> int:
        if times > self.settings.max_gesture_times:
            raise ToolError(
                f"Gesture repeat count {times} exceeds maximum "
                f"{self.settings.max_gesture_times}."
            )
        return times

    def clamp_expression_duration(self, duration_seconds: float) -> float:
        if duration_seconds > self.settings.max_expression_seconds:
            raise ToolError(
                f"Expression duration {duration_seconds}s exceeds maximum "
                f"{self.settings.max_expression_seconds}s."
            )
        return duration_seconds

    def clamp_dance_repeat(self, repeat: int) -> int:
        if repeat > self.settings.max_dance_repeat:
            raise ToolError(
                f"Dance repeat count {repeat} exceeds maximum {self.settings.max_dance_repeat}."
            )
        return repeat

    def clamp_tracking_duration(self, duration_seconds: float) -> float:
        if duration_seconds > self.settings.max_tracking_seconds:
            raise ToolError(
                f"Tracking duration {duration_seconds}s exceeds maximum "
                f"{self.settings.max_tracking_seconds}s."
            )
        return duration_seconds

    def clamp_audio_duration(self, duration_seconds: float) -> float:
        if duration_seconds > self.settings.max_audio_seconds:
            raise ToolError(
                f"Audio duration {duration_seconds}s exceeds maximum "
                f"{self.settings.max_audio_seconds}s."
            )
        return duration_seconds
