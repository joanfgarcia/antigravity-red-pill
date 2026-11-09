"""T2+P2: HUB-v2 synthesis, affect derivation from history, relic transport."""

import json
from unittest.mock import MagicMock

from red_pill.metabolism.distiller import (
	build_emotional_vector,
	derive_hub_affect,
	merge_relics,
	synthesize_hub_v2,
)

CHUNKS = [
	{"summary": "s1", "texture": "cálido", "emotion": "joy", "intensity": 0.85, "category": "social", "lang": "es", "relics": ["cita uno"]},
	{
		"summary": "s2",
		"texture": "técnico",
		"emotion": "neutral",
		"intensity": 0.3,
		"category": "work",
		"lang": "es",
		"relics": ["cita dos", "cita uno"],
	},
	{"summary": "s3", "texture": "", "emotion": "neutral", "intensity": 0.3, "category": "social", "lang": "es", "relics": []},
]


def _mock_provider(monkeypatch, payload):
	from red_pill.core import providers

	provider = MagicMock()
	provider.generate.return_value = json.dumps(payload) if isinstance(payload, dict) else payload
	monkeypatch.setattr(providers.ProviderRegistry, "get_inference_provider", classmethod(lambda cls, name=None: provider))
	return provider


def test_derive_hub_affect_dominant_not_last():
	# Legacy took the LAST chunk's emotion (neutral); history-weighted must keep joy
	# only if its cumulative intensity wins — here neutral wins 0.6 vs 0.85 joy... joy wins.
	emotion, intensity = derive_hub_affect(CHUNKS)
	assert emotion == "joy"  # 0.85 joy > 0.6 accumulated neutral
	assert intensity == 0.85


def test_derive_hub_affect_accumulation_beats_single_peak():
	chunks = [
		{"emotion": "neutral", "intensity": 0.5},
		{"emotion": "neutral", "intensity": 0.5},
		{"emotion": "joy", "intensity": 0.7},
	]
	emotion, _ = derive_hub_affect(chunks)
	assert emotion == "neutral"  # 1.0 accumulated > 0.7


def test_merge_relics_dedupe_and_cap():
	assert merge_relics(CHUNKS) == ["cita uno", "cita dos"]
	many = [{"relics": [f"r{i}"]} for i in range(9)]
	assert len(merge_relics(many)) == 5


def test_build_emotional_vector_shape():
	affects = [{"child_id": "a", "emotion": "joy", "intensity": 0.8, "category": "social"}]
	assert build_emotional_vector(affects) == {"fragments": affects}


def test_synthesize_hub_v2_happy_path(monkeypatch):
	_mock_provider(monkeypatch, {"title": "Sesión definitiva", "summary": "Resumen maestro.", "texture": "Alivio tangible.", "lang": "es"})
	hub = synthesize_hub_v2(CHUNKS)
	assert hub["title"] == "Sesión definitiva"
	assert hub["texture"] == "Alivio tangible."
	assert hub["lang"] == "es"
	assert "_is_fallback" not in hub


def test_synthesize_hub_v2_uses_hub_task(monkeypatch):
	"""El hub debe resolverse por `task="hub"`, no por el default `conversation`."""
	provider = _mock_provider(monkeypatch, {"title": "T", "summary": "S", "texture": "", "lang": "es"})
	synthesize_hub_v2(CHUNKS)
	assert provider.generate.call_args.kwargs.get("task") == "hub"


def test_synthesize_hub_v2_texture_over_limit_splits_without_cutting(monkeypatch):
	_mock_provider(monkeypatch, {"title": "T", "summary": "S", "texture": "x" * 2000, "lang": "es"})
	hub = synthesize_hub_v2(CHUNKS)
	assert hub["texture"] == ""
	parts = hub["texture_parts"]
	assert parts and all(len(p) <= 960 for p in parts)
	assert "".join(parts) == "x" * 2000  # no se pierde un carácter
	assert hub["texture_split"] is True
	assert hub["texture_split_fallback"] is True
	assert hub["texture_over_target"] is True
	assert "texture_trimmed" not in hub
	assert hub["truncated"] is False


class _CompactProvider:
	"""Primera llamada: summary largo. Compaction: summary corto (texto plano)."""

	def __init__(self, compact: str = "resumen compacto"):
		self.compact = compact
		self.calls: list[str] = []

	def generate(self, prompt, messages=None, temperature=0.1, **kwargs):
		system = str((messages or [{}])[0].get("content") or "")
		self.calls.append(system)
		if "HUB_SUMMARY_COMPACT" in system:
			return self.compact
		return json.dumps({"title": "T", "summary": "L" * 1500, "texture": "", "lang": "es"})


def _patch_custom(monkeypatch, provider):
	from red_pill.core import providers

	monkeypatch.setattr(providers.ProviderRegistry, "get_inference_provider", classmethod(lambda cls, name=None: provider))


