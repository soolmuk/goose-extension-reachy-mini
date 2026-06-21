"""Schemas, enums, and environment settings for the Reachy Mini MCP extension."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


ImageFormat = Literal["jpeg", "png"]
DetailLevel = Literal["brief", "normal", "detailed"]
Intensity = Literal["small", "medium"]
ControlAppPresetPolicy = Literal["off", "simulation_only", "always"]
LookDirection = Literal["center", "left", "right", "up", "down", "front_left", "front_right"]
ImageRegion = Literal[
    "center",
    "upper_left",
    "upper_right",
    "lower_left",
    "lower_right",
    "person_candidate",
    "object_candidate",
]
TrackingMode = Literal["face", "person", "speaker"]
GestureName = Literal[
    "yes",
    "yes_understanding",
    "no",
    "no_firm",
    "curious_tilt_left",
    "curious_tilt_right",
    "look_around_short",
    "small_bounce",
    "shy_tilt",
    "thinking_wobble_short",
    "antenna_wave",
    "antenna_perk_up",
    "antenna_relax",
]
BodyDirection = Literal["left", "right", "center"]
ExpressionName = Literal[
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
]
DanceName = Literal["random", "happy_wiggle", "celebration", "silly", "groove"]
MimeType = Literal["audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp3", "audio/ogg"]


class ToolError(Exception):
    """User-facing tool error that should be returned as a graceful MCP result."""


class Settings(BaseModel):
    """Environment-driven extension settings."""

    mock: bool = True
    mock_explicit: bool = True
    media_backend: str = "default"
    control_app: bool = False
    control_app_auto: bool = True
    control_app_url: str | None = None
    control_app_camera_url: str | None = None
    control_app_camera_path: str = "/camera"
    control_app_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    control_app_auth_token: str | None = None
    control_app_media_backend: str = "auto"
    control_app_capture_source: str = "auto"
    control_app_screen_crop: str | None = None
    control_app_python: str | None = None
    control_app_daemon_url: str | None = None
    control_app_signaling_host: str = "localhost"
    control_app_signaling_port: int = Field(default=8443, ge=1, le=65535)
    control_app_preset_policy: ControlAppPresetPolicy = "simulation_only"
    control_app_motion_timeout_seconds: float = Field(default=3.0, gt=0, le=30)
    enable_motion: bool = True
    enable_audio: bool = True
    enable_camera: bool = True
    enable_tracking: bool = True
    max_gesture_times: int = Field(default=3, ge=1, le=10)
    max_expression_seconds: float = Field(default=5.0, gt=0, le=30)
    max_dance_repeat: int = Field(default=3, ge=1, le=10)
    max_tracking_seconds: float = Field(default=30.0, gt=0, le=120)
    max_audio_seconds: float = Field(default=10.0, gt=0, le=60)
    max_image_size: int = Field(default=1280, ge=320, le=4096)
    tts_backend: str | None = None

    @classmethod
    def from_env(cls) -> Settings:
        """Create settings from REACHY_MINI_* environment variables."""

        mock_env = os.getenv("REACHY_MINI_MOCK")
        return cls(
            mock=_env_bool("REACHY_MINI_MOCK", default=True),
            mock_explicit=mock_env is not None and mock_env != "",
            media_backend=os.getenv("REACHY_MINI_MEDIA_BACKEND", "default"),
            control_app=_env_bool("REACHY_MINI_CONTROL_APP", default=False),
            control_app_auto=_env_bool("REACHY_MINI_CONTROL_APP_AUTO", default=True),
            control_app_url=os.getenv("REACHY_MINI_CONTROL_APP_URL") or None,
            control_app_camera_url=os.getenv("REACHY_MINI_CONTROL_APP_CAMERA_URL") or None,
            control_app_camera_path=os.getenv("REACHY_MINI_CONTROL_APP_CAMERA_PATH", "/camera"),
            control_app_timeout_seconds=_env_float("REACHY_MINI_CONTROL_APP_TIMEOUT_SECONDS", 5.0),
            control_app_auth_token=os.getenv("REACHY_MINI_CONTROL_APP_AUTH_TOKEN") or None,
            control_app_media_backend=os.getenv("REACHY_MINI_CONTROL_APP_MEDIA_BACKEND", "auto"),
            control_app_capture_source=os.getenv("REACHY_MINI_CONTROL_APP_CAPTURE_SOURCE", "auto"),
            control_app_screen_crop=os.getenv("REACHY_MINI_CONTROL_APP_SCREEN_CROP") or None,
            control_app_python=os.getenv("REACHY_MINI_CONTROL_APP_PYTHON") or None,
            control_app_daemon_url=os.getenv("REACHY_MINI_CONTROL_APP_DAEMON_URL") or None,
            control_app_signaling_host=os.getenv("REACHY_MINI_CONTROL_APP_SIGNALING_HOST", "localhost"),
            control_app_signaling_port=_env_int("REACHY_MINI_CONTROL_APP_SIGNALING_PORT", 8443),
            control_app_preset_policy=os.getenv(
                "REACHY_MINI_CONTROL_APP_PRESET_POLICY", "simulation_only"
            ),
            control_app_motion_timeout_seconds=_env_float(
                "REACHY_MINI_CONTROL_APP_MOTION_TIMEOUT_SECONDS", 3.0
            ),
            enable_motion=_env_bool("REACHY_MINI_ENABLE_MOTION", default=True),
            enable_audio=_env_bool("REACHY_MINI_ENABLE_AUDIO", default=True),
            enable_camera=_env_bool("REACHY_MINI_ENABLE_CAMERA", default=True),
            enable_tracking=_env_bool("REACHY_MINI_ENABLE_TRACKING", default=True),
            max_gesture_times=_env_int("REACHY_MINI_MAX_GESTURE_TIMES", 3),
            max_expression_seconds=_env_float("REACHY_MINI_MAX_EXPRESSION_SECONDS", 5.0),
            max_dance_repeat=_env_int("REACHY_MINI_MAX_DANCE_REPEAT", 3),
            max_tracking_seconds=_env_float("REACHY_MINI_MAX_TRACKING_SECONDS", 30.0),
            max_audio_seconds=_env_float("REACHY_MINI_MAX_AUDIO_SECONDS", 10.0),
            max_image_size=_env_int("REACHY_MINI_MAX_IMAGE_SIZE", 1280),
            tts_backend=os.getenv("REACHY_MINI_TTS_BACKEND") or None,
        )


class FrameResult(BaseModel):
    """Normalized camera frame returned by a client."""

    data: object
    width: int | None = None
    height: int | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))

    model_config = {"arbitrary_types_allowed": True}


class ImagePayload(BaseModel):
    """MCP-safe encoded image payload."""

    image_base64: str
    mime_type: str
    width: int
    height: int
    timestamp: str


class ImuResult(BaseModel):
    """High-level IMU result."""

    orientation: dict[str, float]
    motion_state: str = "stable"
    timestamp: str = Field(default_factory=utc_now_iso)


class MotionResult(BaseModel):
    """Common result for robot actions."""

    status: str = "ok"
    action: str
    message: str | None = None
    details: dict[str, object] = Field(default_factory=dict)


class DirectionResult(BaseModel):
    """Sound direction / DoA result."""

    speech_detected: bool
    direction: str | None = None
    angle_radians: float | None = None
    confidence: str = "low"


class AudioPayload(BaseModel):
    """Base64 encoded audio payload."""

    audio_base64: str
    mime_type: str
    duration_seconds: float
    timestamp: str = Field(default_factory=utc_now_iso)


class CaptureImageInput(BaseModel):
    format: ImageFormat = "jpeg"
    include_metadata: bool = True


class DescribeCurrentViewInput(BaseModel):
    detail_level: DetailLevel = "normal"


class LookAtImageRegionInput(BaseModel):
    region: ImageRegion
    intensity: Intensity = "small"


class TrackHeadInput(BaseModel):
    enabled: bool
    mode: TrackingMode = "face"
    duration_seconds: float = Field(default=10.0, gt=0)


class ListenDirectionInput(BaseModel):
    duration_seconds: float = Field(default=2.0, gt=0)


class LookTowardSoundInput(BaseModel):
    listen_duration_seconds: float = Field(default=2.0, gt=0)
    intensity: Intensity = "small"


class LookInput(BaseModel):
    direction: LookDirection
    intensity: Intensity = "small"


class GestureInput(BaseModel):
    gesture: GestureName
    times: int = Field(default=1, ge=1)
    intensity: Intensity = "small"


class TurnBodyInput(BaseModel):
    direction: BodyDirection
    amount: Intensity = "small"


class ResetPoseInput(BaseModel):
    include_antennas: bool = True
    include_body: bool = True


class PlayExpressionInput(BaseModel):
    expression: ExpressionName
    intensity: Intensity = "medium"
    duration_seconds: float = Field(default=2.0, gt=0)
    say_message: bool = False
    message: str | None = None

    @field_validator("message")
    @classmethod
    def message_length(cls, value: str | None) -> str | None:
        if value is not None and len(value) > 500:
            raise ValueError("message must be 500 characters or fewer")
        return value


class DanceInput(BaseModel):
    dance: DanceName = "random"
    repeat: int = Field(default=1, ge=1)


class ListenAudioSampleInput(BaseModel):
    duration_seconds: float = Field(default=3.0, gt=0)


class PlayAudioInput(BaseModel):
    audio_base64: str
    mime_type: MimeType = "audio/wav"
    wobble: bool = False


class SayTextInput(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    voice: str = "default"
    wobble: bool = True


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return int(value)


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return float(value)
