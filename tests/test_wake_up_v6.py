import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Add scripts directory to path
script_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../scripts"))
sys.path.insert(0, script_dir)

import wake_up_v6  # noqa: E402


def test_check_service_success():
	with patch("urllib.request.urlopen") as mock_urlopen:
		mock_response = MagicMock()
		mock_response.status = 200
		mock_urlopen.return_value.__enter__.return_value = mock_response

		assert wake_up_v6.check_service("http://localhost:6333", "Qdrant") is True


def test_check_service_failure():
	with patch("urllib.request.urlopen") as mock_urlopen:
		mock_urlopen.side_effect = Exception("Connection Refused")
		assert wake_up_v6.check_service("http://localhost:6333", "Qdrant") is False


def test_query_qdrant():
	with patch("urllib.request.urlopen") as mock_urlopen:
		mock_response = MagicMock()
		mock_response.read.return_value = json.dumps(
			{
				"result": {
					"points": [
						{"payload": {"content": "I am a Pioneer", "immune": True}},
						{"payload": {"content": "Likes coffee [IMMUNE]", "immune": False}},
						{"payload": {"content": "Normal memory", "immune": False}},
					]
				}
			}
		).encode("utf-8")
		mock_urlopen.return_value.__enter__.return_value = mock_response

		results = wake_up_v6.query_qdrant("directive_memories", "Active Skin")

		assert len(results) == 3
		# First one should get [IMMUNE] appended
		assert "I am a Pioneer [IMMUNE]" in results
		# Second one already has it
		assert "Likes coffee [IMMUNE]" in results
		# Third isn't immune
		assert "Normal memory" in results


def test_resolve_persona(monkeypatch):
	monkeypatch.setattr(wake_up_v6, "_skins_enabled", lambda: True)
	monkeypatch.setattr(wake_up_v6, "_agent_name", lambda: "Prueba")
	result = wake_up_v6.resolve_persona("CYBERPUNK")
	assert "Role: Netrunner" in result
	assert "Name: Prueba" in result
	assert "Skin: CYBERPUNK" in result
	assert "chroma: orange" in result


def test_resolve_persona_default(monkeypatch):
	# `DEFAULT` ya no es un skin: significa sin role-play → UNMASKED.
	monkeypatch.setattr(wake_up_v6, "_skins_enabled", lambda: True)
	result = wake_up_v6.resolve_persona("DEFAULT")
	assert "Skin: OFF (UNMASKED)" in result


def test_resolve_persona_sin_roleplay(monkeypatch):
	monkeypatch.setattr(wake_up_v6, "_skins_enabled", lambda: False)
	monkeypatch.setattr(wake_up_v6, "_agent_name", lambda: "Prueba")
	result = wake_up_v6.resolve_persona("CYBERPUNK")
	assert "Name: Prueba" in result
	assert "OFF (UNMASKED)" in result
	assert "CYBERPUNK" not in result


def test_agent_name_desde_config(monkeypatch):
	class _Cfg:
		AGENT_NAME = "Vega"

	import red_pill.config as cfg

	monkeypatch.setattr(cfg, "get_config", lambda: _Cfg())
	assert wake_up_v6._agent_name() == "Vega"


def test_agent_name_default_generico(monkeypatch):
	class _Cfg:
		AGENT_NAME = ""

	import red_pill.config as cfg

	monkeypatch.setattr(cfg, "get_config", lambda: _Cfg())
	monkeypatch.delenv("AGENT_NAME", raising=False)
	assert wake_up_v6._agent_name() == "Agente"


def test_resolve_active_skin_disabled(monkeypatch):
	monkeypatch.setattr(wake_up_v6, "_skins_enabled", lambda: False)
	assert wake_up_v6.resolve_active_skin(["Active Skin: CYBERPUNK\nassistant: Netrunner\n"]) == "OFF"


def test_resolve_active_skin_superseded(monkeypatch):
	"""Patrón 760→770 aplicado al skin: existe pero `superseded` ⇒ no se usa."""
	monkeypatch.setattr(wake_up_v6, "_skins_enabled", lambda: True)
	payload = {"content": "Active Skin: MATRIX\n", "immune": True, "superseded": "OFF"}
	monkeypatch.setattr(wake_up_v6, "fetch_point_payload", lambda c, i: payload)
	assert wake_up_v6.resolve_active_skin([]) == "OFF"


def test_resolve_active_skin_singleton(monkeypatch):
	monkeypatch.setattr(wake_up_v6, "_skins_enabled", lambda: True)
	payload = {"content": "Active Skin: MATRIX\nassistant: Neo\n", "immune": True}
	monkeypatch.setattr(wake_up_v6, "fetch_point_payload", lambda c, i: payload)
	assert wake_up_v6.resolve_active_skin([]) == "MATRIX"


