import logging
from pathlib import Path

from red_pill.core.paths import get_bunker_root

logger = logging.getLogger(__name__)


class SovereignKillSwitch:
	"""
	Sistema de seguridad de emergencia para la Autonomía Cognitiva.
	Utiliza comprobaciones a nivel de sistema de archivos (ultrarrápidas e
	inmunes a bloqueos de base de datos).
	"""

	def __init__(self, workspace: str | None = None):
		if not workspace:
			workspace = str(get_bunker_root())

		self.lock_file = Path(workspace) / "AUTONOMY_KILL.lock"

	def is_engaged(self) -> bool:
		"""
		Retorna True si la autonomía está cortada (el archivo existe).
		Operación O(1) a nivel de SO (stat).
		"""
		return self.lock_file.exists()

	def engage(self, reason: str = "EMERGENCY_MANUAL_OVERRIDE") -> None:
		"""Activa el cortacorrientes."""
		try:
			with open(self.lock_file, "w") as f:
				f.write(f"AUTONOMY HALTED.\nReason: {reason}\n")
			logger.critical(f"[KILL-SWITCH] ENGAGED. Autonomous operations halted. Reason: {reason}")
		except Exception as e:
			logger.error(f"[KILL-SWITCH] FAILED TO ENGAGE: {e}")

	def disengage(self) -> None:
		"""Restaura la corriente."""
		if self.lock_file.exists():
			try:
				self.lock_file.unlink()
				logger.info("[KILL-SWITCH] DISENGAGED. Autonomy restored.")
			except Exception as e:
				logger.error(f"[KILL-SWITCH] FAILED TO DISENGAGE: {e}")
