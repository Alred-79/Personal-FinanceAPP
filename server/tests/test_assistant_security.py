"""Tests for SSRF protection on OpenWebsiteTool and TTL bounded agent cache.

Covers _validate_url, _fetch_and_strip, OpenWebsiteTool._run
integration, and TTLCache eviction behaviour.
"""

import json
import socket
import time
from unittest.mock import patch, MagicMock

import pytest

# Module under test imports
from server.src.services.assistant_service import (
    _validate_url,
    _fetch_and_strip,
    _GENERIC_FETCH_ERROR,
    _MAX_RESPONSE_BYTES,
    OpenWebsiteTool,
    AssistantService,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_addrinfo_public(host, port, *args, **kwargs):
    """Simulate DNS resolution to a public IP (93.184.216.34 = example.com)."""
    return [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
    ]


def _fake_addrinfo_private(host, port, *args, **kwargs):
    """Simulate DNS resolution to a private IP."""
    return [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 0)),
    ]


def _fake_addrinfo_loopback(host, port, *args, **kwargs):
    return [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0)),
    ]


def _fake_addrinfo_link_local(host, port, *args, **kwargs):
    return [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 0)),
    ]


def _fake_addrinfo_192(host, port, *args, **kwargs):
    return [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.1", 0)),
    ]


# ---------------------------------------------------------------------------
# _validate_url, scheme checks
# ---------------------------------------------------------------------------

class TestValidateUrlScheme:
    def test_ftp_rejected(self):
        with pytest.raises(ValueError, match=_GENERIC_FETCH_ERROR):
            _validate_url("ftp://example.com/file")

    def test_file_rejected(self):
        with pytest.raises(ValueError, match=_GENERIC_FETCH_ERROR):
            _validate_url("file:///etc/passwd")

    def test_no_scheme_rejected(self):
        with pytest.raises(ValueError, match=_GENERIC_FETCH_ERROR):
            _validate_url("example.com")

    def test_javascript_rejected(self):
        with pytest.raises(ValueError, match=_GENERIC_FETCH_ERROR):
            _validate_url("javascript:alert(1)")


# ---------------------------------------------------------------------------
# _validate_url, IP range checks (mocked DNS)
# ---------------------------------------------------------------------------

class TestValidateUrlIPBlocking:
    @patch("server.src.services.assistant_service.socket.getaddrinfo", _fake_addrinfo_link_local)
    def test_cloud_metadata_blocked(self):
        """169.254.169.254 (AWS/GCP metadata endpoint) must be blocked."""
        with pytest.raises(ValueError, match=_GENERIC_FETCH_ERROR):
            _validate_url("http://169.254.169.254/latest/meta-data/")

    @patch("server.src.services.assistant_service.socket.getaddrinfo", _fake_addrinfo_loopback)
    def test_localhost_blocked(self):
        with pytest.raises(ValueError, match=_GENERIC_FETCH_ERROR):
            _validate_url("http://localhost/")

    @patch("server.src.services.assistant_service.socket.getaddrinfo", _fake_addrinfo_loopback)
    def test_127_blocked(self):
        with pytest.raises(ValueError, match=_GENERIC_FETCH_ERROR):
            _validate_url("http://127.0.0.1/secret")

    @patch("server.src.services.assistant_service.socket.getaddrinfo", _fake_addrinfo_private)
    def test_10_network_blocked(self):
        with pytest.raises(ValueError, match=_GENERIC_FETCH_ERROR):
            _validate_url("http://10.0.0.1/internal")

    @patch("server.src.services.assistant_service.socket.getaddrinfo", _fake_addrinfo_192)
    def test_192_168_blocked(self):
        with pytest.raises(ValueError, match=_GENERIC_FETCH_ERROR):
            _validate_url("http://192.168.1.1/admin")

    @patch("server.src.services.assistant_service.socket.getaddrinfo", _fake_addrinfo_public)
    def test_public_ip_allowed(self):
        """A normal public IP should pass validation."""
        result = _validate_url("http://example.com/page")
        assert result == "http://example.com/page"

    def test_dns_failure_rejected(self):
        with patch(
            "server.src.services.assistant_service.socket.getaddrinfo",
            side_effect=socket.gaierror("Name resolution failed"),
        ):
            with pytest.raises(ValueError, match=_GENERIC_FETCH_ERROR):
                _validate_url("http://nonexistent.invalid/")


