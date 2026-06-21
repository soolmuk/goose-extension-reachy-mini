from __future__ import annotations

import base64
import contextlib
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Iterator

from PIL import Image

from goose_reachy_mini.control_app_client import ControlAppClient, _crop_png_bytes
from goose_reachy_mini.mock_reachy import MockReachyClient
from goose_reachy_mini.schemas import Settings
from goose_reachy_mini.server import create_client
from goose_reachy_mini.vision import encode_frame_for_mcp


def _jpeg_bytes() -> bytes:
    image = Image.new("RGB", (32, 24), color=(10, 20, 30))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


class _Handler(BaseHTTPRequestHandler):
    jpeg = _jpeg_bytes()
    daemon_status: dict[str, object] = {
        "type": "daemon_status",
        "robot_name": "reachy_mini",
        "mockup_sim_enabled": True,
        "simulation_enabled": False,
        "wireless_version": False,
        "no_media": False,
        "media_released": False,
    }
    posts: list[tuple[str, dict[str, object]]] = []

    def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
        if self.path == "/snapshot.jpg":
            self._send(200, "image/jpeg", self.jpeg)
        elif self.path == "/api/frame":
            payload = {"image_base64": base64.b64encode(self.jpeg).decode("ascii")}
            self._send(200, "application/json", json.dumps(payload).encode("utf-8"))
        elif self.path == "/api/daemon/status":
            self._send(200, "application/json", json.dumps(self.daemon_status).encode("utf-8"))
        elif self.path == "/":
            self._send(200, "text/html", b'<html><body><img src="/snapshot.jpg"></body></html>')
        else:
            self._send(404, "text/plain", b"not found")

    def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b"{}"
        payload = json.loads(body.decode("utf-8")) if body.strip() else {}
        self.posts.append((self.path, payload))
        if self.path == "/api/move/goto":
            self._send(200, "application/json", b'{"uuid":"00000000-0000-0000-0000-000000000001"}')
        elif self.path == "/api/move/stop":
            self._send(200, "application/json", b'{"message":"stopped"}')
        else:
            self._send(404, "application/json", b'{"detail":"not found"}')

    def log_message(self, format: str, *args: object) -> None:
        return None

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@contextlib.contextmanager
def _server() -> Iterator[str]:
    _Handler.posts = []
    _Handler.daemon_status = {
        "type": "daemon_status",
        "robot_name": "reachy_mini",
        "mockup_sim_enabled": True,
        "simulation_enabled": False,
        "wireless_version": False,
        "no_media": False,
        "media_released": False,
    }
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_control_app_client_reads_direct_jpeg_snapshot() -> None:
    with _server() as base_url:
        client = ControlAppClient(camera_url=f"{base_url}/snapshot.jpg")
        frame = client.get_frame()
        payload = encode_frame_for_mcp(frame)

    assert payload.mime_type == "image/jpeg"
    assert payload.width == 32
    assert payload.height == 24
    assert client.get_status()["control_app_mode"] is True


def test_control_app_client_reads_json_base64_frame() -> None:
    with _server() as base_url:
        client = ControlAppClient(camera_url=f"{base_url}/api/frame")
        frame = client.get_frame()
        payload = encode_frame_for_mcp(frame)

    assert payload.width == 32
    assert payload.height == 24


def test_control_app_client_discovers_camera_src_from_html() -> None:
    with _server() as base_url:
        client = ControlAppClient(base_url=base_url, camera_path="/")
        frame = client.get_frame()
        payload = encode_frame_for_mcp(frame)

    assert payload.width == 32
    assert payload.height == 24


def test_create_client_prefers_control_app_over_mock() -> None:
    settings = Settings(mock=True, control_app=True, control_app_camera_url="http://127.0.0.1/cam")
    client = create_client(settings)
    assert isinstance(client, ControlAppClient)
    assert client.get_status()["camera_source"] == "http://127.0.0.1/cam"



def test_control_app_client_reads_helper_ppm_frame(tmp_path) -> None:
    fake_python = tmp_path / "fake-python"
    # Minimal 2x1 binary PPM: red pixel, green pixel.
    fake_python.write_bytes(
        b"#!/bin/sh\nprintf 'P6\\n2 1\\n255\\n\\377\\000\\000\\000\\377\\000'\n"
    )
    fake_python.chmod(0o755)

    client = ControlAppClient(
        media_backend="webrtc",
        python_executable=str(fake_python),
        timeout_seconds=1,
    )
    frame = client.get_frame()
    payload = encode_frame_for_mcp(frame)

    assert payload.width == 2
    assert payload.height == 1
    assert client.get_status()["last_capture_transport"] == "webrtc"


