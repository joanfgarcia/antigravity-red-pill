"""MEM-011 · F2 — síntesis de partes y raíz (flag OFF por defecto).

Con `SW_HUB_POLAROID_ENABLED=true`, una sesión que no cabe en una polaroid se
escribe como N partes + 1 raíz; con el flag apagado, el camino es exactamente el
de siempre (`no_parts`).
"""

from unittest.mock import MagicMock

import pytest

from red_pill.metabolism import hub_parts

_PREFIX = "00000000-0000-0000-0000-00000000ee"


@pytest.fixture()
def polaroids(monkeypatch):
	def fake(session_id, root=None):
		return [
			hub_parts.PolaroidRange("0001-0040", 10, 100),
			hub_parts.PolaroidRange("0041-0080", 101, 200),
			hub_parts.PolaroidRange("0081-0120", 201, 300),
		]

	monkeypatch.setattr(hub_parts, "polaroids_for_session", fake)
	return None


def _member(n: int, lines: str, chars: int = 400) -> tuple:
	return (
		f"{_PREFIX}{n:02d}",
		{
			"content": "x" * chars,
			"session_id": "work:ses_mem011",
			"source_lines": f"memento/index.md#{lines}",
			"created_at": 100.0 + n,
			"node_type": "memento_engram",
		},
	)


def _memory() -> MagicMock:
	memory = MagicMock()
	written: list = []

	def add_memory(**kwargs):
		written.append(kwargs)
		return f"point-{len(written)}"

	memory.add_memory.side_effect = add_memory
	memory.written = written
	memory.client.scroll.return_value = ([], None)
	memory.client.retrieve.return_value = []
	return memory


def test_sesion_que_cabe_en_una_parte_no_hace_nada(polaroids):
	memory = _memory()
	members = [_member(1, "l20-30", 10), _member(2, "l120-130", 10)]
	synth = MagicMock(return_value={"title": "t", "summary": "s"})
	assert (
		hub_parts.synthesize_parts(memory, "work_memories", "work:ses_mem011", members, synth, lambda c: ("neutral", 0.5), budget=8000) == "no_parts"
	)
	synth.assert_not_called()


def test_escribe_partes_y_raiz_con_su_rol(polaroids):
	memory = _memory()
	members = [_member(1, "l20-30"), _member(2, "l120-130"), _member(3, "l250-260")]
	synth = MagicMock(return_value={"title": "t", "summary": "resumen corto"})
	affect = lambda chunks: ("neutral", 0.5)  # noqa: E731

	result = hub_parts.synthesize_parts(memory, "work_memories", "work:ses_mem011", members, synth, affect, budget=500)
	assert result == "written"
	# 3 partes (una por polaroid, 400 chars cada una con budget 500) + 1 raíz
	assert synth.call_count == 4
	metas = [call.kwargs["metadata"] for call in memory.add_memory.call_args_list]
	roles = [m.get("hub_role") for m in metas]
	assert roles == ["part", "part", "part", "root"]
	assert [m.get("hub_depth") for m in metas] == [1, 1, 1, 2]
	assert [m.get("part_key") for m in metas[:3]] == ["0001-0040", "0041-0080", "0081-0120"]
	assert metas[3].get("part_key") is None
	# La raíz tiene como miembros las 3 partes, no las hojas.
	assert metas[3]["hub_members_count"] == 3


def test_si_una_parte_falla_no_se_escribe_la_raiz(polaroids):
	memory = _memory()
	members = [_member(1, "l20-30"), _member(2, "l120-130")]
	calls = {"n": 0}

	def synth(*args, **kwargs):
		calls["n"] += 1
		if calls["n"] == 2:
			raise RuntimeError("llm caído")
		return {"title": "t", "summary": "s"}

	with pytest.raises(RuntimeError):
		hub_parts.synthesize_parts(memory, "work_memories", "work:ses_mem011", members, synth, lambda c: ("neutral", 0.5), budget=500)
	# Solo se escribió la primera parte; la raíz no existe.
	assert len(memory.written) == 1
	assert memory.written[0]["metadata"]["hub_role"] == "part"


def test_parte_con_varias_hojas_sintetiza_una_vez(polaroids):
	memory = _memory()
	members = [_member(1, "l20-30", 200), _member(2, "l90-99", 200), _member(3, "l120-130", 200)]
	synth = MagicMock(return_value={"title": "t", "summary": "s"})
	hub_parts.synthesize_parts(memory, "work_memories", "work:ses_mem011", members, synth, lambda c: ("neutral", 0.5), budget=500)
	# 2 partes (la 1 junta dos hojas) + raíz = 3 llamadas
	assert synth.call_count == 3


def test_la_resintesis_honra_el_flag_de_polaroids(monkeypatch):
	"""`resynthesize_session` debe usar `synthesize_parts` con el flag ON.

	Sin esto escribía una raíz monolítica e ignoraba las partes; y si ya existían,
	re-parentaba todas las hojas a la raíz (aplanado, auditoría F-2).
	"""
	from red_pill.config import get_config
	from red_pill.metabolism import hub_synthesis

	cfg = get_config()
	monkeypatch.setattr(cfg, "SW_HUB_POLAROID_ENABLED", True, raising=False)
	monkeypatch.setattr(hub_synthesis, "_load_session_members", lambda *_a, **_k: [("m1", {"content": "a"}), ("m2", {"content": "b"})])
	calls = {"parts": 0, "mono": 0}

	def fake_parts(*_a, **_k):
		calls["parts"] += 1
		return "written"

	def fake_mono(*_a, **_k):
		calls["mono"] += 1
		return "written"

	monkeypatch.setattr(hub_parts, "synthesize_parts", fake_parts)
	monkeypatch.setattr(hub_synthesis, "_synthesize_one", fake_mono)

	assert hub_synthesis.resynthesize_session(MagicMock(), "work_memories", "work:ses_mem011") == "written"
	assert calls == {"parts": 1, "mono": 0}


def test_la_resintesis_con_el_flag_apagado_sigue_siendo_monolitica(monkeypatch):
	from red_pill.config import get_config
	from red_pill.metabolism import hub_synthesis

	cfg = get_config()
	monkeypatch.setattr(cfg, "SW_HUB_POLAROID_ENABLED", False, raising=False)
	monkeypatch.setattr(hub_synthesis, "_load_session_members", lambda *_a, **_k: [("m1", {"content": "a"}), ("m2", {"content": "b"})])
	calls = {"parts": 0, "mono": 0}
	monkeypatch.setattr(hub_parts, "synthesize_parts", lambda *_a, **_k: calls.__setitem__("parts", calls["parts"] + 1) or "written")
	monkeypatch.setattr(hub_synthesis, "_synthesize_one", lambda *_a, **_k: calls.__setitem__("mono", calls["mono"] + 1) or "written")

	assert hub_synthesis.resynthesize_session(MagicMock(), "work_memories", "work:ses_mem011") == "written"
	assert calls == {"parts": 0, "mono": 1}
