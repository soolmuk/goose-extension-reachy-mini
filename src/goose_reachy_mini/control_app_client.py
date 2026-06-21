"""Reachy Mini Control App camera adapter.

This adapter is intentionally conservative: it only reads camera frames exposed by a
locally running Control App. Motion/audio actions remain unavailable unless a verified
safe Control App API is added later.

Camera capture can use either:
- HTTP snapshot/MJPEG/JSON endpoints, when a direct endpoint is configured; or
- the Control App / Reachy Mini Python environment's GStreamer MediaManager over
  LOCAL IPC or WebRTC, launched as a short-lived subprocess so this extension does
  not need GStreamer installed in its own Python environment.
"""

from __future__ import annotations

import base64
import binascii
import html
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from .recorded_moves import fallback_gesture_for_expression
from .schemas import DirectionResult, FrameResult, MotionResult, ToolError, utc_now_iso

_MAX_FRAME_BYTES = 10 * 1024 * 1024
_HTML_SRC_RE = re.compile(rb"<(?:img|source|video)\b[^>]+\bsrc=[\"']([^\"']+)[\"']", re.I)
_IMAGE_KEYS = (
    "image_base64",
    "imageBase64",
    "frame_base64",
    "frameBase64",
    "snapshot_base64",
    "snapshotBase64",
    "image",
    "frame",
    "snapshot",
    "data",
)
_URL_KEYS = ("image_url", "imageUrl", "frame_url", "frameUrl", "snapshot_url", "snapshotUrl", "url")
_VALID_MEDIA_BACKENDS = {"auto", "http", "local", "webrtc"}
_VALID_CAPTURE_SOURCES = {"auto", "camera", "screen"}
_DEFAULT_DAEMON_URLS = (
    "http://127.0.0.1:8000",
    "http://localhost:8000",
)
_CAPTURE_SCRIPT = r'''
import argparse
import sys
import time

parser = argparse.ArgumentParser()
parser.add_argument("--backend", choices=["local", "webrtc"], required=True)
parser.add_argument("--host", default="localhost")
parser.add_argument("--signaling-port", type=int, default=8443)
parser.add_argument("--daemon-url", default="http://localhost:8000")
parser.add_argument("--timeout", type=float, default=5.0)
parser.add_argument("--log-level", default="WARNING")
args = parser.parse_args()

from reachy_mini.media.media_manager import MediaBackend, MediaManager
from reachy_mini.media.camera_constants import GenericWebcamSpecs

media = None
try:
    backend = MediaBackend.LOCAL if args.backend == "local" else MediaBackend.WEBRTC
    media = MediaManager(
        backend=backend,
        log_level=args.log_level,
        signalling_host=args.host,
        signaling_host=args.host,
        camera_specs=GenericWebcamSpecs(),
        daemon_url=args.daemon_url,
    )
except TypeError:
    # Older SDK spelling only accepts signalling_host.
    media = MediaManager(
        backend=backend,
        log_level=args.log_level,
        signalling_host=args.host,
        camera_specs=GenericWebcamSpecs(),
        daemon_url=args.daemon_url,
    )

try:
    deadline = time.monotonic() + args.timeout
    frame = None
    while time.monotonic() < deadline:
        frame = media.get_frame()
        if frame is not None:
            break
        time.sleep(0.05)

    if frame is None:
        raise RuntimeError(f"No camera frame received from {args.backend} backend")

    # Reachy MediaManager camera frames are BGR numpy arrays. Emit a binary PPM
    # (P6) RGB image. Pillow in the MCP extension can decode PPM without needing
    # Pillow in the Control App venv.
    rgb = frame[:, :, ::-1]
    height, width = rgb.shape[:2]
    sys.stdout.buffer.write(f"P6\n{width} {height}\n255\n".encode("ascii"))
    sys.stdout.buffer.write(rgb.tobytes())
    sys.stdout.buffer.flush()
finally:
    if media is not None:
        try:
            media.close()
        except Exception:
            pass
'''


