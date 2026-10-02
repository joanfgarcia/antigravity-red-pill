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


QDRANT_TEST_URL = "http://qdrant.test:6333"


def test_recall_recent_orders_and_filters(monkeypatch):
	monkeypatch.setattr(common, "_qdrant_url", lambda: QDRANT_TEST_URL)
	with patch("urllib.request.urlopen") as mock_urlopen:
		mock_urlopen.return_value.__enter__.return_value = _mock_scroll_response(["hub A", "engram B"])

		results = common.recall_recent("work_memories", limit=5)

		assert results == ["hub A", "engram B"]
		sent = json.loads(mock_urlopen.call_args[0][0].data.decode())
		assert sent["order_by"] == {"key": "created_at", "direction": "desc"}
		must_not = sent["filter"]["must_not"]
		assert {"key": "_is_fragment", "match": {"value": True}} in must_not
		assert any(c["key"] == "lazarus_phase" for c in must_not)


def test_recall_recent_degrades_without_index(monkeypatch):
	monkeypatch.setattr(common, "_qdrant_url", lambda: QDRANT_TEST_URL)
	with patch("urllib.request.urlopen") as mock_urlopen:
		# First (ordered) call fails as if created_at had no payload index; retry succeeds
		ok = MagicMock()
		ok.__enter__.return_value = _mock_scroll_response(["engram"])
		mock_urlopen.side_effect = [Exception("Index required"), ok]

		assert common.recall_recent("work_memories", limit=5) == ["engram"]
		retry_payload = json.loads(mock_urlopen.call_args[0][0].data.decode())
		assert "order_by" not in retry_payload


def test_endpoints_y_clave_salen_de_config_no_del_home():
	"""Nada de localhost:6333/8760 a fuego ni load_dotenv del ~/.config real: URL,
	clave y LLM salen de config (que respeta la redirección XDG)."""
	import red_pill.config as cfg

	# patch.object (no monkeypatch): al salir borra el atributo y vuelve a delegar
	# en el __getattr__ del módulo en vez de congelar el valor calculado.
	with (
		patch.object(cfg, "QDRANT_URL", QDRANT_TEST_URL, create=True),
		patch.object(cfg, "QDRANT_API_KEY", "k-test", create=True),
		patch.object(cfg, "MLX_LM_URL", "http://llm.test:9999/v1/chat/completions", create=True),
		patch("urllib.request.urlopen") as mock_urlopen,
	):
		mock_urlopen.return_value.__enter__.return_value = _mock_scroll_response(["x"])
		assert common.scroll_contents("work_memories", 3) == ["x"]
		req = mock_urlopen.call_args[0][0]
		assert req.full_url == f"{QDRANT_TEST_URL}/collections/work_memories/points/scroll"
		assert req.get_header("Api-key") == "k-test"

		mock_urlopen.reset_mock()
		mock_urlopen.return_value.__enter__.return_value.read.return_value = json.dumps({"choices": [{"message": {"content": " ok "}}]}).encode()
		assert common.chat("sys", "user", 10) == "ok"
		assert mock_urlopen.call_args[0][0].full_url == "http://llm.test:9999/v1/chat/completions"


def test_qdrant_sin_endpoint_http_no_hace_peticiones():
	"""En la suite QDRANT_URL es ':memory:': la síntesis se queda sin contexto, sin HTTP."""
	with patch("urllib.request.urlopen") as mock_urlopen:
		assert common.recall_recent("work_memories", limit=5) == []
		mock_urlopen.assert_not_called()


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
	monkeypatch.setattr(opp, "chat", lambda *a, **k: "Joan — Ingeniero de software; foco actual: release v7.14 de red-pill.")

	opp.OperatorProfilePhase().execute(SleepContext(memory_manager=None))

	assert "Ingeniero de software" in artifact.read_text()


def test_validate_activity_rejects_short_and_nominal():
	assert rap._validate_activity("") is False
	assert rap._validate_activity("too short") is False
	assert rap._validate_activity("System nominal. Persona engaged and running fine.") is False
	assert rap._validate_activity("Joan refactorizó el wake-up y cerró la release v7.14.0.") is True
