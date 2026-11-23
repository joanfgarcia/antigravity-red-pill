"""El marcador de rechazo de un hub dice POR QUÉ, no solo que falló.

Medido 2026-11-20 04:24: `summary 1441 > hard limit 1000 … no se escribe`.
El log no permitía distinguir si la compactación por síntesis no había llegado
a correr (nada que reintentar igual) o si el maestro la había ignorado dos
veces. El hub rechazado no se escribe, así que el marcador de rechazo es el
único sitio donde esa traza sobrevive a la noche.
"""

from __future__ import annotations

from red_pill.metabolism.hub_synthesis import synthesize_session_hubs
from tests.test_sw_m4_hubs import FakeClient, FakeMM, _member


def test_rechazo_por_tope_duro_guarda_la_traza_de_compactacion(monkeypatch):
	import red_pill.config as cfgmod

	monkeypatch.setattr(cfgmod, "SW_HUBS_ENABLED", True, raising=False)
	monkeypatch.setattr(cfgmod, "SLEEP_HUB_SUMMARY_HARD_LIMIT", 1000, raising=False)
	client = FakeClient([_member("s", "idea 1", "m1"), _member("s", "idea 2", "m2")])
	mm = FakeMM(client)

	def long_synth(chunks, **kwargs):
		return {
			"title": "T",
			"summary": "historia " * 300,
			"texture": "",
			"compaction_calls": 2,
			"summary_compaction_calls": 2,
			"texture_compaction_calls": 0,
			"summary_compacted": True,
		}

	stats = synthesize_session_hubs(mm, collections=("work_memories",), synthesizer=long_synth, affect_fn=lambda c: ("gray", 0.5))
	assert stats["hubs_failed"] == 1 and not mm.added
	marked = client.marked["work_memories"]
	assert marked["m1"]["hub_synth_reject_reason"] == "summary_over_hard_limit"
	detail = marked["m1"]["hub_synth_reject_detail"]
	assert detail["chars"] > detail["hard"]
	assert detail["compaction_calls"] == 2
	assert detail["summary_calls"] == 2
	assert detail["texture_calls"] == 0
	assert detail["compacted"] is True


def test_rechazo_por_textura_no_culpa_al_summary(monkeypatch):
	"""COMPACT-TRACE-001: el detalle cita las llamadas del SUMMARY, no el total.

	Un hub con 3 compactaciones de textura y ninguna del summary se leía como
	«el maestro ignoró la compactación 3 veces». El veredicto debe nombrar el
	campo que decide: summary_calls=0 ⇒ la compactación del summary no corrió.
	"""
	import red_pill.config as cfgmod

	monkeypatch.setattr(cfgmod, "SW_HUBS_ENABLED", True, raising=False)
	monkeypatch.setattr(cfgmod, "SLEEP_HUB_SUMMARY_HARD_LIMIT", 1000, raising=False)
	client = FakeClient([_member("s", "idea 1", "m1"), _member("s", "idea 2", "m2")])
	mm = FakeMM(client)

	def long_synth(chunks, **kwargs):
		return {
			"title": "T",
			"summary": "historia " * 300,
			"texture": "textura compactada",
			"compaction_calls": 3,
			"summary_compaction_calls": 0,
			"texture_compaction_calls": 3,
			"summary_compacted": False,
		}

	synthesize_session_hubs(mm, collections=("work_memories",), synthesizer=long_synth, affect_fn=lambda c: ("gray", 0.5))
	detail = client.marked["work_memories"]["m1"]["hub_synth_reject_detail"]
	assert detail["compaction_calls"] == 3
	assert detail["summary_calls"] == 0
	assert detail["texture_calls"] == 3


def test_rechazo_sin_compactacion_se_distingue_del_que_la_ignoro(monkeypatch):
	"""`compaction_calls=0` es diagnóstico distinto de «el maestro no obedeció».

	Sin este dato los dos casos se leían idénticos en el marcador y la noche
	siguiente no había forma de saber qué mirar.
	"""
	import red_pill.config as cfgmod

	monkeypatch.setattr(cfgmod, "SW_HUBS_ENABLED", True, raising=False)
	monkeypatch.setattr(cfgmod, "SLEEP_HUB_SUMMARY_HARD_LIMIT", 1000, raising=False)
	client = FakeClient([_member("s", "idea 1", "m1"), _member("s", "idea 2", "m2")])
	mm = FakeMM(client)

	def long_synth(chunks, **kwargs):
		return {"title": "T", "summary": "historia " * 300, "texture": ""}

	synthesize_session_hubs(mm, collections=("work_memories",), synthesizer=long_synth, affect_fn=lambda c: ("gray", 0.5))
	detail = client.marked["work_memories"]["m1"]["hub_synth_reject_detail"]
	assert detail["compaction_calls"] == 0
	assert detail["compacted"] is False


def test_hub_que_cabe_no_lleva_traza_de_rechazo(monkeypatch):
	import red_pill.config as cfgmod

	monkeypatch.setattr(cfgmod, "SW_HUBS_ENABLED", True, raising=False)
	client = FakeClient([_member("s", "idea 1", "m1"), _member("s", "idea 2", "m2")])
	mm = FakeMM(client)

	stats = synthesize_session_hubs(
		mm,
		collections=("work_memories",),
		synthesizer=lambda c, **kw: {"title": "T", "summary": "cabe", "texture": ""},
		affect_fn=lambda c: ("gray", 0.5),
	)
	assert stats["hubs_written"] == 1
	assert mm.added
	payload = mm.added[0]["metadata"]
	assert "hub_synth_reject_detail" not in payload
	assert payload["hub_summary_compacted"] is False


def test_marcador_sigue_siendo_el_mismo_contrato(monkeypatch):
	"""La traza es ADITIVA: hash, contador, motivo y fecha no cambian."""
	import red_pill.config as cfgmod

	monkeypatch.setattr(cfgmod, "SW_HUBS_ENABLED", True, raising=False)
	monkeypatch.setattr(cfgmod, "SLEEP_HUB_SUMMARY_HARD_LIMIT", 1000, raising=False)
	client = FakeClient([_member("s", "idea 1", "m1"), _member("s", "idea 2", "m2")])
	mm = FakeMM(client)

	synthesize_session_hubs(
		mm,
		collections=("work_memories",),
		synthesizer=lambda c, **kw: {"title": "T", "summary": "historia " * 300, "texture": ""},
		affect_fn=lambda c: ("gray", 0.5),
	)
	payload = client.marked["work_memories"]["m1"]
	for key in ("hub_synth_reject_hash", "hub_synth_reject_count", "hub_synth_reject_reason", "hub_synth_reject_at"):
		assert key in payload
	assert payload["hub_synth_reject_count"] == 1
