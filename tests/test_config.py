import importlib

import pytest


def test_invalid_decay_strategy(monkeypatch):
	"""Ensures ValueError is raised for invalid DECAY_STRATEGY."""
	monkeypatch.setenv("DECAY_STRATEGY", "quantum")
	import red_pill.config as config

	with pytest.raises(ValueError, match="Invalid DECAY_STRATEGY: quantum"):
		importlib.reload(config)

	# Restore to default to prevent breaking other tests
	monkeypatch.setenv("DECAY_STRATEGY", "linear")
	importlib.reload(config)
