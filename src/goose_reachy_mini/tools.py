"""MCP tool implementations for Reachy Mini."""

from __future__ import annotations

from typing import Protocol

from pydantic import ValidationError

from .audio import decode_audio_base64, tts_missing_result
from .recorded_moves import DANCE_ALLOWLIST, EXPRESSION_INTENTS
from .safety import SafetyPolicy
from .schemas import (
    CaptureImageInput,
    DanceInput,
    DescribeCurrentViewInput,
    GestureInput,
    ListenAudioSampleInput,
    ListenDirectionInput,
    LookAtImageRegionInput,
    LookInput,
    LookTowardSoundInput,
    PlayAudioInput,
    PlayExpressionInput,
    ResetPoseInput,
    SayTextInput,
    Settings,
    ToolError,
    TrackHeadInput,
    TurnBodyInput,
)
from .vision import build_scene_description_instruction, encode_frame_for_mcp


class ReachyLikeClient(Protocol):
    """Client protocol shared by the real and mock Reachy clients."""

    media_backend: str

    def get_status(self) -> dict[str, object]: ...
    def get_imu(self) -> dict[str, object]: ...
    def get_frame(self) -> object: ...
    def look(self, direction: str, intensity: str) -> object: ...
    def look_at_image_region(self, region: str, intensity: str) -> object: ...
    def gesture(self, gesture: str, times: int, intensity: str) -> object: ...
    def turn_body(self, direction: str, amount: str) -> object: ...
    def reset_pose(self, include_antennas: bool = True, include_body: bool = True) -> object: ...
    def track_head(self, enabled: bool, mode: str, duration_seconds: float) -> object: ...
    def listen_direction(self, duration_seconds: float) -> object: ...
    def play_expression(
        self,
        expression: str,
        intensity: str,
        duration_seconds: float,
        say_message: bool = False,
        message: str | None = None,
    ) -> object: ...
    def stop_expression(self) -> object: ...
    def dance(self, dance: str, repeat: int) -> object: ...
    def stop_dance(self) -> object: ...
    def listen_audio_sample(self, duration_seconds: float) -> dict[str, object]: ...
    def play_audio(self, audio_bytes: bytes, mime_type: str, wobble: bool = False) -> object: ...
    def say_text(self, text: str, voice: str, wobble: bool = True) -> object: ...


