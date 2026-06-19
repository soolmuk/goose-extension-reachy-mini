"""MCP stdio server entrypoint for the Reachy Mini goose extension."""

from __future__ import annotations

import argparse
import signal
import sys

from mcp.server.fastmcp import FastMCP

from .control_app_client import ControlAppClient, fetch_control_app_daemon_status
from .mock_reachy import MockReachyClient
from .reachy_client import ReachyClient
from .schemas import Settings
from .tools import TOOL_NAMES, ReachyTools

_SERVER_NAME = "goose-reachy-mini"


def create_client(settings: Settings) -> MockReachyClient | ReachyClient | ControlAppClient:
    """Create the configured Reachy client adapter."""

    daemon_status = None
    if settings.control_app:
        daemon_status = fetch_control_app_daemon_status(
            settings.control_app_daemon_url or settings.control_app_url,
            timeout_seconds=min(settings.control_app_timeout_seconds, 1.0),
            auth_token=settings.control_app_auth_token,
        )
        return _create_control_app_client(settings, daemon_status)

    if settings.control_app_auto and not settings.mock_explicit:
        daemon_status = fetch_control_app_daemon_status(
            settings.control_app_daemon_url or settings.control_app_url,
            timeout_seconds=min(settings.control_app_timeout_seconds, 1.0),
            auth_token=settings.control_app_auth_token,
        )
        if daemon_status is not None:
            settings.control_app = True
            settings.mock = False
            return _create_control_app_client(settings, daemon_status)

    if settings.mock:
        return MockReachyClient(media_backend=settings.media_backend)
    return ReachyClient(media_backend=settings.media_backend)


def _create_control_app_client(
    settings: Settings,
    daemon_status: dict[str, object] | None = None,
) -> ControlAppClient:
    daemon_url = settings.control_app_daemon_url or settings.control_app_url
    if daemon_status is not None and isinstance(daemon_status.get("_daemon_url"), str):
        daemon_url = str(daemon_status["_daemon_url"])

    signaling_host = settings.control_app_signaling_host
    if signaling_host == "localhost" and daemon_url:
        try:
            from urllib.parse import urlparse

            signaling_host = urlparse(daemon_url).hostname or signaling_host
        except ValueError:
            pass

    return ControlAppClient(
        base_url=settings.control_app_url or daemon_url,
        camera_url=settings.control_app_camera_url,
        camera_path=settings.control_app_camera_path,
        timeout_seconds=settings.control_app_timeout_seconds,
        auth_token=settings.control_app_auth_token,
        media_backend=settings.control_app_media_backend,
        capture_source=settings.control_app_capture_source,
        screen_crop=settings.control_app_screen_crop,
        python_executable=settings.control_app_python,
        daemon_url=daemon_url,
        signaling_host=signaling_host,
        signaling_port=settings.control_app_signaling_port,
        daemon_status=daemon_status,
    )


def create_mcp_server(
    settings: Settings | None = None,
    client: MockReachyClient | ReachyClient | ControlAppClient | None = None,
) -> FastMCP:
    """Create a configured FastMCP server with all public tools registered."""

    settings = settings or Settings.from_env()
    client = client or create_client(settings)
    tools = ReachyTools(client, settings)
    mcp = FastMCP(
        _SERVER_NAME,
        instructions=(
            "Safe high-level Reachy Mini tools for status, camera, attention, motion, "
            "expression, dance, and short audio. Do not use camera or microphone tools "
            "unless the user explicitly requests them."
        ),
    )

    for name in TOOL_NAMES:
        fn = getattr(tools, name)
        mcp.add_tool(fn, name=name, description=(fn.__doc__ or "").strip())

    # Keep the client alive as long as the server object is alive for tests/cleanup.
    mcp._reachy_client = client  # type: ignore[attr-defined]
    return mcp


def main(argv: list[str] | None = None) -> None:
    """Run Reachy Mini MCP server over stdio."""

    parser = argparse.ArgumentParser(description="Reachy Mini MCP stdio server for goose")
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Force mock mode regardless of REACHY_MINI_MOCK.",
    )
    parser.add_argument(
        "--control-app",
        action="store_true",
        help="Use the Reachy Mini Control App HTTP camera adapter.",
    )
    parser.add_argument(
        "--list-tools",
        action="store_true",
        help="Print public tool names and exit (does not start stdio server).",
    )
    args = parser.parse_args(argv)

    if args.list_tools:
        for name in TOOL_NAMES:
            print(name)
        return

    settings = Settings.from_env()
    if args.control_app:
        settings.control_app = True
        settings.mock = False
    if args.mock:
        settings.mock = True
        settings.control_app = False
    client = create_client(settings)

    def _cleanup(signum: int, _frame: object) -> None:
        close = getattr(client, "close", None)
        if callable(close):
            close()
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGINT, _cleanup)
    signal.signal(signal.SIGTERM, _cleanup)

    mcp = create_mcp_server(settings=settings, client=client)
    try:
        mcp.run(transport="stdio")
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()


if __name__ == "__main__":
    main(sys.argv[1:])
