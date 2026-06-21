from __future__ import annotations

import base64

import pytest
from mcp.types import ImageContent, TextContent

from goose_reachy_mini.mock_reachy import MockReachyClient
from goose_reachy_mini.schemas import Settings
from goose_reachy_mini.tools import TOOL_NAMES, ReachyTools


def make_tools(settings: Settings | None = None) -> tuple[ReachyTools, MockReachyClient]:
    settings = settings or Settings(mock=True)
    client = MockReachyClient()
    return ReachyTools(client, settings), client


def test_tool_names_are_final_public_list() -> None:
    assert TOOL_NAMES == [
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


def test_status_mock_mode() -> None:
    tools, _client = make_tools()
    status = tools.reachy_get_status()
    assert status["mock_mode"] is True
    assert status["connected"] is True
    assert "happy" in status["available_expression_intents"]


def test_idle_no_action() -> None:
    tools, client = make_tools()
    assert tools.reachy_idle()["status"] == "ok"
    assert client.calls == []


def test_mock_capture_image_returns_image_content() -> None:
    tools, _client = make_tools()
    result = tools.reachy_capture_image()
    assert isinstance(result, list)
    assert len(result) >= 1
    img = result[0]
    assert isinstance(img, ImageContent)
    assert img.mimeType == "image/jpeg"
    assert base64.b64decode(img.data)
    # Metadata text is included by default
    if len(result) > 1:
        assert isinstance(result[1], TextContent)
        assert "Camera frame" in result[1].text


def test_describe_current_view_returns_image_and_instruction() -> None:
    tools, _client = make_tools()
    result = tools.reachy_describe_current_view(detail_level="brief")
    assert isinstance(result, list)
    assert len(result) == 2
    img = result[0]
    assert isinstance(img, ImageContent)
    assert img.mimeType == "image/jpeg"
    text = result[1]
    assert isinstance(text, TextContent)
    assert "한국어" in text.text


def test_image_region_enum_rejects_raw_coordinates() -> None:
    tools, _client = make_tools()
    result = tools.reachy_look_at_image_region(region="100,200")
    assert result["status"] == "error"


def test_look_at_image_region_records_action() -> None:
    tools, client = make_tools()
    result = tools.reachy_look_at_image_region(region="upper_right", intensity="small")
    assert result["status"] == "ok"
    assert client.calls[-1][0] == "look_at_image_region"


@pytest.mark.parametrize(
    ("method", "kwargs"),
    [
        ("reachy_look", {"direction": "sideways"}),
        ("reachy_gesture", {"gesture": "spin_forever"}),
        ("reachy_turn_body", {"direction": "around"}),
        ("reachy_track_head", {"enabled": True, "mode": "everything"}),
        ("reachy_play_expression", {"expression": "raw_file_path"}),
        ("reachy_dance", {"dance": "../../unsafe"}),
    ],
)
def test_invalid_enums_are_rejected(method: str, kwargs: dict[str, object]) -> None:
    tools, _client = make_tools()
    result = getattr(tools, method)(**kwargs)
    assert result["status"] == "error"


def test_gesture_times_limit() -> None:
    tools, _client = make_tools(Settings(mock=True, max_gesture_times=3))
    result = tools.reachy_gesture(gesture="yes", times=4)
    assert result["status"] == "error"
    assert "exceeds maximum" in result["message"]


def test_expression_duration_limit() -> None:
    tools, _client = make_tools(Settings(mock=True, max_expression_seconds=5))
    result = tools.reachy_play_expression(expression="happy", duration_seconds=6)
    assert result["status"] == "error"


def test_dance_repeat_limit() -> None:
    tools, _client = make_tools(Settings(mock=True, max_dance_repeat=3))
    result = tools.reachy_dance(dance="random", repeat=4)
    assert result["status"] == "error"


def test_tracking_duration_limit() -> None:
    tools, _client = make_tools(Settings(mock=True, max_tracking_seconds=10))
    result = tools.reachy_track_head(enabled=True, duration_seconds=11)
    assert result["status"] == "error"


def test_motion_disabled_blocks_motion_tools() -> None:
    tools, _client = make_tools(Settings(mock=True, enable_motion=False))
    result = tools.reachy_look(direction="left")
    assert result["status"] == "error"
    assert "Motion is disabled" in result["message"]


def test_camera_disabled_blocks_camera_tools() -> None:
    tools, _client = make_tools(Settings(mock=True, enable_camera=False))
    result = tools.reachy_capture_image()
    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], TextContent)
    assert "Camera is disabled" in result[0].text


def test_camera_unavailable_returns_clear_error() -> None:
    tools, client = make_tools()
    client.camera_available = False

    def broken_frame() -> object:
        raise RuntimeError("camera unavailable")

    client.get_frame = broken_frame  # type: ignore[method-assign]
    result = tools.reachy_capture_image()
    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], TextContent)
    assert "camera unavailable" in result[0].text


def test_audio_disabled_blocks_audio_tools() -> None:
    tools, _client = make_tools(Settings(mock=True, enable_audio=False))
    result = tools.reachy_listen_audio_sample()
    assert result["status"] == "error"
    assert "Audio is disabled" in result["message"]


def test_imu_unstable_blocks_motion() -> None:
    tools, client = make_tools()
    client.imu_motion_state = "unstable"
    result = tools.reachy_gesture(gesture="yes")
    assert result["status"] == "error"
    assert "blocked" in result["message"]


def test_sound_direction_and_look_toward_sound() -> None:
    tools, client = make_tools()
    result = tools.reachy_look_toward_sound()
    assert result["moved"] is True
    assert [call[0] for call in client.calls][-2:] == ["listen_direction", "look"]


def test_look_toward_sound_noop_without_speech() -> None:
    tools, client = make_tools()
    client.speech_detected = False
    result = tools.reachy_look_toward_sound()
    assert result["moved"] is False
    assert [call[0] for call in client.calls] == ["listen_direction"]


def test_expression_dance_stop_idempotent() -> None:
    tools, _client = make_tools()
    assert tools.reachy_stop_expression()["status"] == "ok"
    assert tools.reachy_stop_dance()["status"] == "ok"


def test_audio_payload_roundtrip() -> None:
    tools, client = make_tools()
    payload = base64.b64encode(b"hello audio").decode("ascii")
    result = tools.reachy_play_audio(audio_base64=payload, mime_type="audio/wav")
    assert result["status"] == "ok"
    assert client.last_audio == b"hello audio"


def test_bad_audio_mime_rejected() -> None:
    tools, _client = make_tools()
    payload = base64.b64encode(b"hello audio").decode("ascii")
    result = tools.reachy_play_audio(audio_base64=payload, mime_type="text/plain")
    assert result["status"] == "error"


def test_say_text_mock_succeeds_without_real_tts() -> None:
    tools, client = make_tools()
    result = tools.reachy_say_text(text="안녕하세요", wobble=True)
    assert result["status"] == "ok"
    assert client.calls[-1][0] == "say_text"


def test_say_text_real_mode_without_tts_backend_returns_guidance() -> None:
    tools, client = make_tools(Settings(mock=False, tts_backend=None))
    result = tools.reachy_say_text(text="안녕하세요", wobble=False)
    assert result["status"] == "unavailable"
    assert "TTS backend is not configured" in result["message"]
    assert client.calls == []