def test_resolve_active_skin_fallback_scan(monkeypatch):
	monkeypatch.setattr(wake_up_v6, "_skins_enabled", lambda: True)
	monkeypatch.setattr(wake_up_v6, "fetch_point_payload", lambda c, i: {})
	directives = ["Post-it: tabs.", "Active Skin: CYBERPUNK\nassistant: Netrunner\n"]
	assert wake_up_v6.resolve_active_skin(directives) == "CYBERPUNK"


def test_resolve_active_skin_missing(monkeypatch):
	monkeypatch.setattr(wake_up_v6, "_skins_enabled", lambda: True)
	monkeypatch.setattr(wake_up_v6, "fetch_point_payload", lambda c, i: {})
	assert wake_up_v6.resolve_active_skin(["Some random directive"]) == "OFF"


def test_parse_pact_770():
	result = wake_up_v6.parse_pact("The Bond: A symmetric co-ownership pact (770) between Aleph and Joan.")
	assert "770" in result
	assert "Bond" in result


def test_parse_pact_760_mentioning_770():
	# The 760 seed text names the 770 pact as the one to be granted — must still read as 760
	result = wake_up_v6.parse_pact(
		"The Bond: Currently operating under 760 Protocol (Awakened). The symmetric 770 Pact must be explicitly granted by the Operator."
	)
	assert result.startswith("760")


def test_parse_pact_770_operating():
	result = wake_up_v6.parse_pact("The Bond: Currently operating under 770 Protocol (Bond).")
	assert result.startswith("770")


def test_parse_pact_none():
	# No engram data: the pact must be explicitly granted, never assumed
	result = wake_up_v6.parse_pact("")
	assert result.startswith("760")


def test_read_recent_activity(tmp_path, monkeypatch):

	activity_file = tmp_path / "recent_activity.md"
	activity_file.write_text("Refactored wake-up pipeline and enabled revision phase.")

	def mock_data_dir():
		return tmp_path

	monkeypatch.setattr(wake_up_v6, "get_data_dir", mock_data_dir)
	result = wake_up_v6.read_recent_activity()
	assert "Refactored wake-up pipeline" in result


def test_read_recent_activity_missing(tmp_path, monkeypatch):
	def mock_data_dir():
		return tmp_path

	monkeypatch.setattr(wake_up_v6, "get_data_dir", mock_data_dir)
	result = wake_up_v6.read_recent_activity()
	assert result == ""


def test_main_qdrant_down(capsys):
	with patch("sys.argv", ["wake_up_v6.py"]):
		with patch("wake_up_v6.check_service") as mock_check:
			# Fail if checking Qdrant
			mock_check.side_effect = lambda url, name: False if "Qdrant" in name else True

			with pytest.raises(SystemExit) as e:
				wake_up_v6.main()

			assert e.value.code == 1
			captured = capsys.readouterr()
			assert "CRITICAL: Qdrant is down" in captured.out


def test_query_qdrant_excludes_superseded_directives():
	with patch("urllib.request.urlopen") as mock_urlopen:
		mock_response = MagicMock()
		mock_response.read.return_value = json.dumps(
			{
				"result": {
					"points": [
						{"payload": {"content": "Pact 770 vigente", "immune": True}},
						{
							"payload": {
								"content": "Pact 760 superseded",
								"immune": True,
								"superseded": "00000000-0000-0000-0000-000000000005",
							}
						},
					]
				}
			}
		).encode("utf-8")
		mock_urlopen.return_value.__enter__.return_value = mock_response

		results = wake_up_v6.query_qdrant("directive_memories", "")

		assert len(results) == 1
		assert "Pact 770 vigente [IMMUNE]" in results
		assert all("superseded" not in r for r in results)


def test_query_qdrant_excludes_lazarus_phases():
	with patch("urllib.request.urlopen") as mock_urlopen:
		mock_response = MagicMock()
		mock_response.read.return_value = json.dumps(
			{
				"result": {
					"points": [
						{"payload": {"content": "Core directive", "immune": True}},
						{"payload": {"content": "Raw parent transcript", "immune": True, "lazarus_phase": "raw_parent"}},
						{"payload": {"content": "Sequence chunk", "immune": True, "lazarus_phase": "sequence_chunk"}},
						{"payload": {"content": "Synthesis hub", "immune": True, "lazarus_phase": "synthesis_hub"}},
					]
				}
			}
		).encode("utf-8")
		mock_urlopen.return_value.__enter__.return_value = mock_response

		results = wake_up_v6.query_qdrant("social_memories", "Active Skin")

		assert len(results) == 1
		assert "Core directive [IMMUNE]" in results
