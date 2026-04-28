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


def test_synthesize_with_llm():
	with patch("urllib.request.urlopen") as mock_urlopen:
		mock_response = MagicMock()
		mock_response.read.return_value = json.dumps({"choices": [{"message": {"content": "I am Bob."}}]}).encode("utf-8")
		mock_urlopen.return_value.__enter__.return_value = mock_response

		result = wake_up_v6.synthesize_with_llm(["Memory A", "Memory B"])
		assert result == "I am Bob."


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