class ControlAppClient:
    """Camera-only adapter for a Reachy Mini Control App.

    Supported HTTP camera response shapes:
    - direct JPEG/PNG bytes
    - MJPEG/multipart stream, from which the first JPEG frame is extracted
    - JSON containing a base64 image field such as ``image_base64`` or ``frame``
    - HTML containing an ``img``/``video``/``source`` ``src`` that points to a camera stream

    If no HTTP camera endpoint is configured, or ``media_backend`` is ``local`` or
    ``webrtc``, capture is performed through the Control App / Reachy Mini SDK
    media stack in a helper subprocess.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        camera_url: str | None = None,
        camera_path: str = "/camera",
        timeout_seconds: float = 5.0,
        auth_token: str | None = None,
        media_backend: str = "auto",
        capture_source: str = "auto",
        screen_crop: str | None = None,
        python_executable: str | None = None,
        daemon_url: str | None = None,
        signaling_host: str = "localhost",
        signaling_port: int = 8443,
        daemon_status: dict[str, Any] | None = None,
        preset_policy: str = "simulation_only",
        motion_timeout_seconds: float = 3.0,
    ) -> None:
        selected_backend = media_backend.strip().lower() if media_backend else "auto"
        if selected_backend not in _VALID_MEDIA_BACKENDS:
            selected_backend = "auto"
        selected_capture_source = capture_source.strip().lower() if capture_source else "auto"
        if selected_capture_source not in _VALID_CAPTURE_SOURCES:
            selected_capture_source = "auto"

        self.media_backend = "control_app"
        self.control_app_media_backend = selected_backend
        self.capture_source = selected_capture_source
        self.screen_crop = screen_crop
        self.base_url = _normalize_base_url(base_url)
        self.camera_url = camera_url.strip() if camera_url else None
        self.camera_path = camera_path or "/camera"
        self.timeout_seconds = timeout_seconds
        self.auth_token = auth_token
        self.python_executable = python_executable.strip() if python_executable else None
        self.daemon_url = daemon_url or self.base_url or _DEFAULT_DAEMON_URLS[0]
        self._daemon_status_url = _daemon_status_url(self.daemon_url)
        self.signaling_host = signaling_host or _host_from_url(self.daemon_url) or "localhost"
        self.signaling_port = signaling_port
        self.preset_policy = preset_policy if preset_policy in {"off", "simulation_only", "always"} else "simulation_only"
        self.motion_timeout_seconds = motion_timeout_seconds
        self._daemon_status = daemon_status
        self._last_error: str | None = None
        self._last_capture_transport: str | None = None
        self._active_move_ids: dict[str, str] = {}

    @property
    def configured(self) -> bool:
        return bool(
            self.camera_url
            or self.base_url
            or self.control_app_media_backend in {"auto", "local", "webrtc"}
        )

    def get_status(self) -> dict[str, object]:
        helper_python = self._python_executable()
        daemon_status = self._refresh_daemon_status()
        mode = _daemon_mode(daemon_status)
        media_available = _daemon_media_available(daemon_status)
        motion_available, motion_reason = self._motion_presets_allowed(daemon_status)
        return {
            "connected": self.configured and self._last_error is None,
            "media_backend": self.media_backend,
            "control_app_media_backend": self.control_app_media_backend,
            "control_app_capture_source": self.capture_source,
            "control_app_screen_crop": self.screen_crop,
            "camera_available": self.configured and media_available,
            "audio_available": False,
            "imu_available": False,
            "motion_available": motion_available,
            "recorded_emotions_available": motion_available,
            "dances_available": motion_available,
            "head_tracking_available": False,
            "mock_mode": False,
            "control_app_mode": True,
            "control_app_runtime_mode": mode,
            "control_app_simulation_enabled": bool(daemon_status.get("simulation_enabled", False)),
            "control_app_mockup_sim_enabled": bool(daemon_status.get("mockup_sim_enabled", False)),
            "control_app_media_released": bool(daemon_status.get("media_released", False)),
            "control_app_no_media": bool(daemon_status.get("no_media", False)),
            "control_app_preset_policy": self.preset_policy,
            "control_app_motion_available_reason": motion_reason,
            "control_app_state": daemon_status.get("state"),
            "control_app_camera_specs_name": daemon_status.get("camera_specs_name"),
            "camera_source": _redact_url(self._camera_entrypoint_url()),
            "daemon_url": _redact_url(self.daemon_url),
            "signaling_host": self.signaling_host,
            "signaling_port": self.signaling_port,
            "helper_python": helper_python,
            "helper_python_available": bool(helper_python),
            "last_capture_transport": self._last_capture_transport,
            "error": self._last_error,
        }

    def get_imu(self) -> dict[str, object]:
        # The Control App camera adapter does not expose IMU data. Return a stable
        # placeholder so non-motion camera tools can still operate; motion methods
        # below remain unavailable.
        return {
            "orientation": {"roll": 0.0, "pitch": 0.0, "yaw": 0.0},
            "motion_state": "stable",
            "timestamp": utc_now_iso(),
            "message": "IMU is not exposed by the Control App camera adapter.",
        }

    def get_frame(self) -> FrameResult:
        if not self.configured:
            raise ToolError(
                "Control App camera adapter is not configured. Set REACHY_MINI_CONTROL_APP=1 "
                "and either configure an HTTP camera URL or allow MediaManager WebRTC/IPC capture."
            )

        try:
            image_bytes = self._capture_frame_bytes()
            self._last_error = None
            return FrameResult(data=image_bytes, timestamp=datetime.now(UTC))
        except ToolError as exc:
            self._last_error = str(exc)
            raise

    def look(self, direction: str, intensity: str) -> MotionResult:
        unavailable = self._motion_unavailable_due_to_policy(
            "look", direction=direction, intensity=intensity
        )
        if unavailable:
            return unavailable
        payload = self._look_payload(direction, intensity)
        response = self._post_goto(payload, active_key="look")
        return MotionResult(
            action="look",
            message="Look preset sent to the Control App daemon.",
            details={"direction": direction, "intensity": intensity, "daemon_response": response},
        )

    def look_at_image_region(self, region: str, intensity: str) -> MotionResult:
        unavailable = self._motion_unavailable_due_to_policy(
            "look_at_image_region", region=region, intensity=intensity
        )
        if unavailable:
            return unavailable
        payload = self._image_region_payload(region, intensity)
        response = self._post_goto(payload, active_key="look")
        return MotionResult(
            action="look_at_image_region",
            message="Image-region look preset sent to the Control App daemon.",
            details={"region": region, "intensity": intensity, "daemon_response": response},
        )

    def gesture(self, gesture: str, times: int, intensity: str) -> MotionResult:
        unavailable = self._motion_unavailable_due_to_policy(
            "gesture", gesture=gesture, times=times, intensity=intensity
        )
        if unavailable:
            return unavailable
        return self._run_gesture(gesture, times, intensity, active_key="gesture")

    def turn_body(self, direction: str, amount: str) -> MotionResult:
        unavailable = self._motion_unavailable_due_to_policy(
            "turn_body", direction=direction, amount=amount
        )
        if unavailable:
            return unavailable
        payload = self._body_yaw_payload(direction, amount)
        response = self._post_goto(payload, active_key="turn_body")
        return MotionResult(
            action="turn_body",
            message="Body-yaw preset sent to the Control App daemon.",
            details={"direction": direction, "amount": amount, "daemon_response": response},
        )

    def reset_pose(self, include_antennas: bool = True, include_body: bool = True) -> MotionResult:
        unavailable = self._motion_unavailable_due_to_policy(
            "reset_pose", include_antennas=include_antennas, include_body=include_body
        )
        if unavailable:
            return unavailable
        payload = self._reset_payload(include_antennas, include_body)
        response = self._post_goto(payload, active_key="reset_pose")
        return MotionResult(
            action="reset_pose",
            message="Neutral pose preset sent to the Control App daemon.",
            details={
                "include_antennas": include_antennas,
                "include_body": include_body,
                "daemon_response": response,
            },
        )

    def track_head(self, enabled: bool, mode: str, duration_seconds: float) -> MotionResult:
        return self._unavailable_motion(
            "track_head", enabled=enabled, mode=mode, duration_seconds=duration_seconds
        )

    def listen_direction(self, duration_seconds: float) -> DirectionResult:
        raise ToolError("Audio input is not exposed by the Control App camera adapter.")

    def play_expression(
        self,
        expression: str,
        intensity: str,
        duration_seconds: float,
        say_message: bool = False,
        message: str | None = None,
    ) -> MotionResult:
        unavailable = self._motion_unavailable_due_to_policy(
            "play_expression",
            expression=expression,
            intensity=intensity,
            duration_seconds=duration_seconds,
            say_message=say_message,
            message=message,
        )
        if unavailable:
            return unavailable
        if expression == "random":
            expression = "happy"
        gesture = fallback_gesture_for_expression(expression)
        if not gesture:
            return MotionResult(
                status="unavailable",
                action="play_expression",
                message=(
                    f"No Control App simulation fallback gesture is mapped for "
                    f"expression {expression!r}."
                ),
                details={
                    "expression": expression,
                    "intensity": intensity,
                    "duration_seconds": duration_seconds,
                    "say_message": say_message,
                    "message": message,
                },
            )
        result = self._run_gesture(gesture, 1, intensity, active_key="expression")
        result.action = "play_expression"
        result.details.update(
            {
                "expression": expression,
                "fallback_gesture": gesture,
                "source": "fallback_gesture",
                "duration_seconds": duration_seconds,
                "say_message": say_message,
                "message": message,
            }
        )
        return result

    def stop_expression(self) -> MotionResult:
        return self._stop_active_move("stop_expression", "expression")

    def dance(self, dance: str, repeat: int) -> MotionResult:
        unavailable = self._motion_unavailable_due_to_policy("dance", dance=dance, repeat=repeat)
        if unavailable:
            return unavailable
        selected = "happy_wiggle" if dance == "random" else dance
        dance_sequences = {
            "happy_wiggle": ["small_bounce", "antenna_wave"],
            "celebration": ["antenna_perk_up", "small_bounce", "yes"],
            "silly": ["look_around_short", "antenna_wave"],
            "groove": ["curious_tilt_left", "curious_tilt_right", "small_bounce"],
        }
        sequence = dance_sequences.get(selected)
        if not sequence:
            return self._unavailable_motion("dance", dance=dance, repeat=repeat)
        responses: list[dict[str, object]] = []
        for _ in range(repeat):
            for gesture_name in sequence:
                result = self._run_gesture(gesture_name, 1, "small", active_key="dance")
                responses.append(result.model_dump())
        return MotionResult(
            action="dance",
            message="Dance fallback sequence sent to the Control App daemon.",
            details={"dance": selected, "repeat": repeat, "steps": responses},
        )

    def stop_dance(self) -> MotionResult:
        return self._stop_active_move("stop_dance", "dance")

    def listen_audio_sample(self, duration_seconds: float) -> dict[str, object]:
        raise ToolError("Audio capture is not exposed by the Control App camera adapter.")

    def play_audio(self, audio_bytes: bytes, mime_type: str, wobble: bool = False) -> MotionResult:
        raise ToolError("Audio playback is not exposed by the Control App camera adapter.")

    def say_text(self, text: str, voice: str, wobble: bool = True) -> MotionResult:
        return MotionResult(
            status="unavailable",
            action="say_text",
            message="TTS is not exposed by the Control App camera adapter.",
            details={"text": text, "voice": voice, "wobble": wobble},
        )

    def close(self) -> None:
        return None

    def _refresh_daemon_status(self) -> dict[str, Any]:
        try:
            status = fetch_control_app_daemon_status(
                self.daemon_url,
                timeout_seconds=min(self.timeout_seconds, 2.0),
                auth_token=self.auth_token,
            )
        except Exception as exc:
            self._last_error = f"Daemon status fetch failed: {exc}"
            return self._daemon_status or {}

        if status is not None:
            self._daemon_status = status
            self._last_error = None
            discovered_url = status.get("_daemon_url")
            if isinstance(discovered_url, str) and discovered_url:
                self.daemon_url = discovered_url
                if self.base_url is None:
                    self.base_url = _normalize_base_url(discovered_url)
        else:
            # Daemon was reachable before but is not responding now.
            if self._daemon_status:
                self._last_error = "Control App daemon is not responding."
            else:
                self._last_error = "No Control App daemon detected."
        return self._daemon_status or {}

    def _motion_presets_allowed(self, daemon_status: dict[str, Any] | None = None) -> tuple[bool, str]:
        status = daemon_status if daemon_status is not None else self._refresh_daemon_status()
        mode = _daemon_mode(status)
        if self.preset_policy == "off":
            return False, "Control App preset motion is disabled by policy."
        if self.preset_policy == "always":
            return True, f"Control App preset motion is enabled for mode {mode!r}."
        if self.preset_policy == "simulation_only":
            if mode in {"simulation", "mockup_simulation"}:
                return True, f"Control App preset motion is enabled for simulation mode {mode!r}."
            return (
                False,
                "Control App preset motion is allowed only in simulation modes "
                f"when REACHY_MINI_CONTROL_APP_PRESET_POLICY=simulation_only. Current mode: {mode}.",
            )
        return False, f"Unknown Control App preset policy: {self.preset_policy!r}."

    def _motion_unavailable_due_to_policy(self, action: str, **details: object) -> MotionResult | None:
        allowed, reason = self._motion_presets_allowed()
        if allowed:
            return None
        details = {**details, "reason": reason, "preset_policy": self.preset_policy}
        return MotionResult(status="unavailable", action=action, message=reason, details=details)

    def _daemon_api_url(self, path: str) -> str:
        return f"{self.daemon_url.rstrip('/')}/api/{path.lstrip('/')}"

    def _request_json(
        self, method: str, path: str, payload: dict[str, object] | None = None
    ) -> dict[str, object]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {
            "Accept": "application/json",
            "User-Agent": "goose-reachy-mini-control-app-adapter/0.1",
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        request = Request(self._daemon_api_url(path), data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.motion_timeout_seconds) as response:  # nosec B310
                response_data = response.read(512 * 1024)
        except HTTPError as exc:
            detail = exc.read(4096).decode("utf-8", errors="replace").strip()
            raise ToolError(
                f"Control App motion API HTTP error {exc.code} for {path}: {detail or exc.reason}"
            ) from exc
        except URLError as exc:
            raise ToolError(f"Could not reach Control App motion API {path}: {exc}") from exc
        except TimeoutError as exc:
            raise ToolError(f"Timed out calling Control App motion API {path}") from exc

        if not response_data.strip():
            return {"status": "ok"}
        try:
            decoded = json.loads(response_data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ToolError(f"Control App motion API {path} returned non-JSON data.") from exc
        if isinstance(decoded, dict):
            return decoded
        return {"result": decoded}

    def _post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
        return self._request_json("POST", path, payload)

    def _post_goto(
        self, payload: dict[str, object], active_key: str | None = None
    ) -> dict[str, object]:
        response = self._post_json("move/goto", payload)
        self._remember_move_id(active_key, response)
        return response

    def _remember_move_id(self, active_key: str | None, response: dict[str, object]) -> None:
        if not active_key:
            return
        uuid = response.get("uuid")
        if isinstance(uuid, str) and uuid:
            self._active_move_ids[active_key] = uuid

    def _stop_active_move(self, action: str, active_key: str) -> MotionResult:
        unavailable = self._motion_unavailable_due_to_policy(action)
        if unavailable:
            return unavailable
        uuid = self._active_move_ids.pop(active_key, None)
        if not uuid:
            return MotionResult(
                action=action,
                message="No active Control App move id was tracked for this preset.",
                details={"active_key": active_key},
            )
        response = self._post_json("move/stop", {"uuid": uuid})
        return MotionResult(
            action=action,
            message="Stop request sent to the Control App daemon.",
            details={"uuid": uuid, "daemon_response": response},
        )

    def _pose(self, *, roll: float = 0.0, pitch: float = 0.0, yaw: float = 0.0) -> dict[str, float]:
        return {"x": 0.0, "y": 0.0, "z": 0.0, "roll": roll, "pitch": pitch, "yaw": yaw}

    def _goto_payload(
        self,
        *,
        head_pose: dict[str, float] | None = None,
        antennas: tuple[float, float] | None = None,
        body_yaw: float | None = None,
        duration: float = 0.6,
    ) -> dict[str, object]:
        payload: dict[str, object] = {"duration": duration, "interpolation": "minjerk"}
        if head_pose is not None:
            payload["head_pose"] = head_pose
        if antennas is not None:
            payload["antennas"] = [antennas[0], antennas[1]]
        if body_yaw is not None:
            payload["body_yaw"] = body_yaw
        return payload

    def _look_payload(self, direction: str, intensity: str) -> dict[str, object]:
        angle = 0.42 if intensity == "medium" else 0.25
        pitch_angle = 0.32 if intensity == "medium" else 0.20
        pose_by_direction = {
            "center": self._pose(),
            "left": self._pose(yaw=angle),
            "right": self._pose(yaw=-angle),
            "up": self._pose(pitch=-pitch_angle),
            "down": self._pose(pitch=pitch_angle),
            "front_left": self._pose(yaw=angle, pitch=-0.08),
            "front_right": self._pose(yaw=-angle, pitch=-0.08),
        }
        return self._goto_payload(head_pose=pose_by_direction.get(direction, self._pose()))

    def _image_region_payload(self, region: str, intensity: str) -> dict[str, object]:
        angle = 0.36 if intensity == "medium" else 0.22
        pitch_angle = 0.28 if intensity == "medium" else 0.18
        pose_by_region = {
            "center": self._pose(),
            "upper_left": self._pose(yaw=angle, pitch=-pitch_angle),
            "upper_right": self._pose(yaw=-angle, pitch=-pitch_angle),
            "lower_left": self._pose(yaw=angle, pitch=pitch_angle),
            "lower_right": self._pose(yaw=-angle, pitch=pitch_angle),
            "person_candidate": self._pose(),
            "object_candidate": self._pose(),
        }
        return self._goto_payload(head_pose=pose_by_region.get(region, self._pose()))

    def _body_yaw_payload(self, direction: str, amount: str) -> dict[str, object]:
        angle = 0.45 if amount == "medium" else 0.25
        yaw = 0.0 if direction == "center" else angle if direction == "left" else -angle
        return self._goto_payload(body_yaw=yaw)

    def _reset_payload(self, include_antennas: bool, include_body: bool) -> dict[str, object]:
        return self._goto_payload(
            head_pose=self._pose(),
            antennas=(0.0, 0.0) if include_antennas else None,
            body_yaw=0.0 if include_body else None,
        )

    def _gesture_steps(self, gesture: str, intensity: str) -> list[dict[str, object]] | None:
        small = intensity != "medium"
        yaw = 0.25 if small else 0.42
        pitch = 0.20 if small else 0.32
        roll = 0.20 if small else 0.32
        bounce_body = 0.10 if small else 0.18
        steps = {
            "yes": [
                self._goto_payload(head_pose=self._pose(pitch=pitch), duration=0.35),
                self._goto_payload(head_pose=self._pose(pitch=-pitch), duration=0.35),
                self._goto_payload(head_pose=self._pose(), duration=0.35),
            ],
            "yes_understanding": [
                self._goto_payload(head_pose=self._pose(pitch=pitch), antennas=(0.4, 0.4), duration=0.35),
                self._goto_payload(head_pose=self._pose(), antennas=(0.0, 0.0), duration=0.35),
            ],
            "no": [
                self._goto_payload(head_pose=self._pose(yaw=yaw), duration=0.35),
                self._goto_payload(head_pose=self._pose(yaw=-yaw), duration=0.35),
                self._goto_payload(head_pose=self._pose(), duration=0.35),
            ],
            "no_firm": [
                self._goto_payload(head_pose=self._pose(yaw=0.45), duration=0.3),
                self._goto_payload(head_pose=self._pose(yaw=-0.45), duration=0.3),
                self._goto_payload(head_pose=self._pose(), duration=0.3),
            ],
            "curious_tilt_left": [self._goto_payload(head_pose=self._pose(roll=roll), duration=0.45)],
            "curious_tilt_right": [self._goto_payload(head_pose=self._pose(roll=-roll), duration=0.45)],
            "look_around_short": [
                self._goto_payload(head_pose=self._pose(yaw=yaw), duration=0.35),
                self._goto_payload(head_pose=self._pose(yaw=-yaw), duration=0.35),
                self._goto_payload(head_pose=self._pose(), duration=0.35),
            ],
            "small_bounce": [
                self._goto_payload(head_pose=self._pose(pitch=0.10), body_yaw=-bounce_body, duration=0.25),
                self._goto_payload(head_pose=self._pose(pitch=-0.10), body_yaw=bounce_body, duration=0.25),
                self._goto_payload(head_pose=self._pose(), body_yaw=0.0, duration=0.25),
            ],
            "shy_tilt": [self._goto_payload(head_pose=self._pose(roll=roll, pitch=pitch), duration=0.45)],
            "thinking_wobble_short": [
                self._goto_payload(head_pose=self._pose(roll=0.14), duration=0.25),
                self._goto_payload(head_pose=self._pose(roll=-0.14), duration=0.25),
                self._goto_payload(head_pose=self._pose(), duration=0.25),
            ],
            "antenna_wave": [
                self._goto_payload(antennas=(0.45, -0.45), duration=0.25),
                self._goto_payload(antennas=(-0.45, 0.45), duration=0.25),
                self._goto_payload(antennas=(0.0, 0.0), duration=0.25),
            ],
            "antenna_perk_up": [self._goto_payload(antennas=(0.45, 0.45), duration=0.35)],
            "antenna_relax": [self._goto_payload(antennas=(-0.20, -0.20), duration=0.35)],
        }
        return steps.get(gesture)

    def _run_gesture(self, gesture: str, times: int, intensity: str, active_key: str) -> MotionResult:
        steps = self._gesture_steps(gesture, intensity)
        if steps is None:
            return self._unavailable_motion("gesture", gesture=gesture, times=times, intensity=intensity)
        responses: list[dict[str, object]] = []
        for _ in range(times):
            for step in steps:
                responses.append(self._post_goto(step, active_key=active_key))
                time.sleep(min(float(step.get("duration", 0.1)), 0.35))
        return MotionResult(
            action="gesture",
            message="Gesture fallback sequence sent to the Control App daemon.",
            details={"gesture": gesture, "times": times, "intensity": intensity, "steps": responses},
        )

    def _capture_frame_bytes(self) -> bytes:
        daemon_status = self._refresh_daemon_status()
        if self._should_capture_screen(daemon_status):
            self._last_capture_transport = "screen"
            return _capture_macos_screen(self.screen_crop)

        if _daemon_media_unavailable(daemon_status):
            raise ToolError(
                "Control App media is not available. Start the Control App camera/media mode "
                "or switch it out of no-media/released state, then try again."
            )

        if self.control_app_media_backend == "http":
            self._last_capture_transport = "http"
            return self._fetch_frame_bytes(self._camera_entrypoint_url())

        if self.control_app_media_backend == "local":
            self._last_capture_transport = "local"
            return self._capture_media_manager_frame("local")

        if self.control_app_media_backend == "webrtc":
            self._last_capture_transport = "webrtc"
            return self._capture_media_manager_frame("webrtc")

        # auto: prefer explicitly configured HTTP endpoint, otherwise use the
        # Control App's WebRTC stream. If HTTP fails, fall back to WebRTC because
        # current desktop Control App builds expose camera specs over REST but not
        # frame snapshots.
        errors: list[str] = []
        if self.camera_url or self.base_url:
            try:
                self._last_capture_transport = "http"
                return self._fetch_frame_bytes(self._camera_entrypoint_url())
            except ToolError as exc:
                errors.append(f"http: {exc}")

        for backend in ("webrtc", "local"):
            try:
                self._last_capture_transport = backend
                return self._capture_media_manager_frame(backend)
            except ToolError as exc:
                errors.append(f"{backend}: {exc}")

        raise ToolError("Control App camera capture failed. " + " | ".join(errors))

    def _should_capture_screen(self, daemon_status: dict[str, Any]) -> bool:
        # Screen capture is ONLY used when the user explicitly requests it via
        # capture_source="screen". In simulation mode the Control App exposes the
        # host webcam as Reachy Mini's camera, so we should still route through
        # the normal camera media stack (HTTP / WebRTC / local) rather than
        # falling back to a desktop screenshot.
        return self.capture_source == "screen"

    def _camera_entrypoint_url(self) -> str:
        if self.camera_url:
            return self.camera_url
        if not self.base_url:
            return ""
        return urljoin(self.base_url, self.camera_path)

    def _fetch_frame_bytes(self, url: str, depth: int = 0) -> bytes:
        if not url:
            raise ToolError("No Control App HTTP camera URL was configured.")
        if depth > 3:
            raise ToolError("Control App camera endpoint discovery exceeded redirect depth.")
        request = Request(url, headers=self._headers())
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:  # nosec B310
                content_type = response.headers.get("Content-Type", "")
                lower_content_type = content_type.lower()
                if "multipart/" in lower_content_type or "mjpeg" in lower_content_type:
                    return _read_first_jpeg_from_stream(response)

                data = response.read(_MAX_FRAME_BYTES + 1)
                if len(data) > _MAX_FRAME_BYTES:
                    raise ToolError("Control App camera response exceeded maximum frame size.")
        except HTTPError as exc:
            raise ToolError(f"Control App camera HTTP error {exc.code} for {_redact_url(url)}") from exc
        except URLError as exc:
            raise ToolError(f"Could not reach Control App camera at {_redact_url(url)}: {exc}") from exc
        except TimeoutError as exc:
            raise ToolError(f"Timed out reading Control App camera at {_redact_url(url)}") from exc

        if _looks_like_image(data) or _looks_like_ppm(data):
            return data
        stripped = data.strip()
        if "json" in lower_content_type or stripped.startswith(b"{"):
            return self._extract_json_image(stripped, url, depth)
        if "html" in lower_content_type or stripped.lower().startswith(b"<!doctype html") or b"<html" in stripped[:2048].lower():
            discovered_url = _discover_camera_src_from_html(stripped, url)
            if not discovered_url:
                raise ToolError(
                    "Control App returned HTML, but no camera img/video src could be discovered. "
                    "Set REACHY_MINI_CONTROL_APP_CAMERA_URL to the direct camera endpoint."
                )
            return self._fetch_frame_bytes(discovered_url, depth + 1)

        raise ToolError(
            f"Control App camera endpoint returned unsupported content type {content_type!r}. "
            "Use a JPEG/PNG snapshot, MJPEG stream, or JSON base64 image endpoint."
        )

    def _capture_media_manager_frame(self, backend: str) -> bytes:
        python = self._python_executable()
        if not python:
            raise ToolError(
                "Could not find a Python environment with reachy_mini and GStreamer. Set "
                "REACHY_MINI_CONTROL_APP_PYTHON to the Control App venv's python executable."
            )

        command = [
            python,
            "-c",
            _CAPTURE_SCRIPT,
            "--backend",
            backend,
            "--host",
            self.signaling_host,
            "--signaling-port",
            str(self.signaling_port),
            "--daemon-url",
            self.daemon_url.rstrip("/"),
            "--timeout",
            str(self.timeout_seconds),
        ]
        try:
            result = subprocess.run(  # noqa: S603 - executable is configured/discovered locally.
                command,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=max(self.timeout_seconds + 3.0, 5.0),
            )
        except subprocess.TimeoutExpired as exc:
            raise ToolError(f"Timed out capturing Control App {backend} camera frame.") from exc
        except OSError as exc:
            raise ToolError(f"Could not run Control App helper python {python!r}: {exc}") from exc

        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            if len(stderr) > 1200:
                stderr = stderr[-1200:]
            raise ToolError(
                f"Control App {backend} camera helper failed with exit code "
                f"{result.returncode}: {stderr or '<no stderr>'}"
            )

        frame = result.stdout
        if not (_looks_like_image(frame) or _looks_like_ppm(frame)):
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            raise ToolError(
                f"Control App {backend} camera helper did not return image bytes. "
                f"stderr: {stderr[-800:] if stderr else '<empty>'}"
            )
        if len(frame) > _MAX_FRAME_BYTES:
            raise ToolError("Control App camera helper returned a frame exceeding maximum size.")
        return frame

    def _extract_json_image(self, data: bytes, source_url: str, depth: int) -> bytes:
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ToolError("Control App camera JSON response could not be decoded.") from exc

        image = _find_base64_image(payload)
        if image is not None:
            return image

        nested_url = _find_url(payload)
        if nested_url:
            return self._fetch_frame_bytes(urljoin(source_url, nested_url), depth + 1)

        raise ToolError(
            "Control App camera JSON response did not contain an image_base64/frame/image field "
            "or a nested image URL."
        )

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "image/jpeg,image/png,multipart/x-mixed-replace,application/json,text/html;q=0.8,*/*;q=0.5",
            "User-Agent": "goose-reachy-mini-control-app-adapter/0.1",
        }
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        return headers

    def _python_executable(self) -> str | None:
        candidates: list[str] = []
        if self.python_executable:
            candidates.append(self.python_executable)
        candidates.extend(_default_control_app_python_candidates())
        candidates.append(sys.executable)

        seen: set[str] = set()
        for candidate in candidates:
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            path = Path(candidate).expanduser()
            if path.is_file() and os.access(path, os.X_OK):
                return str(path)
        return None

    def _unavailable_motion(self, action: str, **details: object) -> MotionResult:
        return MotionResult(
            status="unavailable",
            action=action,
            message=(
                f"{action} is not exposed by the Control App camera adapter. "
                "This adapter currently supports camera capture only."
            ),
            details=details,
        )


def _capture_macos_screen(crop: str | None = None) -> bytes:
    """Capture the visible macOS screen as PNG bytes, optionally cropped.

    This is a *user-opt-in* debugging / utility path enabled only when
    capture_source is explicitly set to "screen". It is NOT Reachy Mini's
    camera view, nor is it a screenshot of the Control App UI. It simply
    records the host desktop so the user can share their screen with the
    assistant when desired.

    This intentionally uses the built-in `screencapture` command instead of
    Accessibility APIs, because Accessibility permission is not always granted.
    Screen Recording permission may still be required by macOS.
    """

    if sys.platform != "darwin":
        raise ToolError("Screen capture source is currently implemented only on macOS.")

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        path = Path(tmp.name)
    try:
        result = subprocess.run(  # noqa: S603,S607 - built-in macOS utility.
            ["screencapture", "-x", "-t", "png", str(path)],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            raise ToolError(f"macOS screencapture failed: {stderr or '<no stderr>'}")
        data = path.read_bytes()
        if not _looks_like_image(data):
            raise ToolError("macOS screencapture did not return a PNG image.")
        if crop:
            data = _crop_png_bytes(data, crop)
        if len(data) > _MAX_FRAME_BYTES:
            raise ToolError("Screen capture exceeded maximum frame size.")
        return data
    except subprocess.TimeoutExpired as exc:
        raise ToolError("Timed out while capturing the macOS screen.") from exc
    finally:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _crop_png_bytes(data: bytes, crop: str) -> bytes:
    try:
        from PIL import Image

        parts = [int(part.strip()) for part in crop.split(",")]
        if len(parts) != 4:
            raise ValueError
        x, y, width, height = parts
        if min(x, y, width, height) < 0 or width == 0 or height == 0:
            raise ValueError
        image = Image.open(io.BytesIO(data))
        cropped = image.crop((x, y, x + width, y + height))
        out = io.BytesIO()
        cropped.save(out, format="PNG")
        return out.getvalue()
    except ValueError as exc:
        raise ToolError(
            "Invalid REACHY_MINI_CONTROL_APP_SCREEN_CROP. Use 'x,y,width,height'."
        ) from exc


def _default_control_app_python_candidates() -> list[str]:
    home = Path.home()
    candidates = [
        home
        / "Library/Application Support/com.pollen-robotics.reachy-mini/.venv/bin/python3",
        home
        / "Library/Application Support/com.pollen-robotics.reachy-mini/.venv/bin/python",
        home / ".local/share/com.pollen-robotics.reachy-mini/.venv/bin/python3",
        home / ".local/share/com.pollen-robotics.reachy-mini/.venv/bin/python",
        Path("/opt/reachy-mini/.venv/bin/python3"),
        Path("/opt/reachy-mini/.venv/bin/python"),
    ]
    return [str(path) for path in candidates]


def _normalize_base_url(value: str | None) -> str | None:
    if not value:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    if not stripped.endswith("/"):
        stripped += "/"
    return stripped


def _redact_url(url: str) -> str:
    if not url:
        return url
    return re.sub(r"([?&](?:token|access_token|api_key|key|auth)=)[^&]+", r"\1<redacted>", url, flags=re.I)


def _looks_like_image(data: bytes) -> bool:
    return data.startswith(b"\xff\xd8") or data.startswith(b"\x89PNG\r\n\x1a\n")


def _looks_like_ppm(data: bytes) -> bool:
    return data.startswith(b"P6\n") or data.startswith(b"P6\r\n")


def _read_first_jpeg_from_stream(response: Any) -> bytes:
    buffer = b""
    while len(buffer) <= _MAX_FRAME_BYTES:
        chunk = response.read(4096)
        if not chunk:
            break
        buffer += chunk
        start = buffer.find(b"\xff\xd8")
        if start == -1:
            # Keep the buffer bounded while searching for the SOI marker.
            buffer = buffer[-2:]
            continue
        end = buffer.find(b"\xff\xd9", start + 2)
        if end != -1:
            return buffer[start : end + 2]
    raise ToolError("Could not extract a JPEG frame from the Control App MJPEG stream.")


def _discover_camera_src_from_html(data: bytes, page_url: str) -> str | None:
    candidates = [html.unescape(match.decode("utf-8", errors="ignore")) for match in _HTML_SRC_RE.findall(data)]
    candidates = [candidate for candidate in candidates if candidate and not candidate.startswith("data:")]
    if not candidates:
        return None

    def score(src: str) -> int:
        lower = src.lower()
        terms = ("camera", "video", "stream", "mjpeg", "snapshot", "frame")
        return sum(1 for term in terms if term in lower)

    candidates.sort(key=score, reverse=True)
    return urljoin(page_url, candidates[0])


def _find_base64_image(payload: Any) -> bytes | None:
    if isinstance(payload, dict):
        for key in _IMAGE_KEYS:
            if key in payload:
                image = _decode_base64_image_value(payload[key])
                if image is not None:
                    return image
        for value in payload.values():
            image = _find_base64_image(value)
            if image is not None:
                return image
    elif isinstance(payload, list):
        for value in payload:
            image = _find_base64_image(value)
            if image is not None:
                return image
    elif isinstance(payload, str):
        return _decode_base64_image_value(payload)
    return None


def _find_url(payload: Any) -> str | None:
    if isinstance(payload, dict):
        for key in _URL_KEYS:
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        for value in payload.values():
            nested = _find_url(value)
            if nested:
                return nested
    elif isinstance(payload, list):
        for value in payload:
            nested = _find_url(value)
            if nested:
                return nested
    return None


def _decode_base64_image_value(value: Any) -> bytes | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.startswith("data:image/") and ";base64," in text:
        text = text.split(",", 1)[1]
    # Avoid attempting to decode URLs. Absolute paths are allowed to fall through
    # because valid base64 JPEG payloads commonly start with '/9j/'.
    if text.startswith(("http://", "https://")):
        return None
    try:
        decoded = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        return None
    return decoded if _looks_like_image(decoded.strip()) else None


def fetch_control_app_daemon_status(
    daemon_url: str | None = None,
    *,
    timeout_seconds: float = 1.0,
    auth_token: str | None = None,
) -> dict[str, Any] | None:
    """Return Control App daemon status if a reachable daemon is running."""

    for base_url in _candidate_daemon_urls(daemon_url):
        status_url = _daemon_status_url(base_url)
        request = Request(status_url, headers=_status_headers(auth_token))
        try:
            with urlopen(request, timeout=timeout_seconds) as response:  # nosec B310
                if response.status != 200:
                    continue
                payload = json.loads(response.read(512 * 1024).decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if _looks_like_control_app_status(payload):
            payload["_daemon_url"] = base_url.rstrip("/")
            return payload
    return None


def is_control_app_daemon_available(daemon_url: str | None = None) -> bool:
    """Return True when a Reachy Mini Control App daemon is reachable."""

    return fetch_control_app_daemon_status(daemon_url, timeout_seconds=0.5) is not None


def _candidate_daemon_urls(daemon_url: str | None) -> list[str]:
    candidates: list[str] = []
    if daemon_url:
        candidates.append(daemon_url)
    else:
        candidates.extend(_DEFAULT_DAEMON_URLS)

    seen: set[str] = set()
    result: list[str] = []
    for candidate in candidates:
        normalized = _normalize_base_url(candidate)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _daemon_status_url(daemon_url: str | None) -> str:
    base_url = _normalize_base_url(daemon_url) or _DEFAULT_DAEMON_URLS[0] + "/"
    return urljoin(base_url, "/api/daemon/status")


def _status_headers(auth_token: str | None = None) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "goose-reachy-mini-control-app-detector/0.1",
    }
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    return headers


def _looks_like_control_app_status(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    return payload.get("type") == "daemon_status" or payload.get("robot_name") == "reachy_mini"


def _daemon_mode(status: dict[str, Any]) -> str:
    if status.get("simulation_enabled"):
        return "simulation"
    if status.get("mockup_sim_enabled"):
        return "mockup_simulation"
    if status.get("wireless_version"):
        return "real_wireless"
    if status:
        return "real_or_lite"
    return "unknown"


def _daemon_media_available(status: dict[str, Any]) -> bool:
    if not status:
        return True
    return not bool(status.get("no_media", False) or status.get("media_released", False))


def _daemon_media_unavailable(status: dict[str, Any]) -> bool:
    return not _daemon_media_available(status)


def _host_from_url(url: str | None) -> str | None:
    if not url:
        return None
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    return parsed.hostname
