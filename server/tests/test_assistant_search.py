"""Tests for WebSearchTool Tavily integration.

Covers: happy path formatting, URL→open_website chain, query/param forwarding,
API key wiring, empty results, error handling, and malformed responses.
"""

from unittest.mock import patch, MagicMock

import pytest

from server.src.services.assistant_service import (
    WebSearchTool,
    _GENERIC_SEARCH_ERROR,
)

_SAMPLE_RESULTS = [
    {
        "title": "What is Budgeting",
        "url": "https://example.com/budgeting",
        "content": "Budgeting is the process of creating a plan to spend your money.",
        "score": 0.95,
        "raw_content": None,
    },
    {
        "title": "Personal Finance Tips",
        "url": "https://example.com/finance-tips",
        "content": "Top tips for managing personal finances effectively.",
        "score": 0.87,
        "raw_content": None,
    },
]

_SAMPLE_RESPONSE = {"query": "budgeting tips", "results": _SAMPLE_RESULTS}


def _make_mock_client(search_return=None, search_side_effect=None):
    """Return a patched TavilyClient constructor mock."""
    mock_instance = MagicMock()
    if search_side_effect is not None:
        mock_instance.search.side_effect = search_side_effect
    else:
        mock_instance.search.return_value = search_return or _SAMPLE_RESPONSE
    mock_cls = MagicMock(return_value=mock_instance)
    return mock_cls, mock_instance


class TestWebSearchToolHappyPath:
    def test_titles_present(self):
        mock_cls, _ = _make_mock_client()
        with patch("server.src.services.assistant_service.TavilyClient", mock_cls):
            result = WebSearchTool()._run("budgeting tips")
        assert "What is Budgeting" in result
        assert "Personal Finance Tips" in result

    def test_snippets_present(self):
        mock_cls, _ = _make_mock_client()
        with patch("server.src.services.assistant_service.TavilyClient", mock_cls):
            result = WebSearchTool()._run("budgeting tips")
        assert "creating a plan to spend your money" in result
        assert "Top tips for managing personal finances" in result

    def test_no_raw_json_noise(self):
        """score, raw_content, and dict braces must not appear in the output."""
        mock_cls, _ = _make_mock_client()
        with patch("server.src.services.assistant_service.TavilyClient", mock_cls):
            result = WebSearchTool()._run("budgeting tips")
        assert "score" not in result
        assert "raw_content" not in result
        assert "{" not in result


class TestWebSearchToolURLChain:
    def test_url_present_verbatim(self):
        """Each result URL must appear verbatim so open_website can use it."""
        mock_cls, _ = _make_mock_client()
        with patch("server.src.services.assistant_service.TavilyClient", mock_cls):
            result = WebSearchTool()._run("budgeting tips")
        assert "https://example.com/budgeting" in result
        assert "https://example.com/finance-tips" in result

    def test_url_under_label(self):
        """URL must appear under 'URL:' label for reliable LLM extraction."""
        mock_cls, _ = _make_mock_client()
        with patch("server.src.services.assistant_service.TavilyClient", mock_cls):
            result = WebSearchTool()._run("budgeting tips")
        assert "URL: https://example.com/budgeting" in result
        assert "URL: https://example.com/finance-tips" in result


class TestWebSearchToolForwarding:
    def test_query_forwarded(self):
        mock_cls, mock_instance = _make_mock_client()
        with patch("server.src.services.assistant_service.TavilyClient", mock_cls):
            WebSearchTool()._run("what is compound interest")
        mock_instance.search.assert_called_once_with(
            query="what is compound interest", max_results=5
        )

    def test_api_key_wiring(self):
        from server.src.services.assistant_service import settings
        mock_cls, _ = _make_mock_client()
        with patch("server.src.services.assistant_service.TavilyClient", mock_cls):
            WebSearchTool()._run("test query")
        mock_cls.assert_called_once_with(api_key=settings.tavily_api_key)


class TestWebSearchToolEdgeCases:
    def test_empty_results_message(self):
        mock_cls, _ = _make_mock_client(search_return={"results": []})
        with patch("server.src.services.assistant_service.TavilyClient", mock_cls):
            result = WebSearchTool()._run("xyzzy obscure query")
        assert "No results found" in result

    def test_missing_results_key(self):
        """Response missing 'results' key is treated as empty, not a KeyError."""
        mock_cls, _ = _make_mock_client(search_return={"query": "test"})
        with patch("server.src.services.assistant_service.TavilyClient", mock_cls):
            result = WebSearchTool()._run("test")
        assert "No results found" in result

    def test_result_missing_url_no_crash(self):
        """A result dict missing 'url' must not crash; empty string is fine."""
        response = {"results": [{"title": "No URL Result", "content": "some text"}]}
        mock_cls, _ = _make_mock_client(search_return=response)
        with patch("server.src.services.assistant_service.TavilyClient", mock_cls):
            result = WebSearchTool()._run("test")
        assert "No URL Result" in result

    def test_result_missing_content_no_crash(self):
        response = {"results": [{"title": "Title Only", "url": "https://example.com"}]}
        mock_cls, _ = _make_mock_client(search_return=response)
        with patch("server.src.services.assistant_service.TavilyClient", mock_cls):
            result = WebSearchTool()._run("test")
        assert "Title Only" in result


class TestWebSearchToolErrorHandling:
    def test_generic_exception_returns_error_string(self):
        mock_cls, _ = _make_mock_client(search_side_effect=Exception("network failure"))
        with patch("server.src.services.assistant_service.TavilyClient", mock_cls):
            result = WebSearchTool()._run("test")
        assert result == _GENERIC_SEARCH_ERROR

    def test_exception_does_not_propagate(self):
        """A Tavily failure must never raise out of _run (would crash the agent stream)."""
        mock_cls, _ = _make_mock_client(search_side_effect=RuntimeError("api error"))
        with patch("server.src.services.assistant_service.TavilyClient", mock_cls):
            try:
                WebSearchTool()._run("test")
            except Exception:
                pytest.fail("_run must not propagate exceptions")

    def test_auth_error_returns_error_string(self):
        """Simulated auth/quota failure degrades gracefully."""
        mock_cls, _ = _make_mock_client(
            search_side_effect=Exception("Invalid API key provided")
        )
        with patch("server.src.services.assistant_service.TavilyClient", mock_cls):
            result = WebSearchTool()._run("test")
        assert result == _GENERIC_SEARCH_ERROR
