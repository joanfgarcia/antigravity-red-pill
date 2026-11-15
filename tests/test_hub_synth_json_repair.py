"""JSON del maestro de hubs: reparación de comillas sin escapar y razón del fallback.

Medido el 2026-11-12 (ciclo nocturno 4047324f): dos hubs se perdieron porque el
summary citaba código con comillas dobles — `print("session:", r.conversation_id)`
— y el JSON dejaba de ser válido. `_sanitize_llm_json` solo repara backslashes
ilegales, así que la síntesis entera se tiraba. Y como el fallback no era
facturable, esas sesiones volvían a pagar el LLM cada noche para siempre.

Estos tests fijan las dos mitades: reparar lo que tenga arreglo y distinguir el
fallback TRANSITORIO (proveedor caído) del DETERMINISTA (salida inservible).
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from red_pill.metabolism.distiller import _parse_hub_payload, synthesize_hub_v2

CHUNKS = [
	{"summary": "s1", "texture": "técnico", "emotion": "neutral", "intensity": 0.3, "category": "work", "lang": "es", "relics": []},
	{"summary": "s2", "texture": "técnico", "emotion": "neutral", "intensity": 0.3, "category": "work", "lang": "es", "relics": []},
]

# La forma EXACTA del fallo real: comillas dobles de contenido, sin escapar.
BROKEN_JSON = """{
  "title": "Verificación de sesión y configuración del puente Opencode",
  "summary": "Joan verificó que el puente opencode devolvió una sesión válida al ejecutar `print("session:", r.conversation_id)` después del prompt, y ajustó el arranque del servicio.",
  "texture": "técnico",
  "lang": "es"
}"""


def _mock_provider(monkeypatch, payload):
	from red_pill.core import providers

	provider = MagicMock()
	provider.generate.return_value = json.dumps(payload) if isinstance(payload, dict) else payload
	monkeypatch.setattr(providers.ProviderRegistry, "get_inference_provider", classmethod(lambda cls, name=None: provider))
	return provider


def test_json_del_hub_con_comillas_sin_escapar_se_repara(monkeypatch):
	"""El caso real: el summary cita código y el JSON deja de cerrar."""
	_mock_provider(monkeypatch, BROKEN_JSON)
	hub = synthesize_hub_v2(CHUNKS)
	assert "_is_fallback" not in hub, "el hub se recupera, no se tira"
	assert 'print("session:", r.conversation_id)' in hub["summary"]
	assert hub["title"].startswith("Verificación de sesión")


def test_parse_hub_payload_repara_y_conserva_el_texto(monkeypatch):
	parsed = _parse_hub_payload(BROKEN_JSON, "es")
	assert parsed is not None
	assert 'print("session:", r.conversation_id)' in parsed["summary"]
	assert parsed["lang"] == "es"


def test_parse_hub_payload_no_toca_json_valido():
	valid = json.dumps({"title": "T", "summary": "Idea limpia.", "texture": "", "lang": "es"})
	parsed = _parse_hub_payload(valid, "es")
	assert parsed is not None and parsed["summary"] == "Idea limpia."


def test_json_irreparable_sigue_siendo_fallback_con_razon(monkeypatch):
	"""Si el reparo no basta, no se inventa nada: fallback, pero con motivo."""
	_mock_provider(monkeypatch, "no json at all")
	hub = synthesize_hub_v2(CHUNKS)
	assert hub["_is_fallback"] is True
	assert hub["_fallback_reason"] == "invalid_output"


def test_proveedor_caido_es_un_fallback_transitorio(monkeypatch):
	from red_pill.core import providers

	def _boom(cls, name=None):
		raise RuntimeError("provider down")

	monkeypatch.setattr(providers.ProviderRegistry, "get_inference_provider", classmethod(_boom))
	hub = synthesize_hub_v2(CHUNKS)
	assert hub["_is_fallback"] is True
	assert hub["_fallback_reason"] == "llm_unavailable"


def test_json_cortado_por_max_tokens_no_se_rescata(monkeypatch):
	"""AD-115: un summary a medias NO se escribe como hub.

	Si el modelo se quedó sin tokens, el JSON no llegó a `texture`/`lang`. El
	rescate campo a campo escribiría media idea; antes se reintentaba, y así
	sigue: fallback, sin hub.
	"""
	truncado = """{
  "title": "Verificación del puente",
  "summary": "Joan verificó que el puente devolvía una sesión válida y después ajustó"""
	_mock_provider(monkeypatch, truncado)
	hub = synthesize_hub_v2(CHUNKS)
	assert hub["_is_fallback"] is True
	assert hub["_fallback_reason"] == "invalid_output"


def test_json_incompleto_con_llave_dentro_no_se_rescata(monkeypatch):
	"""El caso que la puerta de completitud tiene que frenar de verdad.

	Aquí sí hay una `}` (dentro del código citado), así que el regex la toma por
	cierre del objeto: sin la puerta, el rescate escribiría un summary sin final.
	"""
	salvageable_pero_incompleto = """{
  "title": "Bug en el formateo",
  "summary": "Se arregló el `print(f"{x}")` que rompía el log y quedó pendiente"""
	_mock_provider(monkeypatch, salvageable_pero_incompleto)
	hub = synthesize_hub_v2(CHUNKS)
	assert hub["_is_fallback"] is True
	assert hub["_fallback_reason"] == "invalid_output"
