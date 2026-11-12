"""M4 single-writer — hub synthesis sobre engramas existentes (D2/D7/D14/G20)."""

from __future__ import annotations

from types import SimpleNamespace

from red_pill.metabolism.hub_synthesis import group_by_session, hub_input_hash, hub_point_id, synthesize_session_hubs


class FakeClient:
	def __init__(self, points):
		self._points = points  # [(id, payload)]
		self.written: dict = {}
		self.marked: dict = {}

	def collection_exists(self, c):
		return c == "work_memories"

	def scroll(self, c, limit=1000, offset=None, with_payload=True, with_vectors=False):
		return [SimpleNamespace(id=i, payload=p) for i, p in self._points], None

	def retrieve(self, collection_name, ids):
		out = []
		for i in ids:
			if i in self.written:
				out.append(SimpleNamespace(id=i, payload=self.written[i]))
		return out

	def set_payload(self, collection_name, payload, points):
		self.marked.setdefault(collection_name, {}).update({p: payload for p in points})


class FakeMM:
	def __init__(self, client, fail=False):
		self.client = client
		self.added: list = []
		self.fail = fail

	def add_memory(self, **kw):
		if self.fail:
			return ""
		self.added.append(kw)
		self.client.written[kw["point_id"]] = kw.get("metadata") or {}
		return kw["point_id"]


def _member(sid, content, cid="m1"):
	return (cid, {"origin": "memento", "node_type": "memento_engram", "session_id": sid, "content": content, "created_at": 100.0})


def test_hub_point_id_determinista():
	assert hub_point_id("work_memories", "opencode:ses_a") == hub_point_id("work_memories", "opencode:ses_a")
	assert hub_point_id("work_memories", "opencode:ses_a") != hub_point_id("social_memories", "opencode:ses_a")


def test_hub_input_hash_cambia_con_miembros():
	assert hub_input_hash(["a", "b"]) == hub_input_hash(["b", "a"])
	assert hub_input_hash(["a", "b"]) != hub_input_hash(["a", "c"])


def test_group_excluye_hubs_y_sin_sesion():
	points = [
		_member("opencode:ses_a", "idea 1", "m1"),
		_member("opencode:ses_a", "idea 2", "m2"),
		("h", {"node_type": "synthesis_hub", "session_id": "opencode:ses_a"}),
		("x", {"origin": "memento", "content": "sin sesión"}),
	]
	groups = group_by_session(points)
	assert set(groups) == {"opencode:ses_a"}
	assert len(groups["opencode:ses_a"]) == 2


def test_hubs_flag_off_no_hace_nada(monkeypatch):
	import red_pill.config as cfgmod

	monkeypatch.setattr(cfgmod, "SW_HUBS_ENABLED", False, raising=False)
	mm = FakeMM(FakeClient([_member("opencode:ses_a", "idea")]))
	stats = synthesize_session_hubs(mm, collections=("work_memories",))
	assert stats["enabled"] is False and not mm.added


def test_hubs_escribe_marca_e_idempotente(monkeypatch):
	import red_pill.config as cfgmod

	monkeypatch.setattr(cfgmod, "SW_HUBS_ENABLED", True, raising=False)
	client = FakeClient([_member("opencode:ses_a", "idea 1", "m1"), _member("opencode:ses_a", "idea 2", "m2")])
	mm = FakeMM(client)

	def synthesizer(chunks, **kwargs):
		return {"title": "T", "summary": "S", "texture": {"theme": "t"}, "lang": "es"}

	def affect(chunks):
		return ("gray", 0.5)

	stats = synthesize_session_hubs(mm, collections=("work_memories",), synthesizer=synthesizer, affect_fn=affect)
	assert stats["hubs_written"] == 1
	hid = hub_point_id("work_memories", "opencode:ses_a")
	assert mm.added[0]["point_id"] == hid
	assert mm.added[0]["metadata"]["node_type"] == "synthesis_hub"
	assert mm.added[0]["metadata"]["lazarus_phase"] == "synthesis_hub"
	assert set(client.marked["work_memories"]) == {"m1", "m2"}
	assert client.marked["work_memories"]["m1"]["hubbed"] is True

	# Segunda pasada: mismo input → se salta (idempotente, sin LLM).
	mm2 = FakeMM(client)
	stats2 = synthesize_session_hubs(mm2, collections=("work_memories",), synthesizer=synthesizer, affect_fn=affect)
	assert stats2["hubs_skipped"] == 1 and not mm2.added