def test_settings_builds_control_app_client_with_media_backend() -> None:
    settings = Settings(
        mock=False,
        control_app=True,
        control_app_media_backend="webrtc",
        control_app_daemon_url="http://127.0.0.1:8000",
        control_app_signaling_host="localhost",
        control_app_signaling_port=8443,
    )
    client = create_client(settings)

    assert isinstance(client, ControlAppClient)
    status = client.get_status()
    assert status["control_app_media_backend"] == "webrtc"
    assert status["daemon_url"] == "http://127.0.0.1:8000"


def test_auto_detects_running_control_app_when_mock_not_explicit(monkeypatch) -> None:
    daemon_status = {
        "type": "daemon_status",
        "robot_name": "reachy_mini",
        "state": "running",
        "mockup_sim_enabled": True,
        "no_media": False,
        "media_released": False,
        "_daemon_url": "http://127.0.0.1:8000",
    }
    monkeypatch.setattr(
        "goose_reachy_mini.server.fetch_control_app_daemon_status",
        lambda *args, **kwargs: daemon_status,
    )

    settings = Settings(mock=True, mock_explicit=False, control_app_auto=True)
    client = create_client(settings)

    assert isinstance(client, ControlAppClient)
    assert client.daemon_url == "http://127.0.0.1:8000"


def test_explicit_mock_disables_control_app_auto_detection(monkeypatch) -> None:
    # When Control App daemon is NOT running and user explicitly asked for mock,
    # mock should be used.
    monkeypatch.setattr(
        "goose_reachy_mini.server.fetch_control_app_daemon_status",
        lambda *args, **kwargs: None,
    )

    settings = Settings(mock=True, mock_explicit=True, control_app_auto=True)
    client = create_client(settings)

    assert isinstance(client, MockReachyClient)


def test_auto_detect_prefers_control_app_when_running(monkeypatch) -> None:
    # When Control App daemon IS running, auto-detect should prefer it
    # even if mock_explicit is True — the user wants to know the actual mode.
    monkeypatch.setattr(
        "goose_reachy_mini.server.fetch_control_app_daemon_status",
        lambda *args, **kwargs: {"type": "daemon_status", "robot_name": "reachy_mini"},
    )

    settings = Settings(mock=True, mock_explicit=True, control_app_auto=True)
    client = create_client(settings)

    assert isinstance(client, ControlAppClient)


def test_control_app_status_exposes_runtime_mode(monkeypatch) -> None:
    daemon_status = {
        "type": "daemon_status",
        "robot_name": "reachy_mini",
        "state": "running",
        "mockup_sim_enabled": True,
        "simulation_enabled": False,
        "wireless_version": False,
        "no_media": False,
        "media_released": False,
        "camera_specs_name": "generic",
    }
    monkeypatch.setattr(
        "goose_reachy_mini.control_app_client.fetch_control_app_daemon_status",
        lambda *args, **kwargs: None,
    )

    client = ControlAppClient(daemon_status=daemon_status)
    status = client.get_status()

    assert status["control_app_runtime_mode"] == "mockup_simulation"
    assert status["control_app_mockup_sim_enabled"] is True
    assert status["control_app_camera_specs_name"] == "generic"


def test_screen_capture_source_status_fields() -> None:
    client = ControlAppClient(capture_source="screen", screen_crop="1,2,3,4")
    status = client.get_status()
    assert status["control_app_capture_source"] == "screen"
    assert status["control_app_screen_crop"] == "1,2,3,4"


def test_crop_png_bytes() -> None:
    image = Image.new("RGB", (4, 3), color=(0, 0, 0))
    image.putpixel((1, 1), (255, 0, 0))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")

    cropped = _crop_png_bytes(buffer.getvalue(), "1,1,2,1")
    cropped_image = Image.open(io.BytesIO(cropped))

    assert cropped_image.size == (2, 1)
    assert cropped_image.getpixel((0, 0))[:3] == (255, 0, 0)


def test_auto_capture_source_does_not_fallback_to_screen_for_simulation() -> None:
    # In simulation mode the Control App exposes the host webcam as Reachy
    # Mini's camera, so auto should route through the media stack, not desktop
    # screen capture.
    client = ControlAppClient(
        media_backend="auto",
        daemon_status={"mockup_sim_enabled": True, "no_media": False, "media_released": False},
    )
    assert client._should_capture_screen({"mockup_sim_enabled": True}) is False


