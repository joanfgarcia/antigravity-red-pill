"""
Hito 3: the distiller must never store its own prompt/format spec as memory.

Production hubs were found containing the literal distillation instructions
("Synthesize these memory chunks...", "The emotion is one of..."). The only
validation was "is it parseable JSON". _is_template_echo() closes that hole,
and distill_engram falls back (dropping the echo) instead of persisting it.
"""

import json
from unittest.mock import MagicMock

from red_pill.core.providers import ProviderRegistry
from red_pill.metabolism.sleep import _is_template_echo, distill_engram


def test_is_template_echo_positive():
	assert _is_template_echo("Synthesize these memory chunks into a cohesive master summary.")
	assert _is_template_echo("[Memory Synthesis: MatMul-Free LM, T1-T3]")
	assert _is_template_echo("The emotion is one of the listed emotions. The intensity is a float between 0.0 and 1.0.")
	assert _is_template_echo("")
	assert _is_template_echo("   ")


def test_is_template_echo_keeps_short_legit_summaries():
	# No length heuristic: short but real summaries must survive (no false-positive data loss).
	assert not _is_template_echo("Bug de tree_hash arreglado.")
	assert not _is_template_echo("test")


def test_is_template_echo_negative():
	legit = (
		"Arreglamos el bug de tree_hash en pure-mls: faltaba incluir el leaf_index "
		"en el cálculo del hash del árbol según la RFC 9420 §7.8, y con eso los 248 tests pasan."
	)
	assert not _is_template_echo(legit)


def _register(summary_json: str):
	provider = MagicMock()
	provider.generate.return_value = summary_json
	ProviderRegistry.register_inference_provider("sip", provider, default=True)


def test_distill_engram_rejects_template_echo():
	_register(
		json.dumps(
			{
				"summary": "Synthesize these memory chunks into a cohesive master summary.",
				"emotion": "neutral",
				"intensity": 0.5,
				"category": "work",
			}
		)
	)
	result = distill_engram("USER: hola\nASSISTANT: qué tal todo", fallback_category="social")
	assert result.get("_is_fallback") is True  # echo rejected → distiller fell back, not persisted as real


def test_distill_engram_accepts_valid_summary():
	_register(
		json.dumps(
			{
				"summary": "Arreglado el bug de tree_hash en pure-mls incluyendo el leaf_index; 248 tests en verde.",
				"emotion": "joy",
				"intensity": 0.6,
				"category": "work",
			}
		)
	)
	result = distill_engram("USER: x cosa\nASSISTANT: y respuesta")
	assert not result.get("_is_fallback")
	assert "tree_hash" in result["summary"]
