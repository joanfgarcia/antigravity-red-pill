"""Caducidad de la espera de síntesis de hubs (2026-11-12).

La compuerta de coste (2026-11-10) deja una sesión EN ESPERA cuando su entrada
ya se rechazó `SW_HUB_SYNTH_MAX_REJECTIONS` veces con el mismo `hub_input_hash`.
Correcto contra el re-pago… y una trampa sin salida: una sesión cerrada no
vuelve a cambiar de entrada nunca, así que se queda sin hub para siempre y su
aviso de dolor no muere jamás (no hay ciclo limpio que lo entierre).

`SW_HUB_SYNTH_WAIT_RETRY_DAYS` acota la espera: pasada la ventana, la sesión
merece UN intento más y el fallo re-arma la ventana. Coste acotado a una
síntesis por ventana y sesión; 0 = espera indefinida (comportamiento previo).
"""

from __future__ import annotations

import time

from test_hub_synth_rejection_gate import FakeMM, MutableClient, _counting, _member, _over_limit, _run


def _setup(monkeypatch, retry_days, max_rejections=1, hard_limit=1000):
	import red_pill.config as cfgmod

	monkeypatch.setattr(cfgmod, "SW_HUBS_ENABLED", True, raising=False)
	monkeypatch.setattr(cfgmod, "SLEEP_HUB_SUMMARY_HARD_LIMIT", hard_limit, raising=False)
	monkeypatch.setattr(cfgmod, "SW_HUB_SYNTH_MAX_REJECTIONS", max_rejections, raising=False)
	monkeypatch.setattr(cfgmod, "SW_HUB_SYNTH_WAIT_RETRY_DAYS", retry_days, raising=False)


def _client():
	return MutableClient([_member("s", "idea 1", "m1"), _member("s", "idea 2", "m2")])


def _age_marker(client, days):
	"""Envejece el marcador de rechazo de todos los miembros (días)."""
	for payload in client.points.values():
		if payload.get("hub_synth_reject_count"):
			payload["hub_synth_reject_at"] = time.time() - days * 86400.0


def test_la_espera_caduca_y_paga_un_intento(monkeypatch):
	_setup(monkeypatch, retry_days=7)
	client = _client()
	synth = _counting(_over_limit)

	_run(FakeMM(client), synth)
	assert synth.calls == 1, "el primer rechazo paga"
	assert _run(FakeMM(client), synth)["hubs_waiting"] == 1
	assert synth.calls == 1, "dentro de la ventana no se paga otra síntesis"

	_age_marker(client, 8)
	assert _run(FakeMM(client), synth)["hubs_waiting"] == 0
	assert synth.calls == 2, "la espera caducó: un intento más"

	# El fallo re-armó la ventana: la siguiente noche vuelve a esperar.
	assert _run(FakeMM(client), synth)["hubs_waiting"] == 1
	assert synth.calls == 2


def test_dentro_de_la_ventana_sigue_en_espera(monkeypatch):
	_setup(monkeypatch, retry_days=7)
	client = _client()
	synth = _counting(_over_limit)
	_run(FakeMM(client), synth)
	_age_marker(client, 1)
	for _ in range(3):
		assert _run(FakeMM(client), synth)["hubs_waiting"] == 1
	assert synth.calls == 1


def test_marcador_sin_fecha_caduca(monkeypatch):
	"""Marcador legacy (anterior al 2026-11-12) sin `hub_synth_reject_at`."""
	_setup(monkeypatch, retry_days=7)
	client = _client()
	synth = _counting(_over_limit)
	_run(FakeMM(client), synth)
	for payload in client.points.values():
		payload.pop("hub_synth_reject_at", None)
	assert _run(FakeMM(client), synth)["hubs_waiting"] == 0
	assert synth.calls == 2, "sin fecha no se puede probar la espera: se paga una vez"


def test_ventana_cero_es_espera_indefinida(monkeypatch):
	_setup(monkeypatch, retry_days=0)
	client = _client()
	synth = _counting(_over_limit)
	_run(FakeMM(client), synth)
	_age_marker(client, 365)
	for _ in range(3):
		assert _run(FakeMM(client), synth)["hubs_waiting"] == 1
	assert synth.calls == 1


def test_caducidad_no_resucita_un_hub_ya_escrito(monkeypatch):
	"""Caducada la espera, si la causa murió el hub se escribe y el marcador se limpia."""
	_setup(monkeypatch, retry_days=7)
	client = _client()
	_run(FakeMM(client), _over_limit)
	assert client.points["m1"]["hub_synth_reject_count"] == 1
	_age_marker(client, 30)
	import red_pill.config as cfgmod

	monkeypatch.setattr(cfgmod, "SLEEP_HUB_SUMMARY_HARD_LIMIT", 100000, raising=False)
	stats = _run(FakeMM(client), _over_limit)
	assert stats["hubs_written"] == 1
	assert client.points["m1"]["hub_synth_reject_count"] == 0
