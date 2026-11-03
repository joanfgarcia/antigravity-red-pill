"""Contador del backlog de Memento (2026-11-03).

El tope nocturno deja sesiones fuera; sin un contador visible, el resto es
invisible ("todo al día" con N esperando). El cierre del chronicle emite
`memento_backlog` con el número real (acumulativo) y la evapora a 0. La clase
`sed` le da la ley de edad: escala y su acantilado son los 30 d del buffer.
"""

from __future__ import annotations

import importlib.util
import time
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "report_memento_backlog.py"


def _load_script():
	spec = importlib.util.spec_from_file_location("report_memento_backlog", SCRIPT)
	mod = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(mod)
	return mod


class _FakeMemory:
	def __init__(self):
		self.injected = []
		self.evaporated = []

	def inject_signal(self, **kw):
		self.injected.append(kw)

	def evaporate_signals(self, name):
		self.evaporated.append(name)


class _FakeRegistry:
	def __init__(self, entries):
		self.state = {"registry": entries}


def test_backlog_cero_evapora_la_senal():
	mod = _load_script()
	mem = _FakeMemory()

	out = mod.report({"pending": 0}, cap=30, memory=mem)

	assert out["signal"] == "evaporated"
	assert mem.evaporated == ["memento_backlog"]
	assert mem.injected == []


def test_backlog_emite_el_contador_con_tope_y_edad():
	mod = _load_script()
	mem = _FakeMemory()

	out = mod.report({"pending": 7, "oldest_days": 2.5}, cap=30, msg_cap=3000, memory=mem)

	assert out["signal"] == "injected"
	(call,) = mem.injected
	assert call["name"] == "memento_backlog"
	assert call["intensity"] == 4.0
	assert "7 sesión" in call["message"]
	assert "30 sesiones" in call["message"] and "3000 mensajes" in call["message"]
	assert "2.5 d" in call["message"]
	assert "acumulativo" in call["message"]


def test_dry_run_no_toca_qdrant():
	mod = _load_script()
	mem = _FakeMemory()

	out = mod.report({"pending": 7}, cap=30, memory=mem, dry_run=True)

	assert out["signal"] == "none"
	assert mem.injected == [] and mem.evaporated == []


def test_compute_cuenta_y_da_la_edad_del_mas_antiguo(monkeypatch):
	mod = _load_script()
	viejo = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 3 * 86400))
	nuevo = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 3600))
	reg = _FakeRegistry(
		{
			"opencode": {
				"opencode:ses_vieja": {"created_at": viejo},
				"opencode:ses_nueva": {"created_at": nuevo},
			}
		}
	)
	monkeypatch.setattr(
		"red_pill.memento.agentic.pending_agentic",
		lambda *a, **kw: [("opencode", "opencode:ses_vieja", "missing"), ("opencode", "opencode:ses_nueva", "missing")],
	)

	out = mod.compute(reg, REPO)

	assert out["pending"] == 2
	assert 2.9 <= out["oldest_days"] <= 3.1


def test_la_senal_tiene_clase_sed_y_acantilado_de_30_dias():
	from red_pill.metabolism.signal_profiles import load_catalog

	catalogo = load_catalog()
	clase = catalogo.class_for("memento_backlog")
	assert clase.name == "sed"
	assert clase.cliff_hours == 720.0
	assert catalogo.stage_for(10.0) == "system_failure"


def test_el_chronicle_cierra_con_el_contador():
	recipe = yaml.safe_load((REPO / "configs" / "jobs" / "chronicle.yaml").read_text())
	stages = recipe["manifest"]["stages"]
	backlog = next(s for s in stages if s["id"] == "memento-backlog")
	assert backlog["command"].endswith("scripts/report_memento_backlog.py")
	assert backlog["depends_on"] == ["memento-annotate"]
	assert backlog["on_fail"] == "warn"