def _sip_provider(monkeypatch, payload):
	"""Provider SIP real (isinstance) con `generate` interceptado."""
	from red_pill.core import providers
	from red_pill.core.providers import SipInferenceProvider

	provider = SipInferenceProvider(socket_path="/tmp/no.sock")
	calls: list[dict] = []

	def fake_generate(prompt, messages=None, temperature=0.1, **kwargs):
		calls.append({"prompt": prompt, "messages": messages, **kwargs})
		return json.dumps(payload)

	monkeypatch.setattr(provider, "generate", fake_generate)
	monkeypatch.setattr(providers.ProviderRegistry, "get_inference_provider", classmethod(lambda cls, name=None: provider))
	return provider, calls


def test_synthesize_hub_v2_hybrid_large_uses_model_and_concise(monkeypatch):
	import red_pill.config as cfg

	_provider, calls = _sip_provider(monkeypatch, {"title": "T", "summary": "S", "texture": "", "lang": "es"})
	monkeypatch.setattr(cfg, "SLEEP_HUB_LARGE_INPUT_CHARS", 1)
	monkeypatch.setattr(cfg, "SLEEP_HUB_LARGE_MODEL", "k2_test")
	monkeypatch.setattr(cfg, "SLEEP_HUB_LARGE_PROMPT", "hub_synthesis_v2_concise.txt")

	hub = synthesize_hub_v2(CHUNKS)
	assert hub["large_path"] is True
	assert hub["model"] == "k2_test"
	assert hub["truncated"] is False
	assert calls[0]["model"] == "k2_test"
	assert "CONCISE" in calls[0]["messages"][0]["content"]


def test_synthesize_hub_v2_hybrid_small_keeps_default(monkeypatch):
	import red_pill.config as cfg

	_provider, calls = _sip_provider(monkeypatch, {"title": "T", "summary": "S", "texture": "", "lang": "es"})
	monkeypatch.setattr(cfg, "SLEEP_HUB_LARGE_INPUT_CHARS", 10**9)
	monkeypatch.setattr(cfg, "SLEEP_HUB_LARGE_MODEL", "k2_test")

	hub = synthesize_hub_v2(CHUNKS)
	assert hub["large_path"] is False
	assert hub["model"] == ""
	assert "model" not in calls[0]
	assert "CONCISE" not in calls[0]["messages"][0]["content"]


def test_synthesize_hub_v2_compacts_over_budget_summary(monkeypatch):
	provider = _CompactProvider("resumen compacto")
	_patch_custom(monkeypatch, provider)
	hub = synthesize_hub_v2(CHUNKS)
	assert hub["summary"] == "resumen compacto"
	assert hub["summary_compacted"] is True
	assert hub["summary_over_budget"] is False
	assert hub["compaction_calls"] == 1
	assert hub["truncated"] is False


def test_synthesize_hub_v2_keeps_summary_if_compaction_fails(monkeypatch):
	# La compaction devuelve lo mismo (no reduce): se conserva ENTERO, sin corte.
	provider = _CompactProvider(compact="L" * 1500)
	_patch_custom(monkeypatch, provider)
	hub = synthesize_hub_v2(CHUNKS)
	assert len(hub["summary"]) == 1500
	assert hub["summary_compacted"] is False
	assert hub["summary_over_budget"] is True
	assert "summary_trimmed" not in hub
	assert hub["truncated"] is False


def test_synthesize_hub_v2_falls_back_on_garbage(monkeypatch):
	_mock_provider(monkeypatch, "not json at all")
	monkeypatch.setattr("red_pill.metabolism.distiller.synthesize_hub", lambda summaries: "s1 s2 s3")
	hub = synthesize_hub_v2(CHUNKS)
	assert hub["_is_fallback"] is True
	assert hub["texture"] == ""
	assert hub["summary"]  # legacy aggregation still yields a hub


def test_synthesize_hub_v2_contract_never_cuts_output(monkeypatch):
	"""AD-116 revisado: si el modelo desobedece, se conserva y se marca; nunca se corta."""

	class _Giant:
		def generate(self, prompt, messages=None, temperature=0.1, **kwargs):  # noqa: ANN001
			system = str((messages or [{}])[0].get("content") or "")
			if "HUB_SUMMARY_COMPACT" in system or "HUB_TEXTURE_COMPACT" in system or "HUB_TEXTURE_SPLIT" in system:
				return "sigue largo. " * 400
			return json.dumps(
				{
					"title": "T" * 300,
					"summary": "frase corta. " * 125,
					"texture": "atmósfera densa. " * 125,
					"lang": "es",
				}
			)

	_patch_custom(monkeypatch, _Giant())
	hub = synthesize_hub_v2(CHUNKS)
	assert len(hub["title"]) == 300 and hub["title_over_target"] is True
	assert len(hub["summary"]) == len(("frase corta. " * 125).strip()) and hub["summary_over_budget"] is True
	assert hub["texture"] == ""
	assert hub["texture_parts"] and all(len(p) <= 960 for p in hub["texture_parts"])
	assert hub["texture_split"] is True
	assert hub["texture_split_fallback"] is True
	assert "texture_trimmed" not in hub and "summary_trimmed" not in hub and "output_trimmed" not in hub
	assert hub["truncated"] is False


