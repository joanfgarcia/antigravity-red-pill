"""NB-001 F5 / P8 — presupuesto por coste real por etapa en la selección nocturna.

Criterios del plan (PLAN-NB-001 §3 F5):
- P8.1 flag off → selección idéntica a hoy (mismos targets y orden).
- P8.2 flag on → el presupuesto de chars reproduce el caso nominal y evita el
	monstruo medido (distill en chars; annotate en unidades + notas esperadas).
- P8.3 anti-hambruna: una sesión que excede el presupuesto entra igual si es la
	primera.
- P8.4 la predicción de coste se expone para poder compararla con la duración real.
"""

from __future__ import annotations

from red_pill.memento.agentic.selection import (
	predict_session_cost,
	select_targets,
	work_unit_chars,
	work_unit_count,
)


def _make_session_dir(root, dir_rel: str, *, body_chars: int = 0, n_splits: int = 0, split_chars: int = 100) -> str:
	"""Crea una sesión Memento mínima con un cuerpo de `body_chars` chars y, si
	`n_splits > 0`, ese número de splits de `split_chars` chars cada uno."""
	memento = root / dir_rel / "memento"
	memento.mkdir(parents=True, exist_ok=True)
	(memento / "index.md").write_text("---\nsession_id: s\n---\n" + ("x" * body_chars), encoding="utf-8")
	for i in range(1, n_splits + 1):
		(memento / f"{i:03d}-mensajes-{i:04d}-{i:04d}.md").write_text(
			f"> [!ref] memento/index.md#l1-1\n{'y' * split_chars}", encoding="utf-8"
		)
	return dir_rel


class _RegistryFake:
	"""Solo lo que `select_targets` necesita: `dir` y `message_count` por sesión."""

	def __init__(self, entries):
		state: dict = {"registry": {}}
		for source, session_id, dir_rel, msgs in entries:
			state["registry"].setdefault(source, {})[session_id] = {"dir": dir_rel, "message_count": msgs}
		self.state = state


def _pending(*ids):
	return [("opencode", sid, reason) for sid, reason in ids]


# ── P8.1 — flag off → selección idéntica a hoy ──────────────────────────────


def test_p81_flag_off_ignora_el_coste_y_sigue_con_mensajes(tmp_path, monkeypatch):
	"""Con el flag OFF (default) la selección presupuesta por mensajes aunque se
	pase `phase` y haya un monstruo de chars en disco: mismo resultado que hoy."""
	import red_pill.config as cfg

	monkeypatch.setattr(cfg, "MEMENTO_NIGHT_COST_MODEL_ENABLED", False)
	root = tmp_path / "memento"
	_make_session_dir(root, "2026-10/opencode/monster", body_chars=500_000)
	_make_session_dir(root, "2026-10/opencode/small", body_chars=100)
	reg = _RegistryFake(
		[
			("opencode", "monster", "2026-10/opencode/monster", 5),
			("opencode", "small", "2026-10/opencode/small", 5),
		]
	)
	pending = _pending(("monster", "new"), ("small", "new"))

	# Con flag OFF, `phase=distill` + `root` no cambian nada: manda msg_limit (10 <= 3000).
	chosen = select_targets(pending, 10, msg_limit=3000, registry=reg, phase="distill", root=root)
	assert chosen == pending  # mismos targets, mismo orden


def test_p81_flag_off_sin_phase_es_exactamente_el_comportamiento_actual(tmp_path, monkeypatch):
	"""Sin flag y sin phase, `select_targets` es byte-idéntico al de siempre
	(dos presupuestos: sesiones + mensajes, el que se cruce primero)."""
	import red_pill.config as cfg

	monkeypatch.setattr(cfg, "MEMENTO_NIGHT_COST_MODEL_ENABLED", False)
	reg = _RegistryFake(
		[
			("opencode", "s0", "d0", 1000),
			("opencode", "s1", "d1", 1000),
			("opencode", "s2", "d2", 1000),
		]
	)
	pending = _pending(("s0", "new"), ("s1", "new"), ("s2", "new"))
	assert select_targets(pending, 10, msg_limit=2500, registry=reg) == [
		("opencode", "s0", "new"),
		("opencode", "s1", "new"),
	]


# ── P8.2 — flag on → presupuesto por coste real ─────────────────────────────


