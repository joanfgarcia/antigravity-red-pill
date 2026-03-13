import subprocess

import red_pill.config as cfg


def notify_user(title: str, message: str, sound: bool = False, category: str = "general"):
	"""
	Sends a system notification and optionally plays a subtle sound.
	- category: used to group/replace notifications (x-canonical-private-synchronous)
	"""
	if not cfg.NOTIFICATIONS_ENABLED:
		return

	try:
		# Tone Calibration: Soft, intuitive, sensory
		# SEC-002: Operator name read from cfg.OPERATOR_DISPLAY_NAME (env: USER_NAME)
		# Hint: x-canonical-private-synchronous allows grouping notifications (in-place update)
		hint = f"string:x-canonical-private-synchronous:red-pill-{category}"
		subprocess.run(["notify-send", "-i", "face-angel", "-h", hint, title, f"{cfg.OPERATOR_DISPLAY_NAME}, {message}"], check=False)

		if sound and cfg.NOTIFICATION_SOUND:
			# A soft rising sweep (880Hz to 1100Hz) - Sensory notification
			subprocess.run(["speaker-test", "-t", "sine", "-f", "980", "-l", "1"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)

	except Exception:
		pass  # Never let notification failure stop the flow


if __name__ == "__main__":
	notify_user("Red Pill: Task Complete", "The heavy neural audit has finished successfully.")
