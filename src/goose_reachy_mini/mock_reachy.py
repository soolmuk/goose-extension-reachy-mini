"""Mock Reachy Mini backend for local development and CI."""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from typing import Any

from PIL import Image, ImageDraw

from .schemas import DirectionResult, FrameResult, MotionResult, utc_now_iso


class MockReachyClient:
    """Hardware-free Reachy Mini client that records actions and returns synthetic media."""

    def __init__(self, media_backend: str = "default") -> None:
        self.media_backend = media_backend
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.connected = True
        self.camera_available = True
        self.audio_available = True
        self.motion_available = True
        self.imu_available = True
        self.recorded_emotions_available = False
        self.dances_available = True
        self.head_tracking_available = True
        self.imu_motion_state = "stable"
        self.speech_detected = True
        self.last_audio: bytes = b""

    def get_status(self) -> dict[str, object]:
        return {
            "connected": self.connected,
            "media_backend": self.media_backend,
            "camera_available": self.camera_available,
            "audio_available": self.audio_available,
            "imu_available": self.imu_available,
            "motion_available": self.motion_available,
            "recorded_emotions_available": self.recorded_emotions_available,
            "dances_available": self.dances_available,
            "head_tracking_available": self.head_tracking_available,
            "mock_mode": True,
        }

    def get_imu(self) -> dict[str, object]:
        return {
            "orientation": {"roll": 0.0, "pitch": 1.2, "yaw": -3.1},
            "motion_state": self.imu_motion_state,
            "timestamp": utc_now_iso(),
        }

    def get_frame(self) -> FrameResult:
        self._record("get_frame")
        image = Image.new("RGB", (640, 360), color=(34, 45, 70))
        draw = ImageDraw.Draw(image)
        draw.rectangle((40, 40, 220, 180), fill=(240, 200, 90), outline=(255, 255, 255), width=3)
        draw.ellipse((380, 80, 540, 240), fill=(90, 190, 140), outline=(255, 255, 255), width=3)
        draw.text((52, 52), "Mock Reachy View", fill=(20, 20, 20))
        draw.text((390, 250), datetime.now(UTC).strftime("%H:%M:%S UTC"), fill=(255, 255, 255))
        return FrameResult(data=image, width=image.width, height=image.height)

    def look(self, direction: str, intensity: str) -> MotionResult:
        self._record("look", direction, intensity)
        return MotionResult(action="look", details={"direction": direction, "intensity": intensity})

    def look_at_image_region(self, region: str, intensity: str) -> MotionResult:
        self._record("look_at_image_region", region, intensity)
        return MotionResult(
            action="look_at_image_region", details={"region": region, "intensity": intensity}
        )

    def gesture(self, gesture: str, times: int, intensity: str) -> MotionResult:
        self._record("gesture", gesture, times, intensity)
        return MotionResult(
            action="gesture", details={"gesture": gesture, "times": times, "intensity": intensity}
        )

    def turn_body(self, direction: str, amount: str) -> MotionResult:
        self._record("turn_body", direction, amount)
        return MotionResult(action="turn_body", details={"direction": direction, "amount": amount})

    def reset_pose(self, include_antennas: bool = True, include_body: bool = True) -> MotionResult:
        self._record("reset_pose", include_antennas, include_body)
        return MotionResult(
            action="reset_pose",
            details={"include_antennas": include_antennas, "include_body": include_body},
        )

    def track_head(self, enabled: bool, mode: str, duration_seconds: float) -> MotionResult:
        self._record("track_head", enabled, mode, duration_seconds)
        return MotionResult(
            action="track_head",
            details={"enabled": enabled, "mode": mode, "duration_seconds": duration_seconds},
            message="Tracking will auto-stop after the requested duration." if enabled else "Tracking stopped.",
        )

    def listen_direction(self, duration_seconds: float) -> DirectionResult:
        self._record("listen_direction", duration_seconds)
        if not self.speech_detected:
            return DirectionResult(speech_detected=False, confidence="low")
        return DirectionResult(
            speech_detected=True,
            direction="front_left",
            angle_radians=0.7,
            confidence="medium",
        )

    def play_expression(
        self,
        expression: str,
        intensity: str,
        duration_seconds: float,
        say_message: bool = False,
        message: str | None = None,
    ) -> MotionResult:
        self._record("play_expression", expression, intensity, duration_seconds, say_message, message)
        return MotionResult(
            action="play_expression",
            details={
                "expression": expression,
                "intensity": intensity,
                "duration_seconds": duration_seconds,
                "source": "fallback_preset",
                "say_message": say_message,
                "message": message,
            },
        )

    def stop_expression(self) -> MotionResult:
        self._record("stop_expression")
        return MotionResult(action="stop_expression", message="Expression stopped or was not running.")

    def dance(self, dance: str, repeat: int) -> MotionResult:
        self._record("dance", dance, repeat)
        selected = "happy_wiggle" if dance == "random" else dance
        return MotionResult(action="dance", details={"dance": selected, "repeat": repeat})

    def stop_dance(self) -> MotionResult:
        self._record("stop_dance")
        return MotionResult(action="stop_dance", message="Dance stopped or was not running.")

    def listen_audio_sample(self, duration_seconds: float) -> dict[str, object]:
        self._record("listen_audio_sample", duration_seconds)
        # Tiny placeholder WAV-like payload. It is intentionally not a full audio recording.
        payload = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 28
        return {
            "audio_base64": base64.b64encode(payload).decode("ascii"),
            "mime_type": "audio/wav",
            "duration_seconds": duration_seconds,
            "timestamp": utc_now_iso(),
        }

    def play_audio(self, audio_bytes: bytes, mime_type: str, wobble: bool = False) -> MotionResult:
        self.last_audio = audio_bytes
        self._record("play_audio", len(audio_bytes), mime_type, wobble)
        return MotionResult(
            action="play_audio",
            details={"bytes": len(audio_bytes), "mime_type": mime_type, "wobble": wobble},
        )

    def say_text(self, text: str, voice: str, wobble: bool = True) -> MotionResult:
        self._record("say_text", text, voice, wobble)
        return MotionResult(
            action="say_text",
            message="Mock mode: text was accepted but no TTS audio was produced.",
            details={"text": text, "voice": voice, "wobble": wobble, "tts_backend": "mock"},
        )

    def close(self) -> None:
        self._record("close")

    def _record(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, args, kwargs))
