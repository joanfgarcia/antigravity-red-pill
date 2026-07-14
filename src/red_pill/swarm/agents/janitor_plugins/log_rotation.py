import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from red_pill.swarm.agents.janitor_plugins.base import JanitorPlugin

logger = logging.getLogger(__name__)


class LogRotationPlugin(JanitorPlugin):
	@property
	def name(self) -> str:
		return "log_rotation"

	async def execute(self, janitor: Any, config_dict: dict, **kwargs) -> Dict[str, Any]:
		janitor.log("[Janitor] Running log_rotation plugin...")
		plugin_cfg = config_dict.get("plugins", {}).get(self.name, {})

		max_size_bytes = plugin_cfg.get("max_size_bytes", 10 * 1024 * 1024)
		days_to_keep = plugin_cfg.get("days_to_keep", 7)

		targets = [
			Path.home() / ".local/share/red-pill/daemon/output.log",
			Path.home() / ".local/share/red-pill/daemon/error.log",
			Path.home() / ".agent/bunker_daemon.log",
			Path.home() / ".agent/bunker_daemon_error.log",
		]
		rotated_count = 0
		purged_count = 0

		for log_path in targets:
			if log_path.exists() and log_path.is_file():
				# 1. Rotate if size exceeds limit or contains old entries
				if self._should_rotate_log(janitor, log_path, max_size_bytes):
					try:
						self._rotate_file_copytruncate(janitor, log_path)
						rotated_count += 1
					except Exception as e:
						logger.error(f"[Janitor] Failed to rotate {log_path}: {e}")
						janitor.log(f"[Janitor] Error rotating {log_path.name}: {e}")

				# 2. Clean up old rotated logs in the same directory
				try:
					purged = self._cleanup_old_rotated_logs(janitor, log_path.parent, log_path.name, days_to_keep)
					purged_count += purged
				except Exception as e:
					logger.error(f"[Janitor] Failed to cleanup rotated logs for {log_path}: {e}")
					janitor.log(f"[Janitor] Error cleaning up old logs for {log_path.name}: {e}")

		return {"logs_rotated": rotated_count, "old_logs_purged": purged_count}

	def _should_rotate_log(self, janitor: Any, log_path: Path, max_size_bytes: int) -> bool:
		if log_path.stat().st_size > max_size_bytes:
			janitor.log(f"[Janitor] Log file {log_path.name} exceeds size limit. Rotating...")
			return True
		try:
			with open(log_path, "r", errors="ignore") as f:
				first_line = f.readline()
			if first_line and len(first_line) >= 10:
				date_str = first_line[:10]
				dt = datetime.strptime(date_str, "%Y-%m-%d")
				age = datetime.now() - dt
				if age.days >= 1:
					janitor.log(f"[Janitor] Log file {log_path.name} contains old entries ({date_str}). Rotating...")
					return True
		except Exception:
			pass
		return False

	def _rotate_file_copytruncate(self, janitor: Any, log_path: Path):
		# Standard rotation logic: Shift backups log.3 -> log.4, log.2 -> log.3, log.1 -> log.2
		for i in range(3, 0, -1):
			old_file = log_path.with_name(f"{log_path.name}.{i}")
			new_file = log_path.with_name(f"{log_path.name}.{i + 1}")
			if old_file.exists():
				try:
					if new_file.exists():
						new_file.unlink()
					old_file.rename(new_file)
				except Exception as e:
					logger.error(f"[Janitor] Failed to shift log backup {old_file} to {new_file}: {e}")

		# Copy active to log.1
		backup_1 = log_path.with_name(f"{log_path.name}.1")
		try:
			shutil.copy2(log_path, backup_1)
		except Exception as e:
			logger.error(f"[Janitor] Failed to copy {log_path} to {backup_1}: {e}")
			raise e

		# Truncate active file in-place
		try:
			with open(log_path, "w"):
				pass
			janitor.log(f"[Janitor] Truncated active log {log_path.name} after backup.")
		except Exception as e:
			logger.error(f"[Janitor] Failed to truncate {log_path}: {e}")
			raise e

	def _cleanup_old_rotated_logs(self, janitor: Any, folder: Path, base_name: str, days: int) -> int:
		purged_count = 0
		cutoff_time = datetime.now().timestamp() - (days * 86400)
		for item in folder.iterdir():
			if item.is_file() and item.name.startswith(base_name) and item.name != base_name:
				# It is a rotated log file (e.g. log.1, log.2)
				try:
					if item.stat().st_mtime < cutoff_time:
						item.unlink()
						purged_count += 1
						janitor.log(f"[Janitor] Deleted old rotated log: {item.name}")
				except Exception as e:
					logger.error(f"[Janitor] Failed to delete rotated log {item}: {e}")
		return purged_count
