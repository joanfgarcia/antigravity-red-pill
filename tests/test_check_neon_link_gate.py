"""Regression tests for the NEON_LINK_HTTP_API gate (neon_hung false positives).

neon-link releases up to 0.5.1 ship the FastAPI app but never serve it, so the
sentinel HTTP probe must stay off unless the operator explicitly enables it.
"""

from types import SimpleNamespace
from unittest.mock import patch

from red_pill.metabolism.sentinel_plugins.check_neon_link import NeonLinkCheck


def _cfg(http_api: bool) -> SimpleNamespace:
	return SimpleNamespace(NEON_LINK_HTTP_API=http_api, NEON_LINK_URL="http://localhost:8770")


def test_audit_health_skips_probe_when_http_api_disabled():
	plugin = NeonLinkCheck()
	with patch("urllib.request.urlopen") as urlopen:
		findings = plugin.audit_health(_cfg(http_api=False))
	urlopen.assert_not_called()
	assert findings == []


def test_audit_health_probes_and_reports_when_http_api_enabled():
	plugin = NeonLinkCheck()
	with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
		findings = plugin.audit_health(_cfg(http_api=True))
	assert len(findings) == 1
	assert findings[0].type == "neon_hung"


def test_audit_health_clean_when_http_api_enabled_and_reachable():
	plugin = NeonLinkCheck()
	with patch("urllib.request.urlopen", return_value=object()):
		findings = plugin.audit_health(_cfg(http_api=True))
	assert findings == []


def test_config_default_is_disabled():
	import red_pill.config as cfg

	assert getattr(cfg, "NEON_LINK_HTTP_API") is False
