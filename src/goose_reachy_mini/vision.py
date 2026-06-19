"""Vision helpers for MCP-safe image payloads."""

from __future__ import annotations

import base64
import io
from datetime import UTC, datetime
from typing import Any

from PIL import Image

from .schemas import FrameResult, ImagePayload, ToolError

REGION_TO_LOOK = {
    "center": ("center", "small"),
    "upper_left": ("front_left", "small"),
    "upper_right": ("front_right", "small"),
    "lower_left": ("front_left", "small"),
    "lower_right": ("front_right", "small"),
    "person_candidate": ("center", "small"),
    "object_candidate": ("center", "small"),
}


def encode_frame_for_mcp(
    frame: FrameResult | object,
    image_format: str = "jpeg",
    max_size: int = 1280,
) -> ImagePayload:
    """Convert a Reachy frame-like object to a base64 image payload."""

    image = normalize_frame_to_image(frame)
    image.thumbnail((max_size, max_size))

    fmt = image_format.lower()
    if fmt not in {"jpeg", "png"}:
        raise ToolError(f"Unsupported image format {image_format!r}. Use 'jpeg' or 'png'.")
    if fmt == "jpeg" and image.mode not in {"RGB", "L"}:
        image = image.convert("RGB")

    buffer = io.BytesIO()
    save_format = "JPEG" if fmt == "jpeg" else "PNG"
    image.save(buffer, format=save_format)
    return ImagePayload(
        image_base64=base64.b64encode(buffer.getvalue()).decode("ascii"),
        mime_type="image/jpeg" if fmt == "jpeg" else "image/png",
        width=image.width,
        height=image.height,
        timestamp=_frame_timestamp(frame),
    )


def normalize_frame_to_image(frame: FrameResult | object) -> Image.Image:
    """Normalize common SDK frame shapes to a PIL Image."""

    data = frame.data if isinstance(frame, FrameResult) else frame

    if isinstance(data, Image.Image):
        return data.copy()
    if isinstance(data, bytes | bytearray):
        return Image.open(io.BytesIO(data)).convert("RGB")
    if hasattr(data, "image"):
        return normalize_frame_to_image(data.image)
    if hasattr(data, "data") and isinstance(data.data, bytes | bytearray):
        return normalize_frame_to_image(data.data)
    if hasattr(data, "to_image") and callable(data.to_image):
        return normalize_frame_to_image(data.to_image())

    # Optional numpy support without adding a hard dependency.
    if hasattr(data, "shape") and hasattr(data, "dtype"):
        try:
            return Image.fromarray(data).convert("RGB")
        except Exception as exc:  # pragma: no cover - depends on frame type
            raise ToolError(f"Could not convert array frame to image: {exc}") from exc

    raise ToolError(f"Unsupported camera frame type: {type(data).__name__}")


def build_scene_description_instruction(detail_level: str) -> str:
    detail = {
        "brief": "간단히 한두 문장으로",
        "normal": "핵심 사람, 사물, 위치 관계를 포함해",
        "detailed": "가능한 자세히, 단 민감한 신원 추정은 피하고",
    }.get(detail_level, "핵심 사람, 사물, 위치 관계를 포함해")
    return (
        f"이 이미지를 보고 현재 Reachy Mini 앞 장면을 한국어로 {detail} 설명하세요. "
        "사람, 사물, 장애물 또는 안전상 주의할 점이 보이면 언급하세요. "
        "얼굴 신원 식별이나 민감한 속성 추정은 하지 마세요."
    )


def region_to_motion(region: str, intensity: str) -> dict[str, str]:
    """Map a public image region preset to a safe internal look preset."""

    if region not in REGION_TO_LOOK:
        raise ToolError(f"Unsupported image region {region!r}.")
    direction, default_intensity = REGION_TO_LOOK[region]
    return {"direction": direction, "intensity": intensity or default_intensity}


def _frame_timestamp(frame: Any) -> str:
    timestamp = getattr(frame, "timestamp", None)
    if isinstance(timestamp, datetime):
        return timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