def test_hub_fallback_no_escribe_ni_marca(monkeypatch):
	import red_pill.config as cfgmod

	monkeypatch.setattr(cfgmod, "SW_HUBS_ENABLED", True, raising=False)
	client = FakeClient([_member("s", "idea 1", "m1"), _member("s", "idea 2", "m2")])
	mm = FakeMM(client)

	def fallback(chunks, **kwargs):
		return {"title": "", "summary": "concat", "_is_fallback": True}

	stats = synthesize_session_hubs(mm, collections=("work_memories",), synthesizer=fallback, affect_fn=lambda c: ("gray", 0.5))
	assert stats["hubs_failed"] == 1 and stats["hubs_written"] == 0
	assert not mm.added and not client.marked  # ni hub ni miembros marcados


def test_hub_de_uno_se_omite(monkeypatch):
	import red_pill.config as cfgmod

	monkeypatch.setattr(cfgmod, "SW_HUBS_ENABLED", True, raising=False)
	client = FakeClient([_member("s", "única idea", "m1")])
	mm = FakeMM(client)
	stats = synthesize_session_hubs(
		mm, collections=("work_memories",), synthesizer=lambda c, **kw: {"title": "T", "summary": "S"}, affect_fn=lambda c: ("gray", 0.5)
	)
	assert stats["sessions"] == 0 and not mm.added


def test_escritura_fallida_no_marca_miembros(monkeypatch):
	import red_pill.config as cfgmod

	monkeypatch.setattr(cfgmod, "SW_HUBS_ENABLED", True, raising=False)
	client = FakeClient([_member("s", "idea 1", "m1"), _member("s", "idea 2", "m2")])
	mm = FakeMM(client, fail=True)
	stats = synthesize_session_hubs(
		mm, collections=("work_memories",), synthesizer=lambda c, **kw: {"title": "T", "summary": "S"}, affect_fn=lambda c: ("gray", 0.5)
	)
	assert stats["hubs_failed"] == 1
	marked = client.marked["work_memories"]
	assert not any(p.get("hubbed") for p in marked.values())  # nada se oculta
	assert marked["m1"]["hub_synth_reject_reason"] == "escritura_rechazada"


def test_hub_summary_over_hard_limit_no_se_escribe(monkeypatch):
	"""Un engrama es una idea: un summary de 3k no se inyecta en Qdrant."""
	import red_pill.config as cfgmod

	monkeypatch.setattr(cfgmod, "SW_HUBS_ENABLED", True, raising=False)
	monkeypatch.setattr(cfgmod, "SLEEP_HUB_SUMMARY_HARD_LIMIT", 1000, raising=False)
	client = FakeClient([_member("s", "idea 1", "m1"), _member("s", "idea 2", "m2")])
	mm = FakeMM(client)

	def long_synth(chunks, **kwargs):
		return {"title": "T", "summary": "historia " * 300, "texture": ""}

	stats = synthesize_session_hubs(mm, collections=("work_memories",), synthesizer=long_synth, affect_fn=lambda c: ("gray", 0.5))
	assert stats["hubs_failed"] == 1 and not mm.added
	# Los miembros siguen recallables; lo único que se anota es el marcador de
	# rechazo (compuerta de coste), nunca `hubbed`.
	marked = client.marked["work_memories"]
	assert not any(p.get("hubbed") for p in marked.values())
	assert marked["m1"]["hub_synth_reject_count"] == 1


def test_hub_texture_parts_se_escriben_sin_campo_texture(monkeypatch):
	"""AD-116 revisado: una textura partida conserva todo en `texture_parts`."""
	import red_pill.config as cfgmod

	monkeypatch.setattr(cfgmod, "SW_HUBS_ENABLED", True, raising=False)
	client = FakeClient([_member("s", "idea 1", "m1"), _member("s", "idea 2", "m2")])
	mm = FakeMM(client)

	def synthesis(chunks, **kwargs):
		return {
			"title": "T",
			"summary": "S",
			"texture": "",
			"texture_parts": ["atmósfera uno", "atmósfera dos"],
			"texture_split": True,
			"texture_split_fallback": False,
			"texture_over_target": True,
		}

	stats = synthesize_session_hubs(mm, collections=("work_memories",), synthesizer=synthesis, affect_fn=lambda c: ("gray", 0.5))
	assert stats["hubs_written"] == 1
	md = mm.added[0]["metadata"]
	assert md["texture_parts"] == ["atmósfera uno", "atmósfera dos"]
	assert "texture" not in md
	assert md["hub_texture_split"] is True
	assert md["hub_texture_split_fallback"] is False
	# El payload completo pasa el contrato real de escritura.
	from red_pill.schemas import CreateEngramRequest

	CreateEngramRequest(content=mm.added[0]["text"], metadata=md)


