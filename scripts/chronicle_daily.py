#!/usr/bin/env python3
"""
chronicle_daily.py — Autonomous Chronicle Ingestion Pipeline (Phase 2)

Orquestador agnóstico de fuentes: descubre los ChronicleSourcePlugin habilitados
(antigravity, claude_code, opencode...), detecta deltas de step_count por fuente
y archiva las conversaciones normalizadas en el Bünker (archive_memories).
El registro (`chronicle_daily_registry.json`) guarda step_counts anidados por
fuente para prevenir ingestas duplicadas o redundantes.

Usage:
	uv run python scripts/chronicle_daily.py              # default: process updates
	uv run python scripts/chronicle_daily.py --all       # force check all
	uv run python scripts/chronicle_daily.py --dry-run   # show what would be processed
"""

import argparse
import json
import logging
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

logging.basicConfig(
	level=logging.INFO,
	format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("chronicle_daily")

# ── Paths ────────────────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from red_pill.core.paths import get_data_dir  # noqa: E402

PROCESSED_LOG = get_data_dir() / "chronicle_daily_registry.json"
WORK_DIR = Path("/tmp/chronicle_today")
SCRIPTS_DIR = Path(__file__).parent


def _default_state() -> dict:
	return {"processed": {}, "registry": {}, "last_run": None, "stats": {"total_ingested": 0, "total_sessions": 0}}


def _migrate_flat_registry(state: dict) -> bool:
	"""Formato plano pre-multi-fuente → anidado por fuente, sin perder lo sembrado.

	El registro histórico era `{cid: step_count}` y solo conocía Antigravity; el
	multi-fuente lo anida como `{source: {cid: step_count}}`. Sin esta migración,
	el primer arranque daría el histórico de Antigravity por desconocido y lo
	re-ingeriría entero (el timeout que ya nos abatió la madrugada del 29 jul).
	"""
	registry = state.get("registry", {})
	if not registry or all(isinstance(v, dict) for v in registry.values()):
		return False

	state["registry"] = {"antigravity": registry}
	processed = state.get("processed", {})
	if processed and not all(isinstance(v, dict) for v in processed.values()):
		state["processed"] = {"antigravity": processed}
	logger.info(f"Migrated flat registry to per-source format ({len(registry)} antigravity sessions preserved).")
	return True


def _load_processed() -> dict:
	"""Load the registry of processed session IDs and their step counts (per source)."""
	state = _default_state()
	if PROCESSED_LOG.exists():
		try:
			loaded = json.loads(PROCESSED_LOG.read_text())
			if isinstance(loaded, dict):
				state.update(loaded)
		except Exception as e:
			logger.warning(f"Could not parse registry, starting fresh: {e}")

	for key, default in _default_state().items():
		state.setdefault(key, default)

	if _migrate_flat_registry(state):
		_save_processed(state)
	return state


def _save_processed(state: dict) -> None:
	PROCESSED_LOG.parent.mkdir(parents=True, exist_ok=True)
	PROCESSED_LOG.write_text(json.dumps(state, indent=2))


def _seed_new_sources(state: dict, plugins: list) -> bool:
	"""Primer contacto con una fuente: siembra su histórico como ya procesado.

	Evita la ingesta masiva inicial (timeouts de la cota del job) — a partir de
	la siembra solo entran deltas; `--all` fuerza el reproceso completo.
	"""
	seeded = False
	now = datetime.now().isoformat()
	for plugin in plugins:
		if plugin.name in state["registry"]:
			continue
		discovered = plugin.discover()
		state["registry"][plugin.name] = {cid: step_count for cid, step_count in discovered}
		state["processed"][plugin.name] = {cid: now for cid, _ in discovered}
		state["stats"]["total_sessions"] += len(discovered)
		logger.info(f"Auto-seeded source '{plugin.name}' with {len(discovered)} existing sessions.")
		seeded = True
	return seeded


def _find_pending(state: dict, plugins: list, force_all: bool = False) -> list:
	"""[(plugin, conversation_id, step_count)] de conversaciones que necesitan ingesta."""
	pending = []
	for plugin in plugins:
		source_registry = state["registry"].setdefault(plugin.name, {})
		try:
			discovered = plugin.discover()
		except Exception as e:
			logger.error(f"Source '{plugin.name}' discovery failed: {e}")
			continue

		for cid, step_count in discovered:
			# Only ingest if the conversation has more steps than what we last recorded
			if force_all or step_count > source_registry.get(cid, -1):
				pending.append((plugin, cid, step_count))
	return pending


def _run(cmd: list[str], step: str) -> bool:
	"""Run a subprocess step, return True on success."""
	logger.info(f"[{step}] Running: {' '.join(cmd)}")
	result = subprocess.run(cmd, capture_output=False)
	if result.returncode != 0:
		logger.error(f"[{step}] FAILED (exit {result.returncode})")
		return False
	logger.info(f"[{step}] Done ✓")
	return True


def _llm_available() -> bool:
	"""Quick check if the local LLM endpoint responds."""
	import os
	import urllib.request

	url = os.environ.get("MLX_LM_URL", "http://127.0.0.1:8760/v1/chat/completions")
	base = url.rsplit("/", 2)[0]
	try:
		urllib.request.urlopen(base, timeout=3)
		return True
	except Exception:
		return False


def main() -> None:
	parser = argparse.ArgumentParser(description="Autonomous Chronicle Ingestion Pipeline")
	parser.add_argument("--all", action="store_true", help="Process all unprocessed conversations")
	parser.add_argument("--dry-run", action="store_true", help="Show what would be processed without doing anything")
	args = parser.parse_args()

	from red_pill.chronicle_sources.base import discover_source_plugins

	plugins = discover_source_plugins()
	if not plugins:
		logger.error("No chronicle source plugins enabled (CHRONICLE_ARCHIVE_SOURCES). Nothing to do.")
		return
	logger.info(f"Active sources: {', '.join(p.name for p in plugins)}")

	# ── Load state ────────────────────────────────────────────────────────────
	state = _load_processed()
	if _seed_new_sources(state, plugins) and not args.dry_run:
		_save_processed(state)

	pending = _find_pending(state, plugins, force_all=args.all)

	if not pending:
		logger.info("No pending conversations to process. Registry is up to date.")
		if not args.dry_run:
			state["last_run"] = datetime.now().isoformat()
			_save_processed(state)
		return

	logger.info(f"Found {len(pending)} pending conversation(s) requiring ingestion.")
	for plugin, cid, step_count in pending:
		logger.info(f"  → [{plugin.name}] {cid} (Steps: {step_count})")

	if args.dry_run:
		logger.info("[DRY RUN] No changes made.")
		return

	# ── Prepare work dir ──────────────────────────────────────────────────────
	if WORK_DIR.exists():
		shutil.rmtree(WORK_DIR)
	WORK_DIR.mkdir(parents=True)

	try:
		uv = ["uv", "run", "python"]

		# ── Normalize pending conversations into isolated WORK_DIR ───────────
		# Cada fuente entrega mensajes ya normalizados; el fichero lleva el
		# session_id namespaced y el originator para que el ingester los persista.
		completed = []  # solo lo cargado con éxito entra luego al registro
		for plugin, cid, step_count in pending:
			try:
				messages = plugin.load(cid)
			except Exception as e:
				logger.warning(f"[{plugin.name}] Could not load {cid}, will retry next cycle: {e}")
				continue

			if messages:
				payload = {"session_id": plugin.qualify(cid), "originator": plugin.name, "messages": messages}
				work_file = WORK_DIR / f"{plugin.name}__{cid}.json"
				work_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
			# Sin mensajes útiles también se registra: no reintentar cada noche
			completed.append((plugin, cid, step_count))

		if not any(WORK_DIR.iterdir()):
			logger.info("Pending conversations yielded no ingestable messages.")
		else:
			# ── Step 1: Ingest ────────────────────────────────────────────────
			ingest_ok = _run(uv + [str(SCRIPTS_DIR / "antigravity_ingest.py"), "--dir", str(WORK_DIR)], "INGEST")
			if not ingest_ok:
				logger.error("Ingest failed. Aborting pipeline.")
				return

			# ── Step 2: Distill (Samantha) ───────────────────────────────────
			if _llm_available():
				_run(uv + [str(SCRIPTS_DIR / "chronicle_distill.py")], "DISTILL")
			else:
				logger.warning("[DISTILL] Local LLM not available. Skipping Samantha distillation — will retry on next cycle.")

			# ── Step 3: Refine ────────────────────────────────────────────────
			_run(uv + [str(SCRIPTS_DIR / "chronicle_refine.py")], "REFINE")

		# ── Mark as processed in Registry ─────────────────────────────────────
		now = datetime.now().isoformat()
		for plugin, cid, step_count in completed:
			state["registry"].setdefault(plugin.name, {})[cid] = step_count
			state["processed"].setdefault(plugin.name, {})[cid] = now

		state["last_run"] = now
		state["stats"]["total_sessions"] += len(completed)
		_save_processed(state)
		logger.info(f"Chronicle pipeline complete. {len(completed)} session(s) updated in the registry.")

	finally:
		if WORK_DIR.exists():
			shutil.rmtree(WORK_DIR)


if __name__ == "__main__":
	main()
