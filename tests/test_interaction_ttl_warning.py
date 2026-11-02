"""Aviso previo a la purga del buffer (2026-11-02).

Anoche el janitor borró 6 turnos sin renderizar y solo lo dijo **después**, con
un contador. Este test fija lo contrario: el aviso llega **antes** (dentro de la
ventana de aviso), con desglose por origen, y se apaga cuando ya no hay riesgo.
"""

import asyncio
import time
from unittest.mock import MagicMock

import pytest
from qdrant_client.http import models

from red_pill.swarm.agents.janitor_plugins.interaction_ttl import InteractionTTLPlugin


@pytest.fixture
def config(monkeypatch):
	import red_pill.config as cfg

	monkeypatch.setattr(cfg, "SW_PURGE_GATE_ENABLED", True, raising=False)
	monkeypatch.setattr(cfg, "INTERACTION_MEMORIES_TTL_HOURS", 72, raising=False)
	monkeypatch.setattr(cfg, "PRE_HEATING_LOOKBACK_HOURS", 48, raising=False)
	monkeypatch.setattr(cfg, "INTERACTION_MAX_AGE_DAYS", 30, raising=False)
	monkeypatch.setattr(cfg, "INTERACTION_WARN_BEFORE_DAYS", 7, raising=False)
	return cfg


@pytest.fixture
def registry(monkeypatch):
	"""Memento con una sola sesión rendereada: `ses_render`."""

	class FakeRegistry:
		def __init__(self, path=None):
			self.state = {"registry": {"opencode": {"ses_render": {"ok": True}}}}

	monkeypatch.setattr("red_pill.memento.registry.MementoRegistry", FakeRegistry)
	return FakeRegistry


def _seed(mm, days_old, session_id=None, originator="unknown"):
	mm.storage.ensure_collection("interaction_memories")
	mm.storage.ensure_collection("signal_memories")
	ts = time.time() - days_old * 86400
	mm.client.upsert(
		collection_name="interaction_memories",
		points=[
			models.PointStruct(
				id=abs(hash((days_old, session_id, originator))) % (2**63),
				vector=[0.0] * mm.cfg.VECTOR_SIZE,
				payload={
					"timestamp": ts,
					"metadata": {"session_id": session_id, "originator": originator},
				},
			)
		],
	)


def _run(mm, tmp_path):
	janitor = MagicMock()
	return asyncio.run(
		InteractionTTLPlugin().execute(janitor, {}, memory_manager=mm, registry_path=str(tmp_path / "reg.json"))
	), janitor


class TestAvisoPrevio:
	def test_avisa_de_lo_que_va_a_caducar(self, memory_manager, config, registry, tmp_path):
		_seed(memory_manager, 28, session_id=None, originator="unknown")
		_run(memory_manager, tmp_path)
		assert memory_manager.has_signal("interaction_expiring_soon") is True

	def test_el_mensaje_desglosa_el_origen(self, memory_manager, config, registry, tmp_path):
		_seed(memory_manager, 28, session_id=None, originator="unknown")
		_seed(memory_manager, 28, session_id=None, originator="pi:ses_abc")
		_run(memory_manager, tmp_path)
		content = None
		pts, _ = memory_manager.client.scroll("signal_memories", limit=10, with_payload=True)
		for p in pts:
			if (p.payload or {}).get("name") == "interaction_expiring_soon":
				content = p.payload.get("content")
		assert content and "pi 1" in content and "unknown 1" in content

	def test_no_avisa_de_lo_ya_renderizado(self, memory_manager, config, registry, tmp_path):
		_seed(memory_manager, 28, session_id="ses_render", originator="opencode")
		_run(memory_manager, tmp_path)
		assert memory_manager.has_signal("interaction_expiring_soon") is False

	def test_no_avisa_de_lo_reciente(self, memory_manager, config, registry, tmp_path):
		_seed(memory_manager, 1, session_id=None, originator="unknown")
		_run(memory_manager, tmp_path)
		assert memory_manager.has_signal("interaction_expiring_soon") is False

	def test_apaga_el_aviso_cuando_ya_no_hay_riesgo(self, memory_manager, config, registry, tmp_path):
		_seed(memory_manager, 28, session_id=None, originator="unknown")
		_run(memory_manager, tmp_path)
		assert memory_manager.has_signal("interaction_expiring_soon") is True
		# Sin nada a punto de caducar, la señal se evapora en la siguiente pasada.
		points, _ = memory_manager.client.scroll("interaction_memories", limit=100, with_payload=True)
		memory_manager.client.delete(
			"interaction_memories",
			points_selector=models.PointIdsList(points=[p.id for p in points]),
		)
		_run(memory_manager, tmp_path)
		assert memory_manager.has_signal("interaction_expiring_soon") is False
