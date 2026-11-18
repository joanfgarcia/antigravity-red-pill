"""HygienePhase: purge empty engrams (zero recall value, real graph cost).

CPU-only. Runs after OrphanPromotion (a hub-less parent's chunk gets promoted
BEFORE hygiene judges the family) and before the AxonWeaver (never weave
what is about to vanish). Chain-restitching semantics in purge_empty_engrams.
"""

import logging

import red_pill.config as cfg
from red_pill.metabolism.maintenance import purge_empty_engrams
from red_pill.metabolism.phases.base import SleepContext, SleepPhase

logger = logging.getLogger(__name__)


class HygienePhase(SleepPhase):
	@property
	def name(self) -> str:
		return "hygiene"

	def execute(self, ctx: SleepContext) -> None:
		"""Retira engramas VACÍOS (sin contenido), no memoria (RFC-OLV-001 §7).

		No es una ruta de olvido: no decide por uso ni por edad, y un engrama con
		contenido nunca entra aquí. Se conserva porque borrar registros sin
		contenido no es olvidar, es higiene; y respeta `immune` y `permastore`.
		"""
		if not cfg.SLEEP_PLUGIN_HYGIENE:
			logger.debug("[HYGIENE] Skipped (SLEEP_PLUGIN_HYGIENE=False)")
			return
		try:
			apply = bool(getattr(cfg, "SW_HYGIENE_PURGE_ENABLED", False))
			report = purge_empty_engrams(ctx.memory_manager, dry_run=not apply) or {}
		except Exception as e:
			logger.error(f"[HYGIENE] Failed to run empty-engram purge: {e}")
			return
		purged = sum(int((r or {}).get("empty_purged", 0) or 0) for r in report.values() if isinstance(r, dict))
		# MET-001: residuos de marcadores. Va DESPUÉS de la purga a propósito: si
		# la purga deja una sesión con un solo miembro, el marcador que sobrevive
		# queda residuo en la misma pasada, no en la siguiente.
		repaired = 0
		if bool(getattr(cfg, "SW_HUB_MARKER_REPAIR_ENABLED", True)):
			try:
				from red_pill.metabolism.hub_synthesis import repair_stale_orphan_markers

				repair = repair_stale_orphan_markers(ctx.memory_manager) or {}
				repaired = int(repair.get("cleared") or 0)
				if repaired:
					logger.info(f"[HYGIENE] {repaired} marcador(es) huérfano(s) residuo limpiados.")
			except Exception as e:
				logger.error(f"[HYGIENE] Failed to repair stale hub markers: {e}")
		ctx.record(self.name, purged, purged=purged, markers_cleared=repaired)
