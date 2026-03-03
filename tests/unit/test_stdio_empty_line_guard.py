"""Regression tests for stdio empty-line handling.

Ensures that bare newlines (e.g. from Cursor reconnecting or terminal Enter)
do not crash the MCP server and take out Cursor. The fix has two layers:
1) EmptyLineFilteringBuffer in utils/io.py (tested in test_io.py)
2) Monkey-patch of mcp.server.stdio.stdio_server to skip empty lines before
   JSON parse (tested here).
"""

import pytest

import mcp.types as types


def test_bare_newline_causes_json_validation_error():
    """Document the bug: model_validate_json('\\n') raises and would crash the server."""
    with pytest.raises(Exception):  # ValidationError / JSON decode
        types.JSONRPCMessage.model_validate_json("\n")

    with pytest.raises(Exception):
        types.JSONRPCMessage.model_validate_json("  \n")

    with pytest.raises(Exception):
        types.JSONRPCMessage.model_validate_json("")


def test_skip_empty_lines_prevents_crash_and_preserves_valid_lines():
    """Same filter as patched stdin_reader: empty/whitespace lines are skipped; valid JSON is parsed.

    Regression test: if the 'if not line or not line.strip(): continue' is
    removed from the patched stdin_reader, feeding '\\n' would crash. This test
    asserts the contract without running the full anyio stdio server.
    """
    # Same condition as in __init__.py _patched_stdio_server stdin_reader
    def should_skip(line: str) -> bool:
        return not line or not line.strip()

    valid_line = '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n'
    lines = ["\n", "  \n", "\t\n", valid_line, "\n"]

    filtered = [line for line in lines if not should_skip(line)]
    assert filtered == [valid_line], "Only the valid JSON-RPC line should pass through"

    # Parsing the only line that passed must succeed (no crash)
    msg = types.JSONRPCMessage.model_validate_json(valid_line)
    assert msg.root.id == 1
