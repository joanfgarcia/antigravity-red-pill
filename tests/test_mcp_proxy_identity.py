"""mcp_proxy.identity_payload: ambigüedad D-BRIDGE y session id del arnés."""

from __future__ import annotations

import red_pill.mcp_proxy as proxy
from red_pill.core import bridge


def _clear_env(monkeypatch):
	for key in (
		"REDPILL_ORIGINATOR",
		"REDPILL_CONTINUITY_ID",
		"REDPILL_MISSION_ID",
		"REDPILL_WORKSPACE",
		"OPENCODE_SESSION_ID",
		"OPENCODE_SESSION",
	):
		monkeypatch.delenv(key, raising=False)


def test_identity_ambiguous_does_not_fall_back_to_global(monkeypatch):
	_clear_env(monkeypatch)
	monkeypatch.setattr(bridge, "resolve_body", lambda provider, cwd: (None, bridge.REASON_AMBIGUOUS))

	payload = proxy.identity_payload("opencode")
	assert payload["ambiguous"] is True
	assert payload["originator"] == ""


def test_identity_prefers_harness_session_id(monkeypatch):
	_clear_env(monkeypatch)
	monkeypatch.setenv("OPENCODE_SESSION_ID", "ses_env")
	monkeypatch.setattr(bridge, "read_session_bridge", lambda provider, sid: {"workdir": "/w", "project_dir": ""})

	payload = proxy.identity_payload("opencode")
	assert payload["ambiguous"] is False
	assert payload["originator"] == "opencode:ses_env"
	assert payload["workdir"] == "/w"