def test_p82_distill_chars_reproduce_nominal_y_evita_monstruo(tmp_path, monkeypatch):
	"""distill es O(chars): con un presupuesto de chars, la sesión nominal entra y
	el monstruo medido (centenares de miles de chars) se difiere."""
	import red_pill.config as cfg

	monkeypatch.setattr(cfg, "MEMENTO_NIGHT_COST_MODEL_ENABLED", True)
	monkeypatch.setattr(cfg, "MEMENTO_NIGHT_DISTILL_CHAR_LIMIT", 100_000)
	root = tmp_path / "memento"
	_make_session_dir(root, "2026-10/opencode/nominal", body_chars=5_000)
	_make_session_dir(root, "2026-10/opencode/monster", body_chars=500_000)
	reg = _RegistryFake(
		[
			("opencode", "nominal", "2026-10/opencode/nominal", 10),
			("opencode", "monster", "2026-10/opencode/monster", 2000),
		]
	)
	pending = _pending(("nominal", "new"), ("monster", "new"))
	chosen = select_targets(pending, 10, msg_limit=3000, registry=reg, phase="distill", root=root)
	assert chosen == [("opencode", "nominal", "new")]  # el monstruo no cabe en 100.000 chars


def test_p82_annotate_unidades_y_notas_esperadas(tmp_path, monkeypatch):
	"""annotate es O(unidades)×2 + O(notas): presupuesto en unidades y en notas
	esperadas. Una sesión pequeña entra; un monstruo de muchos splits se difiere."""
	import red_pill.config as cfg

	monkeypatch.setattr(cfg, "MEMENTO_NIGHT_COST_MODEL_ENABLED", True)
	monkeypatch.setattr(cfg, "MEMENTO_NIGHT_ANNOTATE_UNIT_LIMIT", 10)
	monkeypatch.setattr(cfg, "MEMENTO_NIGHT_ANNOTATE_NOTE_LIMIT", 1000)
	monkeypatch.setattr(cfg, "MEMENTO_NIGHT_ANNOTATE_NOTES_PER_UNIT", 8)
	root = tmp_path / "memento"
	_make_session_dir(root, "2026-10/opencode/small", n_splits=2, split_chars=100)
	_make_session_dir(root, "2026-10/opencode/monster", n_splits=65, split_chars=100)
	reg = _RegistryFake(
		[
			("opencode", "small", "2026-10/opencode/small", 10),
			("opencode", "monster", "2026-10/opencode/monster", 2000),
		]
	)
	pending = _pending(("small", "new"), ("monster", "new"))
	chosen = select_targets(pending, 10, msg_limit=3000, registry=reg, phase="annotate", root=root)
	assert chosen == [("opencode", "small", "new")]  # 65 splits > 10 unidades


def test_p82_notas_esperadas_acotan_antes_que_las_unidades(tmp_path, monkeypatch):
	"""El presupuesto de notas esperadas corta aunque las unidades quepan: `b` suma
	56 notas (7 splits × 8) y revienta el tope de 50 notas pese a que 1+7 < 100
	unidades. Demuestra el «(+ notas esperadas)» del contrato."""
	import red_pill.config as cfg

	monkeypatch.setattr(cfg, "MEMENTO_NIGHT_COST_MODEL_ENABLED", True)
	monkeypatch.setattr(cfg, "MEMENTO_NIGHT_ANNOTATE_UNIT_LIMIT", 100)
	monkeypatch.setattr(cfg, "MEMENTO_NIGHT_ANNOTATE_NOTE_LIMIT", 50)
	monkeypatch.setattr(cfg, "MEMENTO_NIGHT_ANNOTATE_NOTES_PER_UNIT", 8)
	root = tmp_path / "memento"
	_make_session_dir(root, "2026-10/opencode/a", n_splits=1, split_chars=10)
	_make_session_dir(root, "2026-10/opencode/b", n_splits=7, split_chars=10)
	reg = _RegistryFake(
		[
			("opencode", "a", "2026-10/opencode/a", 10),
			("opencode", "b", "2026-10/opencode/b", 10),
		]
	)
	pending = _pending(("a", "new"), ("b", "new"))
	chosen = select_targets(pending, 10, msg_limit=3000, registry=reg, phase="annotate", root=root)
	# `a` entra (8 notas). `b`: 8+56 = 64 notas > 50, aunque 1+7 = 8 unidades < 100.
	assert chosen == [("opencode", "a", "new")]


# ── P8.3 — anti-hambruna ────────────────────────────────────────────────────