# ---------------------------------------------------------------------------
# _fetch_and_strip
# ---------------------------------------------------------------------------

class TestFetchAndStrip:
    @patch("server.src.services.assistant_service.socket.getaddrinfo", _fake_addrinfo_public)
    @patch("server.src.services.assistant_service.requests.get")
    def test_strips_html_tags(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.iter_content.return_value = [
            b"<html><body><p>Hello World</p></body></html>"
        ]
        mock_get.return_value = mock_resp

        text = _fetch_and_strip("http://example.com")
        assert "Hello World" in text
        assert "<p>" not in text

    @patch("server.src.services.assistant_service.socket.getaddrinfo", _fake_addrinfo_public)
    @patch("server.src.services.assistant_service.requests.get")
    def test_oversized_response_rejected(self, mock_get):
        """Responses exceeding 512 KB must raise ValueError."""
        big_chunk = b"x" * (_MAX_RESPONSE_BYTES + 1)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.iter_content.return_value = [big_chunk]
        mock_get.return_value = mock_resp

        with pytest.raises(ValueError, match=_GENERIC_FETCH_ERROR):
            _fetch_and_strip("http://example.com")

    @patch("server.src.services.assistant_service.requests.get")
    def test_no_auto_redirects(self, mock_get):
        """``requests.get`` must be called with redirects disabled."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.iter_content.return_value = [b"<p>ok</p>"]
        mock_get.return_value = mock_resp

        with patch(
            "server.src.services.assistant_service.socket.getaddrinfo",
            _fake_addrinfo_public,
        ):
            _fetch_and_strip("http://example.com")

        assert mock_get.call_args.kwargs.get("allow_redirects") is False


# ---------------------------------------------------------------------------
# SSRF bypass hardening, redirects & DNS rebinding
# ---------------------------------------------------------------------------

def _addrinfo_by_host(host, port, *args, **kwargs):
    """Resolve example.com → public, metadata host → link local."""
    mapping = {
        "example.com": "93.184.216.34",
        "169.254.169.254": "169.254.169.254",
    }
    ip = mapping.get(host, "93.184.216.34")
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port or 0))]


class TestRedirectAndRebinding:
    @patch("server.src.services.assistant_service.socket.getaddrinfo", _addrinfo_by_host)
    @patch("server.src.services.assistant_service.requests.get")
    def test_redirect_to_metadata_blocked(self, mock_get):
        """A public URL that 302-redirects to the metadata IP must be blocked."""
        redirect_resp = MagicMock()
        redirect_resp.status_code = 302
        redirect_resp.headers = {"Location": "http://169.254.169.254/latest/meta-data/"}
        mock_get.return_value = redirect_resp

        with pytest.raises(ValueError, match=_GENERIC_FETCH_ERROR):
            _fetch_and_strip("http://example.com/page")

        # Only the first hop should have been fetched; the redirect target is
        # rejected at validation time before any second request.
        assert mock_get.call_count == 1

    @patch("server.src.services.assistant_service.socket.getaddrinfo", _addrinfo_by_host)
    @patch("server.src.services.assistant_service.requests.get")
    def test_redirect_to_metadata_via_tool_returns_generic(self, mock_get):
        redirect_resp = MagicMock()
        redirect_resp.status_code = 302
        redirect_resp.headers = {"Location": "http://169.254.169.254/"}
        mock_get.return_value = redirect_resp

        tool = OpenWebsiteTool()
        result = tool._run(url="http://example.com/page")
        assert result == _GENERIC_FETCH_ERROR

    @patch("server.src.services.assistant_service.socket.getaddrinfo", _fake_addrinfo_private)
    def test_fetch_path_revalidates_resolution(self):
        """The fetch path itself must reject a private resolution.

        This closes the DNS-rebinding TOCTOU: even if validation elsewhere
        passed, ``_fetch_and_strip`` re-resolves + validates the IP it pins,
        so a host that resolves to a private address is never connected to.
        """
        with pytest.raises(ValueError, match=_GENERIC_FETCH_ERROR):
            _fetch_and_strip("http://rebind.example/")


# ---------------------------------------------------------------------------
# OpenWebsiteTool._run, integration
# ---------------------------------------------------------------------------

class TestOpenWebsiteToolRun:
    @patch("server.src.services.assistant_service.socket.getaddrinfo", _fake_addrinfo_public)
    @patch("server.src.services.assistant_service.requests.get")
    def test_public_url_returns_text(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.iter_content.return_value = [b"<h1>Page Title</h1><p>content</p>"]
        mock_get.return_value = mock_resp

        tool = OpenWebsiteTool()
        result = tool._run(url="http://example.com/page")
        assert "Page Title" in result
        assert "content" in result
        assert "<h1>" not in result

    @patch("server.src.services.assistant_service.socket.getaddrinfo", _fake_addrinfo_loopback)
    def test_private_url_returns_generic_error(self):
        tool = OpenWebsiteTool()
        result = tool._run(url="http://127.0.0.1/secret")
        assert result == _GENERIC_FETCH_ERROR

    @patch("server.src.services.assistant_service.socket.getaddrinfo", _fake_addrinfo_link_local)
    def test_metadata_url_returns_generic_error(self):
        tool = OpenWebsiteTool()
        result = tool._run(url="http://169.254.169.254/latest/meta-data/")
        assert result == _GENERIC_FETCH_ERROR

    @patch("server.src.services.assistant_service.socket.getaddrinfo", _fake_addrinfo_public)
    @patch("server.src.services.assistant_service.requests.get")
    def test_oversized_response_returns_generic_error(self, mock_get):
        big_chunk = b"x" * (_MAX_RESPONSE_BYTES + 1)
        mock_resp = MagicMock()
        mock_resp.iter_content.return_value = [big_chunk]
        mock_get.return_value = mock_resp

        tool = OpenWebsiteTool()
        result = tool._run(url="http://example.com/huge")
        assert result == _GENERIC_FETCH_ERROR


# ---------------------------------------------------------------------------
# TTLCache, agent eviction
# ---------------------------------------------------------------------------

class TestAgentCacheEviction:
    @patch("server.src.services.assistant_service.settings")
    def test_ttl_eviction(self, mock_settings):
        """Agent should be evicted after TTL expires."""
        mock_settings.groq_api_key = "fake"
        mock_settings.groq_chat_model = "llama-3.3-70b-versatile"
        mock_settings.assistant_temperature = 0
        mock_settings.assistant_memory_window = 4

        svc = AssistantService()

        # Replace the cache with one that uses a controllable timer.
        _current_time = [time.monotonic()]
        cache = __import__("cachetools").TTLCache(
            maxsize=128, ttl=1800, timer=lambda: _current_time[0],
        )
        svc.agents = cache

        svc.agents[42] = "sentinel_agent"  # type: ignore[index]
        assert 42 in svc.agents

        # Advance the fake clock past the TTL.
        _current_time[0] += 1801
        assert 42 not in svc.agents

    @patch("server.src.services.assistant_service.settings")
    def test_maxsize_eviction(self, mock_settings):
        """Cache should evict the least recently used entry at maxsize."""
        mock_settings.groq_api_key = "fake"
        mock_settings.groq_chat_model = "llama-3.3-70b-versatile"
        mock_settings.assistant_temperature = 0
        mock_settings.assistant_memory_window = 4

        svc = AssistantService()
        # Fill to maxsize
        for i in range(128):
            svc.agents[i] = f"agent_{i}"  # type: ignore[index]
        assert len(svc.agents) == 128

        # Adding one more should evict the oldest
        svc.agents[999] = "new_agent"  # type: ignore[index]
        assert 999 in svc.agents
        assert len(svc.agents) == 128  # still at max
        # The first inserted (key 0) should have been evicted
        assert 0 not in svc.agents
