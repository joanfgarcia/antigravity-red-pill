"""Ramas pendientes de aterrizar: la medición llega al Operador sin preguntar.

HANDOFF-001 (A+C, decidido el 2026-11-12). El hecho: ese día el Operador tuvo
que preguntar **cuatro veces** qué había dejado un despertar en una rama. Ni el
log ni el acta estaban mal — el acta habla a las otras almas y él tiene que ir a
leerla.

Contrato de esta pieza:

- El dato lo **mide** `scripts/branch_landing_audit.py` (contenido, no SHA) y lo
  deja en `state/pending_branches.json`.
- `open_loops_line` lo lee sin correr git y lo pinta en la línea `OPEN LOOPS: …`
  que el Operador ve al abrir cualquier sesión.
- La señal `branch_pending_landing` se emite medida y **se entierra a cero**
  (contrato de ciclo de vida, mismo día).
- Un dato viejo no se usa: silencio antes que una cifra de ayer.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "branch_landing_audit.py"


@pytest.fixture()
def audit_module():
	spec = importlib.util.spec_from_file_location("branch_landing_audit", SCRIPT)
	module = importlib.util.module_from_spec(spec)
	assert spec.loader is not None
	# Sin registrar el módulo, un `@dataclass` del script no resuelve su namespace.
	sys.modules["branch_landing_audit"] = module
	spec.loader.exec_module(module)
	return module


class FakeMemory:
	def __init__(self):
		self.injected: list[dict] = []
		self.evaporated: list[str] = []

	def inject_signal(self, **kw):
		self.injected.append(kw)

	def evaporate_signals(self, name=None):
		self.evaporated.append(name)
		return 1


def _state(tmp_path: Path, pending: int, age_s: float = 0.0) -> Path:
	path = tmp_path / "pending_branches.json"
	path.write_text(
		json.dumps({"generated_at": time.time() - age_s, "target": "next", "pending": pending, "branches": []}),
		encoding="utf-8",
	)
	return path


def _line(monkeypatch, tmp_path) -> str:
	from red_pill.core import open_loops

	monkeypatch.setattr("red_pill.core.paths.get_state_dir", lambda: tmp_path)
	monkeypatch.setattr(open_loops, "_cache", {})
	return open_loops.open_loops_line(desk=tmp_path / "desk", workspace=tmp_path)


def test_la_linea_anuncia_las_ramas_pendientes(monkeypatch, tmp_path):
	_state(tmp_path, 2)
	assert "2 rama(s) pendiente(s) de aterrizar" in _line(monkeypatch, tmp_path)


def test_sin_fichero_no_hay_ruido(monkeypatch, tmp_path):
	assert "rama(s)" not in _line(monkeypatch, tmp_path)


def test_a_cero_no_anuncia_nada(monkeypatch, tmp_path):
	_state(tmp_path, 0)
	assert "rama(s)" not in _line(monkeypatch, tmp_path)


def test_un_dato_de_ayer_no_se_usa(monkeypatch, tmp_path):
	"""Mejor silencio que una cifra vieja: el repo pudo cambiar desde entonces."""
	_state(tmp_path, 3, age_s=2 * 86400)
	assert "rama(s)" not in _line(monkeypatch, tmp_path)


def test_publish_escribe_el_estado_y_senala(monkeypatch, tmp_path, audit_module):
	mem = FakeMemory()
	monkeypatch.setattr("red_pill.core.paths.get_state_dir", lambda: tmp_path)
	monkeypatch.setattr("red_pill.memory.MemoryManager", lambda: mem)
	payload = {
		"target": "next",
		"repos": [
			{
				"repo": "/tmp/repo",
				"verdicts": [
					{"branch": "awaken/x", "tip": "abc1234", "status": "clean", "evidence": "merge_clean"},
					{"branch": "main", "tip": "def5678", "status": "merged", "evidence": "ancestor"},
				],
			}
		],
	}
	path = audit_module.publish_pending_state(payload, 1)
	state = json.loads(Path(path).read_text(encoding="utf-8"))
	assert state["pending"] == 1
	assert [b["branch"] for b in state["branches"]] == ["awaken/x"], "solo lo pendiente, no lo ya aterrizado"
	assert mem.injected and mem.injected[0]["name"] == "branch_pending_landing"
	assert "awaken/x@abc1234" in mem.injected[0]["message"]
	assert not mem.evaporated


def test_publish_a_cero_entierra_la_senal(monkeypatch, tmp_path, audit_module):
	"""Contrato de ciclo de vida: sin ramas pendientes, el aviso muere."""
	mem = FakeMemory()
	monkeypatch.setattr("red_pill.core.paths.get_state_dir", lambda: tmp_path)
	monkeypatch.setattr("red_pill.memory.MemoryManager", lambda: mem)
	audit_module.publish_pending_state({"target": "next", "repos": []}, 0)
	assert mem.evaporated == ["branch_pending_landing"]
	assert not mem.injected
