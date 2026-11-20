"""Tests del núcleo puro del hook (RFC-HARNESS-001 · P1).

Lo que se protege aquí:

- El mapa de arneses: el kernel hablaba `claude_code` y el RFC `claude-code`;
  sin mapa único, medio arnés no resuelve cuerpo (S15).
- `originator` lo compone el **arnés** desde `session_id`, nunca el modelo.
- `delivery_id` determinista → el ack puede ser idempotente (S13).
- `telemetry_text` es SILENT cuando no hay nada: una línea vacía por turno
  también se paga.
- Procedencia: lo que no es kernel va con `trusted=False` (seguridad F8).
"""

from __future__ import annotations

import pytest

from red_pill.hooks.context_api import (
	AckLedger,
	HookPayloadError,
	HookRequest,
	block,
	canon_harness,
	delivery_id,
	originator_for,
	telemetry_text,
)


def test_mapa_de_arneses_unifica_nombres():
	assert canon_harness("opencode") == "opencode"
	assert canon_harness("claude-code") == "claude_code"
	assert canon_harness("claude-code-project") == "claude_code"
	assert canon_harness("claude-desktop") == "claude_code"
	assert canon_harness("pi") == "pi"
	assert canon_harness("antigravity") == "antigravity"
	# desconocido: se normaliza, no se inventa
	assert canon_harness("Some-IDE") == "some_ide"


def test_originator_composicion_y_validacion():
	assert originator_for("opencode", "ses_123") == "opencode:ses_123"
	assert originator_for("claude-code", "abc") == "claude_code:abc"
	with pytest.raises(HookPayloadError):
		originator_for("opencode", "")
	with pytest.raises(HookPayloadError):
		originator_for("opencode", "x" * 500)


def test_delivery_id_es_estable_y_discrimina():
	a = delivery_id("opencode:ses_1", 3, "full")
	assert a == delivery_id("opencode:ses_1", 3, "full"), "debe ser estable para acks idempotentes"
	assert a != delivery_id("opencode:ses_1", 4, "full")
	assert a != delivery_id("opencode:ses_2", 3, "full")
	assert a != delivery_id("opencode:ses_1", 3, "light")


def test_payload_valido_produce_request():
	req = HookRequest.from_payload(
		{
			"session_id": "ses_9",
			"harness": "pi",
			"model": "llamacpp/mimo",
			"turn": "7",
			"prompt": "hola",
			"need": "full",
			"reason": "session_start",
		}
	)
	assert req.originator == "pi:ses_9"
	assert req.turn == 7
	assert req.need == "full"


@pytest.mark.parametrize(
	"payload",
	[
		None,
		{},
		{"harness": "pi"},
		{"session_id": "s", "harness": "pi", "need": "todo"},
		{"session_id": "s", "harness": "pi", "reason": "porque-sí"},
		{"session_id": "s", "harness": "pi", "turn": "no-es-un-numero"},
	],
)
def test_payload_invalido_falla_con_4xx(payload):
	with pytest.raises(HookPayloadError):
		HookRequest.from_payload(payload)


def test_telemetria_es_silent_cuando_no_hay_nada():
	assert telemetry_text(None) is None
	assert telemetry_text({}) is None
	assert telemetry_text({"open_loops": 0, "pain": 0, "coro": 0, "jobs": 0}) is None


def test_telemetria_cabe_en_una_linea():
	linea = telemetry_text(
		{
			"open_loops": 16,
			"pain": 3,
			"coro": 1,
			"jobs": 2,
			"mood": {"emotion": "gray", "lag_s": 180, "stale": False},
		}
	)
	assert linea == "OPEN LOOPS 16 · dolor 3 · coro 1 novedad · jobs 2 · mood gray 3m"
	assert "\n" not in linea
	assert len(linea) < 120


def test_mood_caducada_se_marca_y_no_se_presenta_como_actual():
	linea = telemetry_text({"mood": {"emotion": "red", "lag_s": 2400, "stale": True}})
	assert linea is not None
	assert "histórica" in linea


def test_bloque_lleva_procedencia():
	k = block("coro", "texto de otro agente", origin="coro", trusted=False)
	assert k == {"kind": "coro", "origin": "coro", "trusted": False, "text": "texto de otro agente"}
	assert block("identity", "x")["trusted"] is True


def test_ledger_de_acks_es_idempotente_y_acotado(tmp_path):
	ledger = AckLedger(path=tmp_path / "acks.json", limit=3)
	assert not ledger.seen("d1")
	ledger.mark("d1")
	assert ledger.seen("d1")
	ledger.mark("d1")  # repetir no duplica
	ledger.mark("d2")
	ledger.mark("d3")
	ledger.mark("d4")  # expulsa el más viejo
	# se relee del disco: sobrevive a recargas del plugin
	fresh = AckLedger(path=tmp_path / "acks.json", limit=3)
	assert fresh.seen("d4")
	assert not fresh.seen("d1")
