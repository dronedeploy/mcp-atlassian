"""I/O utility functions for MCP Atlassian."""

import io
import os
from pathlib import Path

from mcp_atlassian.utils.env import is_env_extended_truthy


class _EmptyLineFilteringBuffer(io.BufferedIOBase):
    """Binary stream wrapper that skips empty/whitespace-only lines on readline().

    MCP stdio expects newline-delimited JSON; a bare newline from the client
    causes JSONRPCMessage.model_validate_json to raise. This wrapper
    ensures readline() only returns lines that contain non-whitespace.
    """

    def __init__(self, raw: io.BufferedIOBase) -> None:
        super().__init__()
        self._raw = raw

    def readline(self, size: int = -1) -> bytes:
        while True:
            line = self._raw.readline(size)
            if not line:
                return line
            if line.strip():
                return line

    def read(self, size: int = -1) -> bytes:
        return self._raw.read(size)

    def read1(self, size: int = -1) -> bytes:
        return getattr(self._raw, "read1", lambda s: self._raw.read(s))(size)

    def readable(self) -> bool:
        return self._raw.readable()

    def close(self) -> None:
        self._raw.close()

    @property
    def closed(self) -> bool:
        return self._raw.closed


def wrap_stdin_skip_empty_lines():  # noqa: D401
    """Replace sys.stdin with a wrapper that skips empty lines (for MCP stdio).

    Call before starting the MCP server when using stdio transport. Returns
    the original sys.stdin so the caller can restore it in a finally block.
    """
    import sys

    real = sys.stdin
    sys.stdin = io.TextIOWrapper(
        _EmptyLineFilteringBuffer(real.buffer),
        encoding=getattr(real, "encoding", "utf-8") or "utf-8",
        line_buffering=True,
    )
    return real


def is_read_only_mode() -> bool:
    """Check if the server is running in read-only mode.

    Read-only mode prevents all write operations (create, update, delete)
    while allowing all read operations. This is useful for working with
    production Atlassian instances where you want to prevent accidental
    modifications.

    Returns:
        True if read-only mode is enabled, False otherwise
    """
    return is_env_extended_truthy("READ_ONLY_MODE", "false")


def validate_safe_path(
    path: str | os.PathLike[str],
    base_dir: str | os.PathLike[str] | None = None,
) -> Path:
    """Validate that a path does not escape the base directory.

    Resolves symlinks and normalizes the path to prevent path traversal
    attacks (e.g., ``../../etc/passwd``).

    Args:
        path: The path to validate.
        base_dir: The directory the path must stay within.
            Defaults to the current working directory.

    Returns:
        The resolved, validated path.

    Raises:
        ValueError: If the resolved path escapes *base_dir*.
    """
    if base_dir is None:
        base_dir = os.getcwd()

    resolved_base = Path(base_dir).resolve(strict=False)
    p = Path(path)
    # Resolve relative paths against base_dir, not cwd
    if not p.is_absolute():
        p = resolved_base / p
    resolved_path = p.resolve(strict=False)

    if not resolved_path.is_relative_to(resolved_base):
        raise ValueError(
            f"Path traversal detected: {path} resolves outside {resolved_base}"
        )

    return resolved_path
