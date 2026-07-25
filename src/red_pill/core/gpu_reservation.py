import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import psutil

from red_pill.core.paths import get_daemon_dir

logger = logging.getLogger(__name__)


class GpuReservationManager:
	@staticmethod
	def get_reservations_file() -> Path:
		return get_daemon_dir() / "gpu_reservations.json"

	@classmethod
	def load_reservations(cls) -> List[Dict[str, Any]]:
		file_path = cls.get_reservations_file()
		if not file_path.exists():
			return []
		try:
			with open(file_path, "r", encoding="utf-8") as f:
				data = json.load(f)
				return data.get("reservations", []) if data is not None else []
		except Exception as e:
			logger.warning(f"[GPU-RESERVE] Failed to load reservations: {e}")
			return []

	@classmethod
	def save_reservations(cls, reservations: List[Dict[str, Any]]):
		file_path = cls.get_reservations_file()
		try:
			with open(file_path, "w", encoding="utf-8") as f:
				json.dump({"reservations": reservations}, f, indent=2)
		except Exception as e:
			logger.error(f"[GPU-RESERVE] Failed to save reservations: {e}")

	@classmethod
	def clean_and_get_active(cls) -> List[Dict[str, Any]]:
		reservations = cls.load_reservations()
		active = []
		dirty = False
		for res in reservations:
			pid = res.get("pid")
			create_time = res.get("create_time")
			alive = False
			if pid:
				try:
					if psutil.pid_exists(pid):
						p = psutil.Process(pid)
						# Verify create_time matches to guard against PID recycling
						if create_time is None or abs(p.create_time() - create_time) < 1.0:
							alive = True
				except Exception:
					pass
			if alive:
				active.append(res)
			else:
				logger.info(f"[GPU-RESERVE] Pruning stale reservation from dead PID {pid} ({res.get('owner')})")
				dirty = True
		if dirty:
			cls.save_reservations(active)
		return active

	@classmethod
	def reserve(cls, owner: str, vram_mb: int, exclusive: bool = False, pid: Optional[int] = None) -> bool:
		if pid is None:
			pid = os.getpid()

		create_time = None
		try:
			create_time = psutil.Process(pid).create_time()
		except Exception:
			pass

		active = cls.clean_and_get_active()

		# Check if there is an existing reservation for this PID, update it
		for res in active:
			if res.get("pid") == pid:
				res["vram_mb"] = vram_mb
				res["exclusive"] = exclusive
				res["owner"] = owner
				res["create_time"] = create_time
				res["created_at"] = time.time()
				cls.save_reservations(active)
				return True

		# Otherwise, add a new one
		active.append({"pid": pid, "owner": owner, "vram_mb": vram_mb, "exclusive": exclusive, "create_time": create_time, "created_at": time.time()})
		cls.save_reservations(active)
		logger.info(f"[GPU-RESERVE] Reserved {vram_mb} MB (exclusive={exclusive}) for PID {pid} ({owner})")
		return True

	@classmethod
	def release(cls, pid: Optional[int] = None) -> bool:
		if pid is None:
			pid = os.getpid()
		reservations = cls.load_reservations()
		filtered = [r for r in reservations if r.get("pid") != pid]
		if len(filtered) < len(reservations):
			cls.save_reservations(filtered)
			logger.info(f"[GPU-RESERVE] Released reservation for PID {pid}")
			return True
		return False

	@classmethod
	def get_total_reserved_mb(cls, exclude_pid: Optional[int] = None) -> int:
		active = cls.clean_and_get_active()
		total = 0
		for res in active:
			if exclude_pid is not None and res.get("pid") == exclude_pid:
				continue
			if res.get("exclusive", False):
				return -1
			total += res.get("vram_mb", 0)
		return total

	@classmethod
	def is_exclusive_active(cls, exclude_pid: Optional[int] = None) -> bool:
		active = cls.clean_and_get_active()
		return any(res.get("exclusive", False) for res in active if (exclude_pid is None or res.get("pid") != exclude_pid))
