"""Compuerta de coste de la síntesis de hubs (2026-11-10).

Un rechazo del hub YA sintetizado (summary sobre el tope duro, idioma, compuerta
de escritura) significa: el LLM corrió, el veredicto no cambió y el input
tampoco. Reintentarlo cada ciclo de sueño paga el mismo coste para el mismo
veredicto, para siempre. Tras `SW_HUB_SYNTH_MAX_REJECTIONS` intentos con el
mismo `hub_input_hash` la sesión queda EN ESPERA hasta que su entrada cambie.

Los fallos transitorios (LLM caído → fallback) NO se cuentan: son baratos y se
resuelven solos.
"""

from __future__ import annotations

from types import SimpleNamespace

from red_pill.metabolism.hub_synthesis import hub_point_id, synthesize_session_hubs


class MutableClient:
	"""Fake que aplica `set_payload` sobre los puntos: el marcador persiste."""

	def __init__(self, points):
		self.points = {pid: dict(payload) for pid, payload in points}
		self.written: dict = {}

	def collection_exists(self, c):
		return c == "work_memories"

	def scroll(self, c, limit=1000, offset=None, with_payload=True, with_vectors=False):
		return [SimpleNamespace(id=pid, payload=dict(pl)) for pid, pl in self.points.items()], None

	def retrieve(self, collection_name, ids):
		return [SimpleNamespace(id=i, payload=self.written[i]) for i in ids if i in self.written]

	def set_payload(self, collection_name, payload, points):
		for pid in points:
			self.points.setdefault(pid, {}).update(payload)


class FakeMM:
	def __init__(self, client, fail_write=False):
		self.client = client
		self.fail_write = fail_write
		self.added: list = []
		self.calls = 0

	def add_memory(self, **kw):
		if self.fail_write:
			return ""
		self.added.append(kw)
		self.client.written[kw["point_id"]] = dict(kw.get("metadata") or {})
		return kw["point_id"]


def _member(sid, content, cid):
	return (cid, {"origin": "memento", "node_type": "memento_engram", "session_id": sid, "content": content, "created_at": 100.0})


def _affect(chunks):
	return ("gray", 0.5)


def _over_limit(chunks, **kwargs):
	return {"title": "T", "summary": "historia " * 300, "texture": ""}


def _ok(chunks, **kwargs):
	return {"title": "T", "summary": "S", "texture": "", "lang": "es"}


def _run(mm, synthesizer, collections=("work_memories",)):
	return synthesize_session_hubs(mm, collections=collections, synthesizer=synthesizer, affect_fn=_affect)


def _counting(synth):
	def wrapper(chunks, **kwargs):
		wrapper.calls += 1
		return synth(chunks, **kwargs)

	wrapper.calls = 0
	return wrapper


def test_entrada_rechazada_deja_de_pagar_tras_el_tope(monkeypatch):
	import red_pill.config as cfgmod

	monkeypatch.setattr(cfgmod, "SW_HUBS_ENABLED", True, raising=False)
	monkeypatch.setattr(cfgmod, "SLEEP_HUB_SUMMARY_HARD_LIMIT", 1000, raising=False)
	monkeypatch.setattr(cfgmod, "SW_HUB_SYNTH_MAX_REJECTIONS", 2, raising=False)
	client = MutableClient([_member("s", "idea 1", "m1"), _member("s", "idea 2", "m2")])
	synth = _counting(_over_limit)

	for _ in range(2):
		stats = _run(FakeMM(client), synth)
		assert stats["hubs_failed"] == 1 and stats["hubs_deferred"] == 0
	assert synth.calls == 2, "los dos primeros intentos SÍ pagan la síntesis"

	for _ in range(3):
		stats = _run(FakeMM(client), synth)
		assert stats["hubs_deferred"] == 1 and stats["hubs_failed"] == 0
	assert synth.calls == 2, "el input no cambió: la tercera no paga otra síntesis"


