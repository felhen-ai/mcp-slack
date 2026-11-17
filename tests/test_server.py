"""Smoke and contract tests for the MCP server module.

The unit tests exercise the tool functions directly, so nothing else imports
``mcp_slack.server``. These tests make sure the server module — and the MCP SDK
API it depends on — still imports and registers every tool. This is what
breaks when the ``mcp`` package ships an incompatible major version
(``mcp`` 2.0.0 removed ``mcp.server.fastmcp``).

They also pin the safety annotations: every tool must declare whether it only
reads or performs an external write, so a new tool cannot omit them.
"""

from __future__ import annotations

import asyncio

from mcp_slack import server

READ_TOOLS = {"slack_list_channels", "slack_find_user", "slack_read_channel"}
WRITE_TOOLS = {"slack_post_message"}


def _tools() -> dict:
    return {tool.name: tool for tool in asyncio.run(server.mcp.list_tools())}


def test_server_module_imports() -> None:
    assert server.mcp.name == "mcp-slack"


def test_server_registers_tools() -> None:
    assert set(_tools()) == READ_TOOLS | WRITE_TOOLS


def test_every_tool_declares_safety_annotations() -> None:
    for name, tool in _tools().items():
        ann = tool.annotations
        assert ann is not None, name
        assert ann.readOnlyHint is not None, name
        assert ann.destructiveHint is not None, name
        assert ann.openWorldHint is True, name


def test_read_tools_are_read_only() -> None:
    tools = _tools()
    for name in READ_TOOLS:
        assert tools[name].annotations.readOnlyHint is True, name
        assert tools[name].annotations.destructiveHint is False, name


def test_post_message_is_marked_as_write() -> None:
    ann = _tools()["slack_post_message"].annotations
    assert ann.readOnlyHint is False
    assert ann.idempotentHint is False
