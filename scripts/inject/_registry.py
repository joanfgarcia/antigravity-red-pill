"""Auto-discovery engine for IDE injection adapters.

Scans ``scripts/inject/<ide>/detect.py`` at runtime.  Each adapter is a
Python module with two entry-points:

    detect(workspace: str | None) -> bool
        Return True if this IDE is present on the host.

    inject(args: argparse.Namespace) -> int
        Execute the injection.  Return the number of files modified.

New IDE support = create a directory with detect.py + inject.py.  Zero
changes to install_neo.sh or upgrade.sh.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("inject_registry")

INJECT_ROOT = Path(__file__).parent


@dataclass
class IDEAdapter:
	name: str
	detect_mod: object
	inject_mod: object


def _load_module(name: str, path: Path) -> object:
	"""Load a Python module from an arbitrary path (no __init__ needed)."""
	spec = importlib.util.spec_from_file_location(name, str(path))
	mod = importlib.util.module_from_spec(spec)
	sys.modules[f"inject_{name}"] = mod
	spec.loader.exec_module(mod)
	return mod


def discover_adapters() -> list[IDEAdapter]:
	"""Scan inject/<ide>/ directories and return adapters with detect.py + inject.py."""
	adapters = []
	for entry in sorted(INJECT_ROOT.iterdir()):
		if not entry.is_dir() or entry.name.startswith("_") or entry.name == "shared":
			continue
		detect_path = entry / "detect.py"
		inject_path = entry / "inject.py"
		if not detect_path.exists() or not inject_path.exists():
			continue
		try:
			detect_mod = _load_module(f"{entry.name}_detect", detect_path)
			inject_mod = _load_module(f"{entry.name}_inject", inject_path)
			adapters.append(IDEAdapter(entry.name, detect_mod, inject_mod))
		except Exception as exc:
			logger.warning(f"Failed to load adapter '{entry.name}': {exc}")
	return adapters


def detect_present(workspace: str | None = None) -> list[IDEAdapter]:
	"""Return only adapters whose detect() returns True."""
	return [a for a in discover_adapters() if a.detect_mod.detect(workspace)]


def inject_all(args, adapters: list[IDEAdapter] | None = None) -> int:
	"""Run inject() on all (or specified) adapters. Total files modified."""
	if adapters is None:
		adapters = detect_present(getattr(args, "workspace", None))
	total = 0
	for adapter in adapters:
		logger.info(f"--- {adapter.name} ---")
		try:
			total += adapter.inject_mod.inject(args)
		except Exception as exc:
			logger.error(f"Adapter '{adapter.name}' failed: {exc}")
	return total