def test_p83_anti_hambruna_el_monstruo_entra_si_es_el_primero(tmp_path, monkeypatch):
	"""Un ítem mayor que el presupuesto no puede quedarse fuera para siempre: si es
	la primera sesión (stale-first), entra aunque por sí sola exceda el presupuesto."""
	import red_pill.config as cfg

	monkeypatch.setattr(cfg, "MEMENTO_NIGHT_COST_MODEL_ENABLED", True)
	monkeypatch.setattr(cfg, "MEMENTO_NIGHT_DISTILL_CHAR_LIMIT", 100_000)
	root = tmp_path / "memento"
	_make_session_dir(root, "2026-10/opencode/monster", body_chars=500_000)
	_make_session_dir(root, "2026-10/opencode/nominal", body_chars=5_000)
	reg = _RegistryFake(
		[
			("opencode", "monster", "2026-10/opencode/monster", 2000),
			("opencode", "nominal", "2026-10/opencode/nominal", 10),
		]
	)
	# stale primero → el monstruo es la primera; entra y agota el presupuesto.
	pending = _pending(("monster", "stale"), ("nominal", "new"))
	chosen = select_targets(pending, 10, msg_limit=3000, registry=reg, phase="distill", root=root)
	assert chosen == [("opencode", "monster", "stale")]  # la nominal ya no cabe


def test_p83_anti_hambruna_annotate_primero_entra(tmp_path, monkeypatch):
	import red_pill.config as cfg

	monkeypatch.setattr(cfg, "MEMENTO_NIGHT_COST_MODEL_ENABLED", True)
	monkeypatch.setattr(cfg, "MEMENTO_NIGHT_ANNOTATE_UNIT_LIMIT", 10)
	monkeypatch.setattr(cfg, "MEMENTO_NIGHT_ANNOTATE_NOTE_LIMIT", 1000)
	monkeypatch.setattr(cfg, "MEMENTO_NIGHT_ANNOTATE_NOTES_PER_UNIT", 8)
	root = tmp_path / "memento"
	_make_session_dir(root, "2026-10/opencode/monster", n_splits=65, split_chars=100)
	reg = _RegistryFake([("opencode", "monster", "2026-10/opencode/monster", 2000)])
	pending = _pending(("monster", "stale"))
	chosen = select_targets(pending, 10, msg_limit=3000, registry=reg, phase="annotate", root=root)
	assert chosen == [("opencode", "monster", "stale")]


# ── P8.4 — predicción de coste expuesta ─────────────────────────────────────


def test_p84_predict_session_cost_expuesta(tmp_path, monkeypatch):
	"""La predicción se expone en la divisa de cada fase para compararla con la
	duración real: chars en distill; unidades + notas esperadas en annotate."""
	import red_pill.config as cfg

	monkeypatch.setattr(cfg, "MEMENTO_NIGHT_ANNOTATE_NOTES_PER_UNIT", 8)
	root = tmp_path / "memento"
	_make_session_dir(root, "2026-10/opencode/distill", body_chars=1234)
	_make_session_dir(root, "2026-10/opencode/annotate", n_splits=5, split_chars=100)

	assert predict_session_cost(root, "2026-10/opencode/distill", "distill") == {"chars": 1234}
	assert predict_session_cost(root, "2026-10/opencode/annotate", "annotate") == {"units": 5, "notes": 40}
	assert predict_session_cost(root, "2026-10/opencode/annotate", None) == {}
	assert predict_session_cost(root, "2026-10/opencode/annotate", "otra") == {}


def test_p84_helpers_de_work_unit(tmp_path):
	"""`work_unit_chars` / `work_unit_count` reflejan el contenido real del árbol."""
	root = tmp_path / "memento"
	_make_session_dir(root, "2026-10/opencode/splits", n_splits=3, split_chars=50)
	assert work_unit_count(root, "2026-10/opencode/splits") == 3
	assert work_unit_chars(root, "2026-10/opencode/splits") == 150

	# Sin splits, el index entero es UNA unidad de `body_chars` chars.
	_make_session_dir(root, "2026-10/opencode/idx", body_chars=77)
	assert work_unit_count(root, "2026-10/opencode/idx") == 1
	assert work_unit_chars(root, "2026-10/opencode/idx") == 77


def test_p84_predict_devuelve_vacio_sin_arbol_o_sin_fase():
	"""Sin root/dir o con fase desconocida la predicción es vacía, nunca revienta."""
	assert predict_session_cost(None, "d", "distill") == {}
	assert predict_session_cost(None, "", "annotate") == {}