def test_synthesize_hub_v2_texture_compacted_by_synthesis(monkeypatch):
	"""La compaction por síntesis reduce la textura sin cortarla."""

	class _Shrink:
		def __init__(self):
			self.calls = 0

		def generate(self, prompt, messages=None, temperature=0.1, **kwargs):  # noqa: ANN001
			self.calls += 1
			system = str((messages or [{}])[0].get("content") or "")
			if "HUB_TEXTURE_COMPACT" in system:
				return "Atmósfera serena y concreta."
			return json.dumps({"title": "T", "summary": "S", "texture": "x" * 1200, "lang": "es"})

	_patch_custom(monkeypatch, _Shrink())
	hub = synthesize_hub_v2(CHUNKS)
	assert hub["texture"] == "Atmósfera serena y concreta."
	assert hub["texture_compacted"] is True
	assert hub["texture_over_target"] is False
	assert hub.get("texture_parts") in (None, [])
	assert hub["truncated"] is False


def test_synthesize_hub_v2_texture_split_by_synthesis(monkeypatch):
	"""Si no cabe, el modelo la parte en trozos coherentes (síntesis, no corte)."""
	parts = ["a" * 600, "b" * 600]

	class _Split:
		def generate(self, prompt, messages=None, temperature=0.1, **kwargs):  # noqa: ANN001
			system = str((messages or [{}])[0].get("content") or "")
			if "HUB_TEXTURE_SPLIT" in system:
				return json.dumps({"parts": parts})
			if "HUB_TEXTURE_COMPACT" in system:
				return "x" * 1200  # no reduce
			return json.dumps({"title": "T", "summary": "S", "texture": "x" * 1200, "lang": "es"})

	_patch_custom(monkeypatch, _Split())
	hub = synthesize_hub_v2(CHUNKS)
	assert hub["texture"] == ""
	assert hub["texture_parts"] == parts
	assert hub["texture_split"] is True
	assert hub["texture_split_fallback"] is False
	assert "".join(hub["texture_parts"]) == "".join(parts)
	assert hub["truncated"] is False


def test_hub_summary_english_is_rewritten_to_spanish(monkeypatch):
	"""Granite cambiaba a inglés; la reescritura de idioma es síntesis, no corte."""
	import red_pill.config as cfg
	from red_pill.metabolism.distiller import _looks_english

	monkeypatch.setattr(cfg, "MEMENTO_PROMPT_LANGUAGE", "es", raising=False)
	english = "The team centralized configuration using YAML and fixed a variable naming error to ensure code accuracy. A detailed plan for the 0.8.0 release was established with pull requests and merges."

	class _Lang:
		def generate(self, prompt, messages=None, temperature=0.1, **kwargs):  # noqa: ANN001
			system = str((messages or [{}])[0].get("content") or "")
			if "HUB_LANGUAGE_REWRITE" in system:
				return "El equipo centralizó la configuración mediante YAML y corrigió un error de nomenclatura para asegurar la precisión del código. Se estableció un plan para la versión 0.8.0 con solicitudes de fusión e integraciones."
			return json.dumps({"title": "T", "summary": english, "texture": "atmósfera", "lang": "es"})

	_patch_custom(monkeypatch, _Lang())
	hub = synthesize_hub_v2(CHUNKS)
	assert _looks_english(hub["summary"]) is False
	assert hub["summary_language_rewritten"] is True
	assert hub["summary_lang_mismatch"] is False



def test_synthesize_hub_v2_texture_split_strict_synthesis_only(monkeypatch):
	"""Con el fallback lossless OFF, si la síntesis no parte, el hub no se escribe."""
	import pytest

	import red_pill.config as cfg
	from red_pill.metabolism.distiller import HubBudgetError

	_mock_provider(monkeypatch, {"title": "T", "summary": "S", "texture": "x" * 2000, "lang": "es"})
	monkeypatch.setattr(cfg, "SLEEP_HUB_TEXTURE_SPLIT_LOSSLESS_FALLBACK", False)
	with pytest.raises(HubBudgetError):
		synthesize_hub_v2(CHUNKS)


def test_split_text_lossless_never_drops_characters():
	from red_pill.metabolism.distiller import split_text_lossless

	text = "Primera frase completa. Segunda frase que tampoco cabe. Tercera frase final."
	parts = split_text_lossless(text, 64)
	assert len(parts) >= 2
	assert all(len(p) <= 64 for p in parts)
	# Sin pérdida: uniendo con espacio se reconstruye el texto (salvo espacios de junta).
	assert " ".join(parts).replace("  ", " ") == text
	assert parts[0].endswith(".")
