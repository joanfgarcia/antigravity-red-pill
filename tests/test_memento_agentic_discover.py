"""Fan-out por sesión del pase Memento (RFC-JOBDAG-002).

El discover debe espejar el DELTA nocturno (stale primero + tope), y `chronicle.yaml`
debe declarar el fan-out por sesión (una hoja por sesión → progreso visible).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
DISCOVER = REPO / "scripts" / "list_memento_agentic_pending.py"


def _load_discover():
	spec = importlib.util.spec_from_file_location("list_memento_agentic_pending", DISCOVER)
	mod = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(mod)
	return mod


def test_discover_stale_primero_y_tope():
	m = _load_discover()
	pending = [("opencode", "a", "new"), ("opencode", "b", "stale"), ("opencode", "c", "new")]
	assert m.select_targets(pending, 2) == ["opencode:b", "opencode:a"]
	assert m.select_targets(pending, 10) == ["opencode:b", "opencode:a", "opencode:c"]


def test_discover_tope_limita():
	m = _load_discover()
	pending = [("s", f"s{i}", "new") for i in range(5)]
	assert len(m.select_targets(pending, 3)) == 3


class _RegistryFake:
	"""Solo lo que `select_targets` necesita: message_count por sesión."""

	def __init__(self, msgs):
		self.state = {"registry": {"opencode": {f"s{i}": {"message_count": n} for i, n in enumerate(msgs)}}}


def test_el_tope_por_mensajes_manda_sobre_el_de_sesiones():
	m = _load_discover()
	reg = _RegistryFake([1000, 1000, 1000])
	pending = [("opencode", f"s{i}", "new") for i in range(3)]

	# 2.500 de presupuesto: entran 2 sesiones (2.000), la tercera rompería.
	assert m.select_targets(pending, 10, msg_limit=2500, registry=reg) == ["opencode:s0", "opencode:s1"]


def test_el_tope_por_sesiones_manda_cuando_son_pequeñas():
	m = _load_discover()
	reg = _RegistryFake([10, 10, 10, 10, 10])
	pending = [("opencode", f"s{i}", "new") for i in range(5)]

	assert len(m.select_targets(pending, 3, msg_limit=10_000, registry=reg)) == 3


def test_una_sesion_mas_grande_que_el_presupuesto_entra_igual():
	"""Si no, un ítem enorme no se procesaría nunca (hambruna)."""
	m = _load_discover()
	reg = _RegistryFake([9000, 100])
	pending = [("opencode", "s0", "stale"), ("opencode", "s1", "new")]

	assert m.select_targets(pending, 10, msg_limit=3000, registry=reg) == ["opencode:s0"]


def test_sin_registro_el_tope_por_mensajes_no_aplica():
	m = _load_discover()
	pending = [("opencode", f"s{i}", "new") for i in range(3)]
	assert len(m.select_targets(pending, 10, msg_limit=1)) == 3


def test_limit_cero_apaga_los_dos_presupuestos():
	"""`0` = sin tope (rescates manuales) — antes solo apagaba el de sesiones."""
	m = _load_discover()
	reg = _RegistryFake([2000, 2000])
	pending = [("opencode", f"s{i}", "new") for i in range(2)]

	assert m.select_targets(pending, 0, msg_limit=3000, registry=reg) == ["opencode:s0", "opencode:s1"]


def _load_script(path: Path):
	spec = importlib.util.spec_from_file_location(path.stem, path)
	mod = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(mod)
	return mod


def test_el_pase_clasico_y_el_discover_comparten_politica():
	"""El tope por mensajes nació en el `discover`; el pase clásico sin `--target`
	seguía con el tope de sesiones solo. Dos puertas, un presupuesto invisible."""
	from red_pill.memento.agentic import selection

	m = _load_discover()
	magentic = _load_script(REPO / "scripts" / "memento_agentic.py")

	# Una sola implementación: si alguien vuelve a duplicarla, esto cae.
	assert magentic.select_targets is selection.select_targets

	reg = _RegistryFake([1000, 1000, 1000])
	pending = [("opencode", f"s{i}", "new") for i in range(3)]
	assert magentic.select_targets(pending, 10, msg_limit=2500, registry=reg) == [
		("opencode", "s0", "new"),
		("opencode", "s1", "new"),
	]
	assert m.select_targets(pending, 10, msg_limit=2500, registry=reg) == ["opencode:s0", "opencode:s1"]


def test_chronicle_usa_fanout_por_sesion():
	cfg = yaml.safe_load((REPO / "configs" / "jobs" / "chronicle.yaml").read_text(encoding="utf-8"))
	stages = cfg["manifest"]["stages"]
	ids = [s["id"] for s in stages]
	assert "discover" in ids and "memento" in ids
	# 2026-10-30: el pase va POR FASES (una corrida de modelo por fase), no
	# intercalado por sesión — intercalado cuesta dos cambios de modelo por
	# sesión. Ambas fases comparten la lista congelada de `discover`.
	md = next(s for s in stages if s["id"] == "memento-distill")
	ma = next(s for s in stages if s["id"] == "memento-annotate")
	for etapa, fase, tarea in ((md, "distill", "distill"), (ma, "annotate", "annotate")):
		assert etapa["fan_out_from"] == "discover"
		assert f"--phase {fase} --target {{{{item}}}}" in etapa["command"]
		assert etapa["llm"]["task"] == tarea
	assert "memento-agentic" not in ids  # la etapa intercalada se retiró
	# el discover depende del migrate; el fanout del discover
	assert next(s for s in stages if s["id"] == "discover")["depends_on"] == ["memento"]
	assert md["depends_on"] == ["discover"]
	# serialización: todas las polaroids antes de empezar las notas
	assert ma["depends_on"] == ["memento-distill"]
