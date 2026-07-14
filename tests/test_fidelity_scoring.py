"""Unit tests for scripts/distiller_fidelity.py coverage scoring (no model)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from distiller_fidelity import PROBES, extract_summary, score_fidelity, side_covered  # noqa: E402


def test_side_covered():
	assert side_covered("hablamos de los actos que nos definen", ["acto", "define"])
	assert not side_covered("un texto sin relación", ["acto", "define"])


def test_extract_summary():
	assert extract_summary('{"summary": "hola", "emotion": "joy"}') == "hola"
	assert extract_summary("no json") == ""


def test_score_both_sides():
	probe = PROBES[0]  # philosophical
	both = "El usuario dice que los actos definen; el asistente discrepa: sin memoria no hay continuidad."
	only_user = "El usuario sostiene que lo que nos define son nuestros actos."
	assert score_fidelity(both, probe)["both_sides"] is True
	s = score_fidelity(only_user, probe)
	assert s["user_side"] is True and s["asst_side"] is False and s["both_sides"] is False