class FakeSignals(FakeMM):
	"""MemoryManager mínimo con señales: emisión, evaporación y diagnóstico."""

	def __init__(self, client, fail=False, existing=False):
		super().__init__(client, fail=fail)
		self.existing = existing
		self.injected: list = []
		self.evaporated: list = []

	def has_signal(self, name):
		return bool(self.existing or self.injected)

	def inject_signal(self, **kw):
		self.injected.append(kw)

	def evaporate_signals(self, name=None):
		self.evaporated.append(name)
		return 1


def test_fallo_de_hub_emite_el_motivo_no_solo_el_recuento(monkeypatch):
	"""El aviso debe decir POR QUÉ cayó el hub (2026-11-10: era indiagnosticable)."""
	import red_pill.config as cfgmod

	monkeypatch.setattr(cfgmod, "SW_HUBS_ENABLED", True, raising=False)
	client = FakeClient([_member("s", "idea 1", "m1"), _member("s", "idea 2", "m2")])
	mm = FakeSignals(client)

	def fallback(chunks, **kwargs):
		return {"title": "", "summary": "concat", "_is_fallback": True}

	stats = synthesize_session_hubs(mm, collections=("work_memories",), synthesizer=fallback, affect_fn=lambda c: ("gray", 0.5))
	assert stats["hubs_failed"] == 1
	assert len(mm.injected) == 1
	sig = mm.injected[0]
	assert sig["name"] == "hub_synthesis_failed"
	assert "sintesis_fallback" in sig["message"]
	assert sig["diagnosis"] == "hub_synthesis_failed:sintesis_fallback"
	assert not mm.evaporated


def test_ciclo_limpio_entierra_el_aviso(monkeypatch):
	"""Si la causa muere, el WARNING no sobrevive: dolor reconciliado por condición."""
	import red_pill.config as cfgmod

	monkeypatch.setattr(cfgmod, "SW_HUBS_ENABLED", True, raising=False)
	client = FakeClient([_member("s", "idea 1", "m1"), _member("s", "idea 2", "m2")])
	mm = FakeSignals(client, existing=True)

	stats = synthesize_session_hubs(
		mm, collections=("work_memories",), synthesizer=lambda c, **kw: {"title": "T", "summary": "S"}, affect_fn=lambda c: ("gray", 0.5)
	)
	assert stats["hubs_failed"] == 0
	assert mm.evaporated == ["hub_synthesis_failed"]


def test_ciclo_limpio_sin_aviso_previo_no_evapora_nada(monkeypatch):
	import red_pill.config as cfgmod

	monkeypatch.setattr(cfgmod, "SW_HUBS_ENABLED", True, raising=False)
	client = FakeClient([_member("s", "idea 1", "m1"), _member("s", "idea 2", "m2")])
	mm = FakeSignals(client)

	synthesize_session_hubs(
		mm, collections=("work_memories",), synthesizer=lambda c, **kw: {"title": "T", "summary": "S"}, affect_fn=lambda c: ("gray", 0.5)
	)
	assert not mm.evaporated and not mm.injected


def test_aviso_de_hub_lista_las_sesiones_una_sola_vez(monkeypatch):
	"""Medido 2026-11-12: el WARNING salía con `sesiones:` dos veces y recuentos
	distintos (3 en la primera lista, 4 en la segunda). Un dolor que se
	contradice consigo mismo no se diagnostica de un vistazo."""
	import red_pill.config as cfgmod

	monkeypatch.setattr(cfgmod, "SW_HUBS_ENABLED", True, raising=False)
	client = FakeClient([_member("s", "idea 1", "m1"), _member("s", "idea 2", "m2")])
	mm = FakeSignals(client)

	def fallback(chunks, **kwargs):
		return {"title": "", "summary": "concat", "_is_fallback": True, "_fallback_reason": "invalid_output"}

	stats = synthesize_session_hubs(mm, collections=("work_memories",), synthesizer=fallback, affect_fn=lambda c: ("gray", 0.5))
	assert stats["hubs_failed"] == 1
	message = mm.injected[0]["message"]
	assert message.count("sesiones:") == 1, message
	assert "motivos: sintesis_invalid_output×1" in message
	assert "work_memories:s" in message
