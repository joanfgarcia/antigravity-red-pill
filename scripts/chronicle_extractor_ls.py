#!/usr/bin/env python3
"""
Chronicle Extractor (Phase 1)
Safely extracts conversations from the IDE LanguageServer to the unencrypted storage.
Idempotent: Only extracts if the .pb file is newer than the .json file.
"""

import json
import logging
import time
from pathlib import Path

from red_pill.core.paths import get_antigravity_conversations_dir, get_state_dir, get_unencrypted_conversations_dir

# Configurar logging básico (ligero para cron)
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("Extractor")

DEBT_STATE_FILE = "chronicle_extractor_debt.json"
DEBT_COOLDOWN_S = 24 * 3600
DEBT_PURGE_WARN_DAYS = 21.0
# Por encima de este umbral el buffer de interacción ya purgó esos turnos: la
# conversación solo se recuperaría abriendo el IDE con esas trazas aún indexadas.
DEBT_RECOVERABLE_DAYS = 30.0

try:
	from red_pill.utils.antigravity_history.api import get_all_trajectories_merged, get_trajectory_steps
	from red_pill.utils.antigravity_history.discovery import discover_language_servers, find_all_endpoints
	from red_pill.utils.antigravity_history.formatters import build_conversation_record
	from red_pill.utils.antigravity_history.parser import FieldLevel, parse_steps
except ImportError:
	logger.error("Faltan dependencias. Ejecuta este script desde el entorno virtual de red_pill.")
	exit(1)


def _evaporate_debt_signal() -> None:
	"""Camino inverso: si ya no hay deuda recuperable, la señal no puede seguir viva.

	Es el fallo que el despertar de las 12:00 documentó como `SIG-001` (dolor
	huérfano): la señal de ayer sobrevive a su causa porque nadie la entierra.
	Aquí se entierra desde quien la emite.
	"""
	try:
		from red_pill.memory import MemoryManager

		memory = MemoryManager()
		if memory.has_signal("chronicle_blocked_by_ide"):
			memory.evaporate_signals("chronicle_blocked_by_ide")
			logger.info("Señal 'chronicle_blocked_by_ide' evaporada: no queda backlog recuperable.")
	except Exception as exc:
		logger.debug(f"No se pudo evaporar la señal de deuda: {exc}")


def _signal_offline_debt(pending: list[Path]) -> None:
	"""Declara la deuda cuando el IDE está cerrado.

	El extractor solo puede hablar con el LanguageServer en caliente, así que un
	IDE cerrado no es un fallo del cron — pero tampoco es gratis: los turnos que
	no se vuelcan acaban purgados por el tope de `INTERACTION_MAX_AGE_DAYS` (30 d)
	sin que nadie se entere. Esta señal convierte esa pérdida silenciosa en deuda
	visible, con enfriamiento de 24 h para no inundar el tablón cada hora.
	"""
	if not pending:
		_evaporate_debt_signal()
		return
	now = time.time()
	ages = [(now - p.stat().st_mtime) / 86400.0 for p in pending]
	age_days = max(0.0, max(ages))
	recoverable = [p for p, age in zip(pending, ages, strict=True) if age < DEBT_RECOVERABLE_DAYS]
	if not recoverable:
		# Backlog permanente: no se declara una deuda que no se puede pagar, y la
		# señal anterior (si la hubo) se entierra.
		logger.info(
			f"Backlog no recuperable: las {len(pending)} conversaciones superan {DEBT_RECOVERABLE_DAYS:.0f} d "
			"y solo queda su puntero cifrado; se archivarán si el IDE vuelve a exponerlas."
		)
		_evaporate_debt_signal()
		return
	logger.warning(
		f"LanguageServer no detectado (IDE cerrado): {len(pending)} conversación(es) sin volcar; "
		f"la más antigua espera {age_days:.1f} d."
	)

	state: Path = get_state_dir() / DEBT_STATE_FILE
	try:
		previous = json.loads(state.read_text(encoding="utf-8"))
	except Exception:
		previous = {}
	try:
		last_signaled = float(previous.get("signaled_at") or 0)
	except (TypeError, ValueError):
		last_signaled = 0.0
	if now - last_signaled < DEBT_COOLDOWN_S:
		logger.info("Deuda ya declarada en las últimas 24 h; no se repite la señal.")
		return

	oldest_recoverable = max(age for p, age in zip(pending, ages, strict=True) if p in recoverable)
	intensity = 9.0 if oldest_recoverable >= DEBT_PURGE_WARN_DAYS else 7.0 if oldest_recoverable >= 7.0 else 4.0
	try:
		from red_pill.memory import MemoryManager

		MemoryManager().inject_signal(
			name="chronicle_blocked_by_ide",
			intensity=intensity,
			signal_type="pain",
			source="ChronicleExtractor",
			message=(
				f"{len(recoverable)} conversación(es) del IDE sin volcar (de {len(pending)} en cola):"
				" el extractor necesita el LanguageServer y el IDE está cerrado."
				f" La más antigua recuperable espera {oldest_recoverable:.1f} d"
				" (el buffer de interacción purga a los 30 d)."
			),
		)
	except Exception as exc:
		logger.warning(f"Señal de deuda no inyectada: {exc}")
		return

	try:
		state.parent.mkdir(parents=True, exist_ok=True)
		state.write_text(
			json.dumps({"signaled_at": time.time(), "pending": len(pending), "oldest_days": round(age_days, 1)}),
			encoding="utf-8",
		)
	except Exception as exc:
		logger.debug(f"No se pudo persistir el estado de la señal: {exc}")


