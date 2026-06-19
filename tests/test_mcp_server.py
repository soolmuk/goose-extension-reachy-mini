from __future__ import annotations

import pytest

from goose_reachy_mini.mock_reachy import MockReachyClient
from goose_reachy_mini.schemas import Settings
from goose_reachy_mini.server import create_mcp_server
from goose_reachy_mini.tools import TOOL_NAMES


@pytest.mark.asyncio
async def test_mcp_server_lists_tools() -> None:
    server = create_mcp_server(settings=Settings(mock=True), client=MockReachyClient())
    tools = await server.list_tools()
    names = [tool.name for tool in tools]
    assert names == TOOL_NAMES


@pytest.mark.asyncio
async def test_mcp_call_status() -> None:
    server = create_mcp_server(settings=Settings(mock=True), client=MockReachyClient())
    result = await server.call_tool("reachy_get_status", {})
    # FastMCP may return content blocks or a structured dict depending on SDK version.
    assert result


@pytest.mark.asyncio
async def test_mcp_tool_schema_has_real_parameters() -> None:
    server = create_mcp_server(settings=Settings(mock=True), client=MockReachyClient())
    tools = await server.list_tools()
    capture = next(tool for tool in tools if tool.name == "reachy_capture_image")
    assert "format" in capture.inputSchema["properties"]
    assert "kwargs" not in capture.inputSchema["properties"]