def test_camera_capture_source_disables_screen_for_simulation() -> None:
    client = ControlAppClient(capture_source="camera", media_backend="auto")
    assert client._should_capture_screen({"mockup_sim_enabled": True}) is False


def test_screen_capture_source_explicitly_enables_desktop_capture() -> None:
    client = ControlAppClient(capture_source="screen", media_backend="auto")
    assert client._should_capture_screen({"mockup_sim_enabled": True}) is True
    assert client._should_capture_screen({"mockup_sim_enabled": False}) is True


def test_control_app_simulation_policy_exposes_motion_available(monkeypatch) -> None:
    monkeypatch.setattr(
        "goose_reachy_mini.control_app_client.fetch_control_app_daemon_status",
        lambda *args, **kwargs: None,
    )
    client = ControlAppClient(
        daemon_status={
            "type": "daemon_status",
            "robot_name": "reachy_mini",
            "mockup_sim_enabled": True,
            "simulation_enabled": False,
        },
        preset_policy="simulation_only",
    )

    status = client.get_status()

    assert status["motion_available"] is True
    assert status["recorded_emotions_available"] is True
    assert status["dances_available"] is True
    assert status["control_app_preset_policy"] == "simulation_only"


def test_control_app_real_mode_blocks_motion_by_default(monkeypatch) -> None:
    monkeypatch.setattr(
        "goose_reachy_mini.control_app_client.fetch_control_app_daemon_status",
        lambda *args, **kwargs: None,
    )
    client = ControlAppClient(
        daemon_status={
            "type": "daemon_status",
            "robot_name": "reachy_mini",
            "wireless_version": True,
        },
        preset_policy="simulation_only",
    )

    result = client.look("left", "small")

    assert result.status == "unavailable"
    assert "simulation modes" in (result.message or "")


def test_control_app_look_posts_goto_in_simulation() -> None:
    with _server() as base_url:
        client = ControlAppClient(
            base_url=base_url,
            daemon_url=base_url,
            preset_policy="simulation_only",
            motion_timeout_seconds=1,
        )
        result = client.look("left", "small")

    assert result.status == "ok"
    assert _Handler.posts
    path, payload = _Handler.posts[0]
    assert path == "/api/move/goto"
    assert payload["duration"] == 0.6
    assert payload["head_pose"]["yaw"] == 0.25


def test_control_app_reset_pose_posts_full_neutral_payload() -> None:
    with _server() as base_url:
        client = ControlAppClient(
            base_url=base_url,
            daemon_url=base_url,
            preset_policy="simulation_only",
            motion_timeout_seconds=1,
        )
        result = client.reset_pose()

    assert result.status == "ok"
    path, payload = _Handler.posts[0]
    assert path == "/api/move/goto"
    assert payload["head_pose"] == {"x": 0.0, "y": 0.0, "z": 0.0, "roll": 0.0, "pitch": 0.0, "yaw": 0.0}
    assert payload["antennas"] == [0.0, 0.0]
    assert payload["body_yaw"] == 0.0


def test_control_app_stop_dance_uses_tracked_move_uuid() -> None:
    with _server() as base_url:
        client = ControlAppClient(
            base_url=base_url,
            daemon_url=base_url,
            preset_policy="simulation_only",
            motion_timeout_seconds=1,
        )
        dance_result = client.dance("happy_wiggle", 1)
        stop_result = client.stop_dance()

    assert dance_result.status == "ok"
    assert stop_result.status == "ok"
    assert _Handler.posts[-1] == (
        "/api/move/stop",
        {"uuid": "00000000-0000-0000-0000-000000000001"},
    )


def test_control_app_look_up_uses_negative_pitch_in_simulation() -> None:
    with _server() as base_url:
        client = ControlAppClient(
            base_url=base_url,
            daemon_url=base_url,
            preset_policy="simulation_only",
            motion_timeout_seconds=1,
        )
        result = client.look("up", "small")

    assert result.status == "ok"
    path, payload = _Handler.posts[0]
    assert path == "/api/move/goto"
    assert payload["head_pose"]["pitch"] == -0.20


def test_control_app_upper_image_region_uses_negative_pitch_in_simulation() -> None:
    with _server() as base_url:
        client = ControlAppClient(
            base_url=base_url,
            daemon_url=base_url,
            preset_policy="simulation_only",
            motion_timeout_seconds=1,
        )
        result = client.look_at_image_region("upper_left", "small")

    assert result.status == "ok"
    path, payload = _Handler.posts[0]
    assert path == "/api/move/goto"
    assert payload["head_pose"]["yaw"] == 0.22
    assert payload["head_pose"]["pitch"] == -0.18
