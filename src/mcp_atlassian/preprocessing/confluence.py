"""Confluence-specific text preprocessing module."""

import logging
import re
import shutil
import tempfile
from pathlib import Path

from md2conf.converter import (
    ConfluenceConverterOptions,
    ConfluenceStorageFormatConverter,
    elements_to_string,
    markdown_to_html,
)
from md2conf.metadata import ConfluenceSiteMetadata

# Handle md2conf API changes: elements_from_string may be renamed to elements_from_strings
try:
    from md2conf.converter import elements_from_string
except ImportError:
    from md2conf.converter import elements_from_strings as elements_from_string

from .base import BasePreprocessor

logger = logging.getLogger("mcp-atlassian")

# HTML tags that markdown and Confluence converters are allowed to produce.
# Tags with a colon (e.g. ac:parameter, ri:user) are treated as allowed (Confluence macros).
_ALLOWED_HTML_TAGS = frozenset({
    "a", "abbr", "b", "blockquote", "br", "code", "col", "colgroup", "del", "div",
    "em", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "i", "img", "ins", "kbd", "li",
    "ol", "p", "pre", "s", "small", "span", "strong", "sub", "sup", "table", "tbody",
    "td", "tfoot", "th", "thead", "tr", "u",
})
_OPEN_TAG_RE = re.compile(r"<([a-zA-Z][a-zA-Z0-9:.-]*)(?:\s[^>]*)?>")
_CLOSE_TAG_RE = re.compile(r"</([a-zA-Z][a-zA-Z0-9:.-]*)>")


def _sanitize_html_for_confluence_parser(html_content: str) -> str:
    """Escape non-whitelisted HTML tags so strict XML parser does not see invalid/mismatched tags.

    Content that contains custom or unknown tags (e.g. <vendorname>) or mismatched
    open/close tags can cause md2conf's elements_from_string to raise ParseError.
    This function escapes any tag not in the allowed set so they become literal text.

    Args:
        html_content: HTML string (e.g. from markdown_to_html).

    Returns:
        HTML with non-allowed tags escaped (e.g. <vendorname> -> &lt;vendorname&gt;).
    """
    def escape_tag(match: re.Match[str], is_close: bool) -> str:
        tagname = match.group(1).lower()
        if ":" in tagname or tagname in _ALLOWED_HTML_TAGS:
            return match.group(0)
        # Escape the whole tag so the parser sees text, not a tag
        raw = match.group(0)
        return raw.replace("<", "&lt;").replace(">", "&gt;")

    out = _OPEN_TAG_RE.sub(lambda m: escape_tag(m, False), html_content)
    out = _CLOSE_TAG_RE.sub(lambda m: escape_tag(m, True), out)
    return out


class ConfluencePreprocessor(BasePreprocessor):
    """Handles text preprocessing for Confluence content."""

    def __init__(self, base_url: str) -> None:
        """
        Initialize the Confluence text preprocessor.

        Args:
            base_url: Base URL for Confluence API
        """
        super().__init__(base_url=base_url)

    def markdown_to_confluence_storage(
        self, markdown_content: str, *, enable_heading_anchors: bool = False
    ) -> str:
        """
        Convert Markdown content to Confluence storage format (XHTML)

        Args:
            markdown_content: Markdown text to convert
            enable_heading_anchors: Whether to enable automatic heading anchor generation (default: False)

        Returns:
            Confluence storage format (XHTML) string
        """
        try:
            # First convert markdown to HTML
            html_content = markdown_to_html(markdown_content)
            # Escape custom/unknown tags so md2conf's strict XML parser does not fail
            # (e.g. <vendorname> or mismatched open/close tags)
            html_content = _sanitize_html_for_confluence_parser(html_content)

            # Create a temporary directory for any potential attachments
            temp_dir = tempfile.mkdtemp()

            try:
                # Parse the HTML into an element tree
                root = elements_from_string(html_content)

                # Create converter options
                options = ConfluenceConverterOptions(
                    ignore_invalid_url=True,
                    heading_anchors=enable_heading_anchors,
                    render_mermaid=False,
                )

                # Create a converter
                converter = ConfluenceStorageFormatConverter(
                    options=options,
                    path=Path(temp_dir) / "temp.md",
                    root_dir=Path(temp_dir),
                    site_metadata=ConfluenceSiteMetadata(
                        domain="", base_path="", space_key=None
                    ),
                    page_metadata={},
                )

                # Transform the HTML to Confluence storage format
                converter.visit(root)

                # Convert the element tree back to a string
                storage_format = elements_to_string(root)

                return str(storage_format)
            finally:
                # Clean up the temporary directory
                shutil.rmtree(temp_dir, ignore_errors=True)

        except Exception as e:
            logger.error(f"Error converting markdown to Confluence storage format: {e}")
            logger.exception(e)

            # Fall back to a simpler method if the conversion fails
            html_content = markdown_to_html(markdown_content)
            html_content = _sanitize_html_for_confluence_parser(html_content)

            # Use a different approach that doesn't rely on the HTML macro
            # This creates a proper Confluence storage format document
            storage_format = f"""<p>{html_content}</p>"""

            return str(storage_format)

    # Confluence-specific methods can be added here