def test_entrada_nueva_reinicia_el_contador(monkeypatch):
	import red_pill.config as cfgmod

	monkeypatch.setattr(cfgmod, "SW_HUBS_ENABLED", True, raising=False)
	monkeypatch.setattr(cfgmod, "SLEEP_HUB_SUMMARY_HARD_LIMIT", 1000, raising=False)
	monkeypatch.setattr(cfgmod, "SW_HUB_SYNTH_MAX_REJECTIONS", 2, raising=False)
	members = [_member("s", "idea 1", "m1"), _member("s", "idea 2", "m2")]
	client = MutableClient(list(members))
	synth = _counting(_over_limit)

	for _ in range(2):
		_run(FakeMM(client), synth)
	assert _run(FakeMM(client), synth)["hubs_deferred"] == 1

	# Llega un miembro nuevo: otra entrada, otro veredicto posible.
	client.points["m3"] = dict(members[0][1])
	stats = _run(FakeMM(client), synth)
	assert stats["hubs_failed"] == 1 and stats["hubs_deferred"] == 0
	assert synth.calls == 3


def test_fallo_transitorio_no_gasta_intentos(monkeypatch):
	"""El LLM caído devuelve fallback: barato y cambia solo, nunca en espera."""
	import red_pill.config as cfgmod

	monkeypatch.setattr(cfgmod, "SW_HUBS_ENABLED", True, raising=False)
	monkeypatch.setattr(cfgmod, "SW_HUB_SYNTH_MAX_REJECTIONS", 1, raising=False)
	client = MutableClient([_member("s", "idea 1", "m1"), _member("s", "idea 2", "m2")])

	def fallback(chunks, **kwargs):
		return {"title": "", "summary": "concat", "_is_fallback": True}

	for _ in range(4):
		stats = _run(FakeMM(client), fallback)
		assert stats["hubs_failed"] == 1 and stats["hubs_deferred"] == 0


def test_hub_escrito_limpia_el_marcador(monkeypatch):
	import red_pill.config as cfgmod

	monkeypatch.setattr(cfgmod, "SW_HUBS_ENABLED", True, raising=False)
	monkeypatch.setattr(cfgmod, "SLEEP_HUB_SUMMARY_HARD_LIMIT", 1000, raising=False)
	monkeypatch.setattr(cfgmod, "SW_HUB_SYNTH_MAX_REJECTIONS", 2, raising=False)
	client = MutableClient([_member("s", "idea 1", "m1"), _member("s", "idea 2", "m2")])

	_run(FakeMM(client), _over_limit)
	assert client.points["m1"]["hub_synth_reject_count"] == 1

	# La causa desaparece (compuerta ajustada): el hub se escribe y el marcador
	# se limpia en el mismo set_payload que marca a los miembros.
	monkeypatch.setattr(cfgmod, "SLEEP_HUB_SUMMARY_HARD_LIMIT", 100000, raising=False)
	stats = _run(FakeMM(client), _over_limit)
	assert stats["hubs_written"] == 1
	assert client.points["m1"]["hubbed"] is True
	assert client.points["m1"]["hub_synth_reject_count"] == 0
	assert client.points["m1"]["hub_synth_reject_hash"] == ""
	assert hub_point_id("work_memories", "s") in client.written


def test_force_salta_la_compuerta(monkeypatch):
	"""La remediación forzada (re-síntesis de hubs truncados) no queda en espera."""
	import red_pill.config as cfgmod

	monkeypatch.setattr(cfgmod, "SW_HUBS_ENABLED", True, raising=False)
	monkeypatch.setattr(cfgmod, "SLEEP_HUB_SUMMARY_HARD_LIMIT", 1000, raising=False)
	monkeypatch.setattr(cfgmod, "SW_HUB_SYNTH_MAX_REJECTIONS", 1, raising=False)
	client = MutableClient([_member("s", "idea 1", "m1"), _member("s", "idea 2", "m2")])
	synth = _counting(_over_limit)

	_run(FakeMM(client), synth)
	stats = synthesize_session_hubs(
		FakeMM(client),
		collections=("work_memories",),
		synthesizer=synth,
		affect_fn=_affect,
		force_sessions={"s"},
	)
	assert synth.calls == 2, "forzada = se paga aunque el marcador diga espera"
	assert stats["hubs_failed"] == 1 and stats["hubs_deferred"] == 0