class ReachyTools:
    """Stateful tool collection bound to one client and one safety policy."""

    def __init__(self, client: ReachyLikeClient, settings: Settings) -> None:
        self.client = client
        self.settings = settings
        self.safety = SafetyPolicy(settings, client)

    def reachy_get_status(self) -> dict[str, object]:
        """Get Reachy Mini connection state and high-level capabilities."""

        status = self.client.get_status()
        status.update(
            {
                "motion_enabled": self.settings.enable_motion,
                "camera_enabled": self.settings.enable_camera,
                "audio_enabled": self.settings.enable_audio,
                "tracking_enabled": self.settings.enable_tracking,
                "safe_api": True,
                "available_dances": sorted(DANCE_ALLOWLIST),
                "available_expression_intents": sorted(EXPRESSION_INTENTS),
            }
        )
        return status

    def reachy_get_imu(self) -> dict[str, object]:
        """Get high-level IMU orientation and stability state."""

        return self.client.get_imu()

    def reachy_idle(self) -> dict[str, object]:
        """Explicitly perform no robot action."""

        return {"status": "ok", "action": "idle", "message": "No robot action was performed."}

    def reachy_capture_image(self, format: str = "jpeg", include_metadata: bool = True) -> dict[str, object]:
        """Capture a single Reachy Mini camera frame."""

        try:
            args = CaptureImageInput(format=format, include_metadata=include_metadata)
            self.safety.assert_camera_allowed("reachy_capture_image")
            frame = self.client.get_frame()
            payload = encode_frame_for_mcp(frame, args.format, self.settings.max_image_size).model_dump()
            if not args.include_metadata:
                payload = {"image_base64": payload["image_base64"], "mime_type": payload["mime_type"]}
            return payload
        except (ToolError, ValidationError, RuntimeError) as exc:
            return _error_result("reachy_capture_image", exc)

    def reachy_describe_current_view(self, detail_level: str = "normal") -> dict[str, object]:
        """Capture the current view and return an instruction for image-based scene description."""

        try:
            args = DescribeCurrentViewInput(detail_level=detail_level)
            self.safety.assert_camera_allowed("reachy_describe_current_view")
            frame = self.client.get_frame()
            payload = encode_frame_for_mcp(frame, "jpeg", self.settings.max_image_size).model_dump()
            payload["instruction"] = build_scene_description_instruction(args.detail_level)
            return payload
        except (ToolError, ValidationError) as exc:
            return _error_result("reachy_describe_current_view", exc)

    def reachy_look_at_image_region(self, region: str, intensity: str = "small") -> dict[str, object]:
        """Look toward a preset image region without exposing raw pixel coordinates."""

        try:
            args = LookAtImageRegionInput(region=region, intensity=intensity)
            self.safety.assert_camera_allowed("reachy_look_at_image_region")
            self.safety.assert_motion_allowed("reachy_look_at_image_region")
            return _dump(self.client.look_at_image_region(args.region, args.intensity))
        except (ToolError, ValidationError) as exc:
            return _error_result("reachy_look_at_image_region", exc)

    def reachy_track_head(
        self, enabled: bool, mode: str = "face", duration_seconds: float = 10.0
    ) -> dict[str, object]:
        """Enable or disable short-duration head/person/speaker tracking."""

        try:
            args = TrackHeadInput(enabled=enabled, mode=mode, duration_seconds=duration_seconds)
            self.safety.assert_tracking_allowed("reachy_track_head")
            duration = self.safety.clamp_tracking_duration(args.duration_seconds)
            return _dump(self.client.track_head(args.enabled, args.mode, duration))
        except (ToolError, ValidationError) as exc:
            return _error_result("reachy_track_head", exc)

    def reachy_listen_direction(self, duration_seconds: float = 2.0) -> dict[str, object]:
        """Listen briefly for speech direction of arrival without doing STT."""

        try:
            args = ListenDirectionInput(duration_seconds=duration_seconds)
            self.safety.assert_audio_allowed("reachy_listen_direction")
            duration = self.safety.clamp_audio_duration(args.duration_seconds)
            return _dump(self.client.listen_direction(duration))
        except (ToolError, ValidationError) as exc:
            return _error_result("reachy_listen_direction", exc)

    def reachy_look_toward_sound(
        self, listen_duration_seconds: float = 2.0, intensity: str = "small"
    ) -> dict[str, object]:
        """Listen briefly and, if speech is detected, look toward that sound once."""

        try:
            args = LookTowardSoundInput(
                listen_duration_seconds=listen_duration_seconds, intensity=intensity
            )
            self.safety.assert_audio_allowed("reachy_look_toward_sound")
            self.safety.assert_motion_allowed("reachy_look_toward_sound")
            duration = self.safety.clamp_audio_duration(args.listen_duration_seconds)
            direction = self.client.listen_direction(duration)
            direction_result = _dump(direction)
            if not direction_result.get("speech_detected"):
                return {
                    "status": "ok",
                    "action": "look_toward_sound",
                    "moved": False,
                    "direction": direction_result,
                }
            look_result = _dump(self.client.look(str(direction_result.get("direction")), args.intensity))
            return {
                "status": "ok",
                "action": "look_toward_sound",
                "moved": True,
                "direction": direction_result,
                "look_result": look_result,
            }
        except (ToolError, ValidationError) as exc:
            return _error_result("reachy_look_toward_sound", exc)

    def reachy_look(self, direction: str, intensity: str = "small") -> dict[str, object]:
        """Move the head using a safe direction/intensity preset."""

        try:
            args = LookInput(direction=direction, intensity=intensity)
            self.safety.assert_motion_allowed("reachy_look")
            return _dump(self.client.look(args.direction, args.intensity))
        except (ToolError, ValidationError) as exc:
            return _error_result("reachy_look", exc)

    def reachy_gesture(self, gesture: str, times: int = 1, intensity: str = "small") -> dict[str, object]:
        """Run a high-level head/body/antenna gesture preset."""

        try:
            args = GestureInput(gesture=gesture, times=times, intensity=intensity)
            self.safety.assert_motion_allowed("reachy_gesture")
            safe_times = self.safety.clamp_gesture_times(args.times)
            return _dump(self.client.gesture(args.gesture, safe_times, args.intensity))
        except (ToolError, ValidationError) as exc:
            return _error_result("reachy_gesture", exc)

    def reachy_turn_body(self, direction: str, amount: str = "small") -> dict[str, object]:
        """Turn the body yaw using a small/medium preset only."""

        try:
            args = TurnBodyInput(direction=direction, amount=amount)
            self.safety.assert_motion_allowed("reachy_turn_body")
            return _dump(self.client.turn_body(args.direction, args.amount))
        except (ToolError, ValidationError) as exc:
            return _error_result("reachy_turn_body", exc)

    def reachy_reset_pose(self, include_antennas: bool = True, include_body: bool = True) -> dict[str, object]:
        """Return head, antennas, and body yaw to a safe neutral pose."""

        try:
            args = ResetPoseInput(include_antennas=include_antennas, include_body=include_body)
            self.safety.assert_motion_allowed("reachy_reset_pose")
            return _dump(self.client.reset_pose(args.include_antennas, args.include_body))
        except (ToolError, ValidationError) as exc:
            return _error_result("reachy_reset_pose", exc)

    def reachy_play_expression(
        self,
        expression: str,
        intensity: str = "medium",
        duration_seconds: float = 2.0,
        say_message: bool = False,
        message: str | None = None,
    ) -> dict[str, object]:
        """Play a curated expression/emotion/conversational intent preset."""

        try:
            args = PlayExpressionInput(
                expression=expression,
                intensity=intensity,
                duration_seconds=duration_seconds,
                say_message=say_message,
                message=message,
            )
            self.safety.assert_motion_allowed("reachy_play_expression")
            duration = self.safety.clamp_expression_duration(args.duration_seconds)
            result = _dump(
                self.client.play_expression(
                    args.expression,
                    args.intensity,
                    duration,
                    args.say_message,
                    args.message,
                )
            )
            if args.say_message and args.message:
                result["speech_note"] = (
                    "Expression accepted. Speech requires a configured TTS backend; "
                    "use reachy_say_text or reachy_play_audio for audio output."
                )
            return result
        except (ToolError, ValidationError) as exc:
            return _error_result("reachy_play_expression", exc)

    def reachy_stop_expression(self) -> dict[str, object]:
        """Stop the current expression/emotion queue if one is running."""

        try:
            self.safety.assert_motion_allowed("reachy_stop_expression")
            return _dump(self.client.stop_expression())
        except (ToolError, ValidationError) as exc:
            return _error_result("reachy_stop_expression", exc)

    def reachy_dance(self, dance: str = "random", repeat: int = 1) -> dict[str, object]:
        """Run a short allowlisted dance preset or random dance."""

        try:
            args = DanceInput(dance=dance, repeat=repeat)
            self.safety.assert_motion_allowed("reachy_dance")
            safe_repeat = self.safety.clamp_dance_repeat(args.repeat)
            return _dump(self.client.dance(args.dance, safe_repeat))
        except (ToolError, ValidationError) as exc:
            return _error_result("reachy_dance", exc)

    def reachy_stop_dance(self) -> dict[str, object]:
        """Stop the current dance if one is running."""

        try:
            self.safety.assert_motion_allowed("reachy_stop_dance")
            return _dump(self.client.stop_dance())
        except (ToolError, ValidationError) as exc:
            return _error_result("reachy_stop_dance", exc)

    def reachy_listen_audio_sample(self, duration_seconds: float = 3.0) -> dict[str, object]:
        """Capture a short audio sample without transcribing it."""

        try:
            args = ListenAudioSampleInput(duration_seconds=duration_seconds)
            self.safety.assert_audio_allowed("reachy_listen_audio_sample")
            duration = self.safety.clamp_audio_duration(args.duration_seconds)
            return self.client.listen_audio_sample(duration)
        except (ToolError, ValidationError) as exc:
            return _error_result("reachy_listen_audio_sample", exc)

    def reachy_play_audio(
        self, audio_base64: str, mime_type: str = "audio/wav", wobble: bool = False
    ) -> dict[str, object]:
        """Play a short base64-encoded audio clip."""

        try:
            args = PlayAudioInput(audio_base64=audio_base64, mime_type=mime_type, wobble=wobble)
            self.safety.assert_audio_allowed("reachy_play_audio")
            if args.wobble:
                self.safety.assert_motion_allowed("reachy_play_audio wobble")
            payload = decode_audio_base64(args.audio_base64, args.mime_type)
            return _dump(self.client.play_audio(payload, args.mime_type, args.wobble))
        except (ToolError, ValidationError) as exc:
            return _error_result("reachy_play_audio", exc)

    def reachy_say_text(self, text: str, voice: str = "default", wobble: bool = True) -> dict[str, object]:
        """Speak text using an optional TTS backend, or return setup guidance if unavailable."""

        try:
            args = SayTextInput(text=text, voice=voice, wobble=wobble)
            self.safety.assert_audio_allowed("reachy_say_text")
            if args.wobble:
                self.safety.assert_motion_allowed("reachy_say_text wobble")
            if not self.settings.tts_backend and not self.settings.mock:
                return tts_missing_result(args.text, args.voice, args.wobble)
            return _dump(self.client.say_text(args.text, args.voice, args.wobble))
        except (ToolError, ValidationError) as exc:
            return _error_result("reachy_say_text", exc)


TOOL_NAMES = [
    "reachy_get_status",
    "reachy_get_imu",
    "reachy_idle",
    "reachy_capture_image",
    "reachy_describe_current_view",
    "reachy_look_at_image_region",
    "reachy_track_head",
    "reachy_listen_direction",
    "reachy_look_toward_sound",
    "reachy_look",
    "reachy_gesture",
    "reachy_turn_body",
    "reachy_reset_pose",
    "reachy_play_expression",
    "reachy_stop_expression",
    "reachy_dance",
    "reachy_stop_dance",
    "reachy_listen_audio_sample",
    "reachy_play_audio",
    "reachy_say_text",
]


def _dump(value: object) -> dict[str, object]:
    if hasattr(value, "model_dump"):
        return value.model_dump()  # type: ignore[no-any-return]
    if isinstance(value, dict):
        return value
    return {"status": "ok", "result": value}


def _error_result(action: str, exc: Exception) -> dict[str, object]:
    return {"status": "error", "action": action, "message": str(exc)}
