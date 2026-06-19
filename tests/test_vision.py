from __future__ import annotations

import base64

from PIL import Image

from goose_reachy_mini.schemas import FrameResult
from goose_reachy_mini.vision import encode_frame_for_mcp


def test_large_image_is_resized() -> None:
    image = Image.new("RGB", (3000, 2000), color=(255, 0, 0))
    payload = encode_frame_for_mcp(FrameResult(data=image), max_size=640)
    assert max(payload.width, payload.height) == 640
    assert base64.b64decode(payload.image_base64)


def test_png_encoding() -> None:
    image = Image.new("RGB", (20, 20), color=(0, 255, 0))
    payload = encode_frame_for_mcp(FrameResult(data=image), image_format="png")
    assert payload.mime_type == "image/png"
