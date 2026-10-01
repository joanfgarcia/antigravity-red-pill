"""ARCH-001 paso B: the backend-specific pulse lives in a strategy, not the worker.

Fija el contrato de la separación:
- `IDEWorker` (core, neutro) ya NO expone los métodos Antigravity.
- `AntigravityPulseStrategy` (plugin) los expone todos.
- `NullPulseStrategy` satisface el protocolo `PulseStrategy`.
- `_build_strategy` devuelve la estrategia Antigravity (el import es el único
  punto que puede degradar a no-op).
"""

from __future__ import annotations

from red_pill.core.agent_worker import IDEWorker
from red_pill.core.pulse_strategy import NullPulseStrategy, PulseStrategy
from red_pill.plugins.antigravity_ide.pulse import AntigravityPulseStrategy

_ANTIGRAVITY_METHODS = [
	"check_for_replies",
	"check_minion_inbox_auto_inject",
	"process_cognitive_queue",
	"check_minion_inbox_auto_inject_agy",
	"process_cognitive_queue_agy",
	"get_trajectory_data",
	"get_all_trajectories",
]


def test_worker_no_longer_exposes_antigravity_methods():
	for method in _ANTIGRAVITY_METHODS:
		assert not hasattr(IDEWorker, method), f"IDEWorker still exposes {method}"


def test_antigravity_strategy_exposes_all_moved_methods():
	for method in _ANTIGRAVITY_METHODS:
		assert hasattr(AntigravityPulseStrategy, method), f"strategy missing {method}"


def test_null_strategy_satisfies_protocol():
	assert isinstance(NullPulseStrategy(), PulseStrategy)


def test_antigravity_strategy_satisfies_protocol():
	assert isinstance(AntigravityPulseStrategy(None, None), PulseStrategy)


def test_build_strategy_returns_antigravity():
	worker = IDEWorker.__new__(IDEWorker)
	worker.client = object()
	worker._bridge_minion = None
	strategy = worker._build_strategy()
	assert isinstance(strategy, AntigravityPulseStrategy)