def run_extraction():
	conv_dir = get_antigravity_conversations_dir()
	out_dir = get_unencrypted_conversations_dir()
	out_dir.mkdir(parents=True, exist_ok=True)

	# 1. Comprobar Idempotencia (mtime)
	needs_export: list[Path] = []
	for pb_file in conv_dir.glob("*.pb"):
		json_file = out_dir / f"{pb_file.stem}.json"

		# Si el JSON no existe, o si el PB es más nuevo
		if not json_file.exists() or pb_file.stat().st_mtime > json_file.stat().st_mtime:
			needs_export.append(pb_file)

	if not needs_export:
		logger.info("Estado Idempotente: Ninguna conversación modificada. Saliendo limpiamente.")
		_evaporate_debt_signal()
		return

	logger.info(f"Detectadas {len(needs_export)} conversaciones nuevas o modificadas.")

	# 2. Descubrir LanguageServer (IDE Abierto)
	servers = discover_language_servers()
	if not servers:
		_signal_offline_debt(needs_export)
		return

	endpoints = find_all_endpoints(servers)
	if not endpoints:
		logger.warning("Servidor de lenguaje encontrado pero puertos inaccesibles.")
		return

	ep = endpoints[0]
	p, c = ep["port"], ep["csrf"]

	# Obtener sumarios para títulos y conteo de pasos
	summaries, cascade_ep, failed_eps = get_all_trajectories_merged(endpoints)

	# 3. Extraer e Inyectar
	exported = 0
	for pb_file in needs_export:
		cid = pb_file.stem
		info = summaries.get(cid, {"summary": "Unknown", "stepCount": 1000})
		try:
			steps = get_trajectory_steps(p, c, cid, step_count=info.get("stepCount", 1000))
			if steps:
				messages = parse_steps(steps, FieldLevel.DEFAULT)
				record = build_conversation_record(cid, info.get("summary", ""), info, messages)

				with open(out_dir / f"{cid}.json", "w", encoding="utf-8") as f:
					json.dump(record, f, indent=2, ensure_ascii=False)
				exported += 1
				logger.info(f"  -> Volcado: {cid[:8]}... ({len(messages)} mensajes)")
		except Exception as e:
			logger.error(f"Fallo al extraer {cid}: {e}")

	logger.info(f"Fase 1 completada: {exported} conversaciones guardadas en {out_dir}")


if __name__ == "__main__":
	run_extraction()
