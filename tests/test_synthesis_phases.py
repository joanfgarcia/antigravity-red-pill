"""Tests for the sleep synthesis phases (OperatorProfile, RecentActivity) and their shared plumbing."""

import json
from unittest.mock import MagicMock, patch

import red_pill.metabolism.phases.operator_profile_phase as opp
import red_pill.metabolism.phases.recent_activity_phase as rap
import red_pill.metabolism.phases.synthesis_common as common
from red_pill.metabolism.phases.base import SleepContext


def _mock_scroll_response(contents):
	mock_response = MagicMock()
	mock_response.read.return_value = json.dumps({"result": {"points": [{"payload": {"content": c}} for c in contents]}}).encode("utf-8")
	return mock_response


def test_recall_recent_orders_and_filters():
	with patch("urllib.request.urlopen") as mock_urlopen:
		mock_urlopen.return_value.__enter__.return_value = _mock_scroll_response(["hub A", "engram B"])

		results = common.recall_recent("work_memories", limit=5)

		assert results == ["hub A", "engram B"]
		sent = json.loads(mock_urlopen.call_args[0][0].data.decode())
		assert sent["order_by"] == {"key": "created_at", "direction": "desc"}
		must_not = sent["filter"]["must_not"]
		assert {"key": "_is_fragment", "match": {"value": True}} in must_not
		assert any(c["key"] == "lazarus_phase" for c in must_not)


def test_recall_recent_degrades_without_index():
	with patch("urllib.request.urlopen") as mock_urlopen:
		# First (ordered) call fails as if created_at had no payload index; retry succeeds
		ok = MagicMock()
		ok.__enter__.return_value = _mock_scroll_response(["engram"])
		mock_urlopen.side_effect = [Exception("Index required"), ok]

		assert common.recall_recent("work_memories", limit=5) == ["engram"]
		retry_payload = json.loads(mock_urlopen.call_args[0][0].data.decode())
		assert "order_by" not in retry_payload


def test_is_fresh(tmp_path):
	artifact = tmp_path / "artifact.md"
	assert common.is_fresh(artifact, 1) is False
	artifact.write_text("data")
	assert common.is_fresh(artifact, 1) is True


def test_recent_activity_keeps_previous_on_llm_failure(tmp_path, monkeypatch):
	artifact = tmp_path / "recent_activity.md"
	artifact.write_text("previous good summary")
	monkeypatch.setattr(rap, "ACTIVITY_PATH", artifact)
	monkeypatch.setattr(rap, "is_fresh", lambda path, hours: False)
	monkeypatch.setattr(rap, "recall_recent", lambda coll, limit, tag=None: ["hub content"])
	monkeypatch.setattr(rap, "chat", lambda *a, **k: "")

	rap.RecentActivityPhase().execute(SleepContext(memory_manager=None))

	assert artifact.read_text() == "previous good summary"


def test_recent_activity_publishes_valid_summary(tmp_path, monkeypatch):
	artifact = tmp_path / "recent_activity.md"
	monkeypatch.setattr(rap, "ACTIVITY_PATH", artifact)
	monkeypatch.setattr(rap, "is_fresh", lambda path, hours: False)
	monkeypatch.setattr(rap, "recall_recent", lambda coll, limit, tag=None: ["hub content"])
	monkeypatch.setattr(rap, "chat", lambda *a, **k: "Joan cerró la release v7.14.0 y refactorizó el wake-up.")

	rap.RecentActivityPhase().execute(SleepContext(memory_manager=None))

	assert "v7.14.0" in artifact.read_text()


def test_recent_activity_skips_when_fresh(tmp_path, monkeypatch):
	artifact = tmp_path / "recent_activity.md"
	artifact.write_text("fresh summary")
	monkeypatch.setattr(rap, "ACTIVITY_PATH", artifact)
	called = []
	monkeypatch.setattr(rap, "recall_recent", lambda *a, **k: called.append(1) or [])

	rap.RecentActivityPhase().execute(SleepContext(memory_manager=None))

	assert called == []  # freshness guard short-circuits before any recall
	assert artifact.read_text() == "fresh summary"


def test_operator_profile_keeps_existing_on_invalid(tmp_path, monkeypatch):
	artifact = tmp_path / "operator_profile.md"
	artifact.write_text("previous profile")
	monkeypatch.setattr(opp, "PROFILE_PATH", artifact)
	monkeypatch.setattr(opp, "is_fresh", lambda path, hours: False)
	monkeypatch.setattr(opp, "recall_recent", lambda coll, limit, tag=None: ["work hub"])
	monkeypatch.setattr(opp, "_fetch_social_immune", lambda limit=5: [])
	monkeypatch.setattr(opp, "_fetch_directive_immune", lambda limit=3: [])
	monkeypatch.setattr(opp, "chat", lambda *a, **k: "INSUFFICIENT_DATA")

	opp.OperatorProfilePhase().execute(SleepContext(memory_manager=None))

	assert artifact.read_text() == "previous profile"


def test_operator_profile_publishes_valid(tmp_path, monkeypatch):
	artifact = tmp_path / "operator_profile.md"
	monkeypatch.setattr(opp, "PROFILE_PATH", artifact)
	monkeypatch.setattr(opp, "is_fresh", lambda path, hours: False)
	monkeypatch.setattr(opp, "recall_recent", lambda coll, limit, tag=None: ["work hub"])
	monkeypatch.setattr(opp, "_fetch_social_immune", lambda limit=5: ["social"])
	monkeypatch.setattr(opp, "_fetch_directive_immune", lambda limit=3: ["directive"])
	monkeypatch.setattr(opp, "chat", lambda *a, **k: "Joan — Arquitecto IA en Hotetec; foco actual: release v7.14 de red-pill.")

	opp.OperatorProfilePhase().execute(SleepContext(memory_manager=None))

	assert "Arquitecto IA" in artifact.read_text()


def test_validate_activity_rejects_short_and_nominal():
	assert rap._validate_activity("") is False
	assert rap._validate_activity("too short") is False
	assert rap._validate_activity("System nominal. Persona engaged and running fine.") is False
	assert rap._validate_activity("Joan refactorizó el wake-up y cerró la release v7.14.0.") is True
