"""Entierro de señales del Janitor (contrato de ciclo de vida, 2026-11-12).

El contrato estático vive en `test_signal_lifecycle_contract.py` (todo dolor debe
tener su entierro en el código). Aquí se comprueba la CONDUCTA: que el entierro
ocurre cuando la causa cesa y que **no** ocurre cuando el dolor sigue vivo.

El caso que motivó esto: `memento_stale_distill` emitía un dolor silenciado y
nunca lo cerraba; la noche destiló las 16 sesiones y la señal seguía en el buzón.

Ojo al detalle que se cazó al escribirlo: un `else` colgado del `try` enterraría
justo después de emitir. Estos tests fijan el orden.
"""

from __future__ import annotations

import asyncio


class FakeJanitor:
	def __init__(self):
		self.logs: list[str] = []

	def log(self, message: str) -> None:
		self.logs.append(message)


class FakeMemory:
	def __init__(self, *, inject_ok: bool = True):
		self.injected: list[dict] = []
		self.evaporated: list[str] = []
		self.inject_ok = inject_ok

	def inject_signal(self, **kw):
		if not self.inject_ok:
			raise RuntimeError("qdrant caído")
		self.injected.append(kw)

	def evaporate_signals(self, name=None):
		self.evaporated.append(name)
		return 1


def _run(plugin, janitor, memory, **kwargs):
	return asyncio.run(plugin.execute(janitor, {"plugins": {plugin.name: {"enabled": True}}}, memory_manager=memory, **kwargs))


def test_sin_stale_entierra_el_dolor_silenciado(monkeypatch):
	"""El caso real: la noche destiló todo y la señal se quedó viva para siempre."""
	from red_pill.swarm.agents.janitor_plugins import memento_stale as mod

	monkeypatch.setattr("red_pill.memento.agentic.pending_agentic", lambda registry: [])
	burials: list = []
	monkeypatch.setattr(mod, "bury_signal", lambda *a, **k: burials.append((a, k)))
	stats = _run(mod.MementoStalePlugin(), FakeJanitor(), FakeMemory())
	assert stats == {"stale": 0}
	assert burials == [(("memento_stale_distill",), {"muted": True})], "sin stale debe enterrar (buzón)"


def test_con_stale_emite_y_no_entierra(monkeypatch):
	"""El orden importa: emitir y enterrar en el mismo pase borraría el dolor."""
	from red_pill.swarm.agents.janitor_plugins import memento_stale as mod

	monkeypatch.setattr("red_pill.memento.agentic.pending_agentic", lambda registry: [("opencode", "ses_1", "stale")])
	burials: list = []
	monkeypatch.setattr(mod, "bury_signal", lambda *a, **k: burials.append((a, k)))

	mem = FakeMemory()
	stats = _run(mod.MementoStalePlugin(), FakeJanitor(), mem)
	assert stats == {"stale": 1}
	assert mem.injected and mem.injected[0]["name"] == "memento_stale_distill"
	assert mem.injected[0]["muted"] is True
	assert not burials, "con la causa viva no se entierra"


def test_bury_signal_del_tablero_evapora(monkeypatch):
	"""`bury_signal` sin `muted` va a Qdrant (tablero); con `muted`, al buzón."""
	from red_pill.swarm.agents.janitor_plugins import base

	resolved: list[str] = []
	monkeypatch.setattr("red_pill.core.inbox.MinionInbox.resolve_report", lambda self, event_id: resolved.append(event_id))

	mem = FakeMemory()
	base.bury_signal("queue_stuck_tasks", memory_manager=mem)
	assert mem.evaporated == ["queue_stuck_tasks"]

	base.bury_signal("memento_stale_distill", muted=True)
	assert resolved == ["signal_memento_stale_distill"]


def test_bury_signal_nunca_lanza(monkeypatch):
	"""Un entierro que no pudo ser no tumba al Janitor."""
	from red_pill.swarm.agents.janitor_plugins import base

	class Broken:
		def evaporate_signals(self, name=None):
			raise RuntimeError("qdrant caído")

	base.bury_signal("queue_stuck_tasks", memory_manager=Broken())  # no lanza


def test_queue_hygiene_entierra_cuando_no_hay_colgados(monkeypatch):
	"""Segundo caso del tablero: el estado cesa y el aviso muere."""
	from red_pill.cognitive.queue_manager import CognitiveQueueManager
	from red_pill.swarm.agents.janitor_plugins import queue_hygiene as mod

	class FakeCQ:
		def purge_hygiene(self, **kw):
			return {"completed_purged": 0, "frustrated_purged": 0, "stuck_marked": 0}

	monkeypatch.setattr("red_pill.cognitive.queue_manager.CognitiveQueueManager", FakeCQ)
	burials: list = []
	monkeypatch.setattr(mod, "bury_signal", lambda *a, **k: burials.append((a, k)))

	mem = FakeMemory()
	stats = _run(mod.QueueHygienePlugin(), FakeJanitor(), mem)
	assert stats["stuck_marked"] == 0
	assert burials and burials[0][0] == ("queue_stuck_tasks",)
	assert not mem.injected
	assert CognitiveQueueManager  # importado arriba: el fake sustituye al real
