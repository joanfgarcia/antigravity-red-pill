import logging
import subprocess

logger = logging.getLogger(__name__)


class SovereignNotifier:
	"""
	Centralized notification dispatcher for the Red-Pill ecosystem.
	Handles both Operator-facing OS desktop notifications (GNOME/KDE)
	and AI-facing internal Bünker signals.
	"""

	@staticmethod
	def notify_os(
		title: str,
		message: str,
		icon: str = "dialog-information",
		urgency: str = "normal",
		sound: bool = False,
		category: str = "general",
	) -> None:
		"""Sends a desktop notification to the Operator via the OS."""
		import red_pill.config as cfg

		if not getattr(cfg, "NOTIFICATIONS_ENABLED", True):
			return

		try:
			hint = f"string:x-canonical-private-synchronous:red-pill-{category}"
			op_name = getattr(cfg, "OPERATOR_DISPLAY_NAME", "Operator")

			cmd = [
				"notify-send",
				"-a",
				"Red-Pill",
				"-i",
				icon,
				"-u",
				urgency,
				"-h",
				hint,
				title,
				f"{op_name}, {message}",
			]
			subprocess.run(cmd, check=False)

			if sound and getattr(cfg, "NOTIFICATION_SOUND", False):
				subprocess.run(
					["speaker-test", "-t", "sine", "-f", "980", "-l", "1"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
				)

		except Exception as e:
			logger.debug(f"[SovereignNotifier] OS notification failed: {e}")

	@staticmethod
	def notify_bunker(
		memory_manager,
		signal_name: str,
		intensity: float = 1.0,
		signal_type: str = "status",
		source: str = "SYSTEM",
	) -> None:
		"""Injects a cognitive signal into the Cortex to notify the AI of a system event."""
		try:
			memory_manager.inject_signal(
				signal_name,
				intensity=intensity,
				signal_type=signal_type,
				source=source,
			)
			logger.info(f"[SovereignNotifier] Injected signal: {signal_name}")
		except Exception as e:
			logger.error(f"[SovereignNotifier] Failed to inject signal: {e}")

	@staticmethod
	def clear_bunker_signal(memory_manager, signal_name: str) -> None:
		"""Evaporates an active signal from the Cortex."""
		try:
			memory_manager.evaporate_signals(signal_name)
			logger.info(f"[SovereignNotifier] Evaporated signal: {signal_name}")
		except Exception as e:
			logger.error(f"[SovereignNotifier] Failed to evaporate signal: {e}")
