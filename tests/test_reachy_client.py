from __future__ import annotations

from goose_reachy_mini.reachy_client import ReachyClient


def test_real_client_import_failure_is_graceful() -> None:
    client = ReachyClient(media_backend="default")
    status = client.get_status()
    assert "connected" in status
    assert status["mock_mode"] is False
    # In environments without hardware/SDK it should not raise and should expose error info.
    if not status["connected"]:
        assert status["error"]
