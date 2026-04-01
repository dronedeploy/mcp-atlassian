"""Module for Confluence comment operations."""

import logging
from typing import Any

import requests
from requests import HTTPError

from ..models.confluence import ConfluenceComment
from .client import ConfluenceClient
from .v2_adapter import ConfluenceV2Adapter

logger = logging.getLogger("mcp-atlassian")


class CommentsMixin(ConfluenceClient):
    """Mixin for Confluence comment operations."""

    @property
    def _v2_adapter(self) -> ConfluenceV2Adapter | None:
        """v2 adapter for footer comments when using OAuth Cloud."""
        if self.config.auth_type == "oauth" and self.config.is_cloud:
            return ConfluenceV2Adapter(
                session=self.confluence._session, base_url=self.confluence.url
            )
        return None

    def get_page_comments(
        self, page_id: str, *, return_markdown: bool = True
    ) -> list[ConfluenceComment]:
        """
        Get all comments for a specific page.

        Args:
            page_id: The ID of the page to get comments from
            return_markdown: When True, returns content in markdown format,
                           otherwise returns raw HTML (keyword-only)

        Returns:
            List of ConfluenceComment models containing comment content and metadata
        """
        try:
            # Get page info to extract space details
            page = self.confluence.get_page_by_id(page_id=page_id, expand="space")
            space_key = page.get("space", {}).get("key", "")

            # Get comments with expanded content
            comments_response = self.confluence.get_page_comments(
                content_id=page_id, expand="body.view.value,version", depth="all"
            )

            # Process each comment
            comment_models = []
            for comment_data in comments_response.get("results", []):
                # Get the content based on format
                body = comment_data["body"]["view"]["value"]
                processed_html, processed_markdown = (
                    self.preprocessor.process_html_content(
                        body, space_key=space_key, confluence_client=self.confluence
                    )
                )

                # Create a copy of the comment data to modify
                modified_comment_data = comment_data.copy()

                # Modify the body value based on the return format
                if "body" not in modified_comment_data:
                    modified_comment_data["body"] = {}
                if "view" not in modified_comment_data["body"]:
                    modified_comment_data["body"]["view"] = {}

                # Set the appropriate content based on return format
                modified_comment_data["body"]["view"]["value"] = (
                    processed_markdown if return_markdown else processed_html
                )

                # Create the model with the processed content
                comment_model = ConfluenceComment.from_api_response(
                    modified_comment_data,
                    base_url=self.config.url,
                )

                comment_models.append(comment_model)

            return comment_models

        except KeyError as e:
            logger.error(f"Missing key in comment data: {str(e)}")
            return []
        except requests.RequestException as e:
            logger.error(f"Network error when fetching comments: {str(e)}")
            return []
        except (ValueError, TypeError) as e:
            logger.error(f"Error processing comment data: {str(e)}")
            return []
        except Exception as e:  # noqa: BLE001 - Intentional fallback with full logging
            logger.error(f"Unexpected error fetching comments: {str(e)}")
            logger.debug("Full exception details for comments:", exc_info=True)
            return []

    def add_comment(self, page_id: str, content: str) -> ConfluenceComment | None:
        """
        Add a comment to a Confluence page.

        Args:
            page_id: The ID of the page to add the comment to
            content: The content of the comment (in Confluence storage format)

        Returns:
            ConfluenceComment object if comment was added successfully, None otherwise
        """
        try:
            # Convert markdown to Confluence storage format if needed
            if not content.strip().startswith("<"):
                content = self.preprocessor.markdown_to_confluence_storage(content)

            # Route through v2 API for OAuth Cloud
            v2_adapter = self._v2_adapter
            if v2_adapter:
                response = v2_adapter.create_footer_comment(
                    page_id=page_id, body=content
                )
                space_key = ""
            else:
                # Get page info to extract space details (v1 path)
                page = self.confluence.get_page_by_id(page_id=page_id, expand="space")
                space_key = page.get("space", {}).get("key", "")
                response = self.confluence.add_comment(page_id, content)

            if not response:
                logger.error("Failed to add comment: empty response")
                return None

            return self._process_comment_response(response, space_key)

        except requests.RequestException as e:
            logger.error(f"Network error when adding comment: {str(e)}")
            return None
        except (ValueError, TypeError, KeyError) as e:
            logger.error(f"Error processing comment data: {str(e)}")
            return None
        except Exception as e:  # noqa: BLE001 - Intentional fallback with full logging
            logger.error(f"Unexpected error adding comment: {str(e)}")
            logger.debug("Full exception details for adding comment:", exc_info=True)
            return None

    def reply_to_comment(
        self, comment_id: str, content: str
    ) -> ConfluenceComment | None:
        """
        Reply to an existing comment thread.

        Args:
            comment_id: The ID of the parent comment to reply to
            content: The reply content (markdown or HTML/storage format)

        Returns:
            ConfluenceComment object if reply was added successfully, None otherwise
        """
        try:
            # Convert markdown to Confluence storage format if needed
            if not content.strip().startswith("<"):
                content = self.preprocessor.markdown_to_confluence_storage(content)

            v2_adapter = self._v2_adapter
            if v2_adapter:
                response = v2_adapter.create_footer_comment(
                    parent_comment_id=comment_id, body=content
                )
                space_key = ""
            else:
                # v1 API: POST /rest/api/content/ with container type "comment"
                data: dict[str, Any] = {
                    "type": "comment",
                    "container": {
                        "id": comment_id,
                        "type": "comment",
                    },
                    "body": {
                        "storage": {
                            "value": content,
                            "representation": "storage",
                        },
                    },
                }
                response = self.confluence.post("rest/api/content/", data=data)
                space_key = ""

            if not response:
                logger.error("Failed to reply to comment: empty response")
                return None

            return self._process_comment_response(response, space_key)

        except requests.RequestException as e:
            logger.error(f"Network error when replying to comment: {str(e)}")
            return None
        except (ValueError, TypeError, KeyError) as e:
            logger.error(f"Error processing reply data: {str(e)}")
            return None
        except Exception as e:  # noqa: BLE001 - Intentional fallback with full logging
            logger.error(f"Unexpected error replying to comment: {str(e)}")
            logger.debug("Full exception details for comment reply:", exc_info=True)
            return None

    def add_inline_comment(
        self,
        content: str,
        *,
        page_id: str | None = None,
        parent_comment_id: str | None = None,
        text_selection: str | None = None,
        text_selection_match_index: int = 0,
        text_selection_match_count: int = 1,
    ) -> ConfluenceComment | None:
        """
        Add an inline comment on a page, or reply on an inline comment thread.

        Requires **Confluence Cloud** (v2 REST) with OAuth, PAT, or basic auth.
        There is no Server/DC or v1 fallback for inline comments.

        For a **new** highlight: pass ``page_id``, ``text_selection`` (exact text
        on the page), and ``content``. Use ``text_selection_match_index`` and
        ``text_selection_match_count`` when the phrase appears more than once.

        For a **reply** on an inline thread: pass ``parent_comment_id`` and
        ``content`` only.

        Args:
            content: Comment body (markdown or storage HTML)
            page_id: Page ID (new inline comment)
            parent_comment_id: Parent comment ID (reply on inline thread)
            text_selection: Exact substring to highlight (required with page_id)
            text_selection_match_index: Zero-based occurrence to highlight
            text_selection_match_count: Total occurrences of text_selection

        Returns:
            ConfluenceComment if successful, None otherwise
        """
        inline_adapter = self._v2_inline_comment_adapter
        if not inline_adapter:
            msg = (
                "Inline comments require Confluence Cloud with the v2 inline-comments "
                "API (API token, OAuth, or PAT). Data Center is unsupported. "
                "If you run mcp-atlassian from Docker, rebuild the image so it "
                "includes _v2_inline_comment_adapter for basic auth."
            )
            logger.error(msg)
            raise ValueError(msg)

        try:
            if not content.strip().startswith("<"):
                content = self.preprocessor.markdown_to_confluence_storage(content)

            if parent_comment_id:
                response = inline_adapter.create_inline_comment(
                    parent_comment_id=parent_comment_id,
                    body=content,
                )
                space_key = ""
            else:
                if not page_id:
                    logger.error("add_inline_comment: page_id required without parent")
                    raise ValueError(
                        "page_id is required for a new inline comment "
                        "(or pass parent_comment_id for a reply)."
                    )
                response = inline_adapter.create_inline_comment(
                    page_id=page_id,
                    body=content,
                    text_selection=text_selection or "",
                    text_selection_match_index=text_selection_match_index,
                    text_selection_match_count=text_selection_match_count,
                )
                space_key = ""

            if not response:
                logger.error("Failed to add inline comment: empty response")
                raise ValueError(
                    "Confluence returned an empty response for inline comment creation."
                )

            try:
                return self._process_comment_response(response, space_key)
            except (TypeError, KeyError) as e:
                logger.error(f"Error parsing inline comment response: {str(e)}")
                parse_err = f"Could not parse Confluence inline comment response: {e}"
                raise ValueError(parse_err) from e

        except HTTPError as e:
            snippet = ""
            status = getattr(getattr(e, "response", None), "status_code", None)
            if e.response is not None and e.response.text:
                snippet = e.response.text.strip()[:2000]
            logger.error(
                "HTTP error when adding inline comment: %s — %s",
                status,
                snippet[:500] if snippet else "(no body)",
            )
            http_msg = (
                "Confluence inline comment API request failed "
                f"(HTTP {status}). "
                "Common causes: text_selection does not match page text exactly "
                "(copy from the editor or storage export), wrong match_index/count, "
                "or insufficient Confluence permissions. "
                f"Response: {snippet}"
            )
            raise ValueError(http_msg) from e
        except requests.RequestException as e:
            logger.error(f"Network error when adding inline comment: {str(e)}")
            net_msg = f"Network error when calling Confluence inline comment API: {e}"
            raise ValueError(net_msg) from e
        except ValueError:
            raise
        except Exception as e:  # noqa: BLE001 - Intentional fallback with full logging
            logger.error(f"Unexpected error adding inline comment: {str(e)}")
            logger.debug(
                "Full exception details for inline comment:", exc_info=True
            )
            unexpected_msg = f"Unexpected error adding inline comment: {e}"
            raise ValueError(unexpected_msg) from e

    def _process_comment_response(
        self, response: dict[str, Any], space_key: str
    ) -> ConfluenceComment:
        """Process a comment API response into a ConfluenceComment model.

        Args:
            response: Raw API response dict
            space_key: The space key for content processing

        Returns:
            Processed ConfluenceComment instance
        """
        _, processed_markdown = self.preprocessor.process_html_content(
            response.get("body", {}).get("view", {}).get("value", ""),
            space_key=space_key,
            confluence_client=self.confluence,
        )

        modified_response = response.copy()
        if "body" not in modified_response:
            modified_response["body"] = {}
        if "view" not in modified_response["body"]:
            modified_response["body"]["view"] = {}

        modified_response["body"]["view"]["value"] = processed_markdown

        return ConfluenceComment.from_api_response(
            modified_response,
            base_url=self.config.url,
        )
