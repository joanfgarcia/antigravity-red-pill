import glob
import logging
import os
import signal
import sqlite3
import subprocess
from pathlib import Path
from typing import Any, List, Optional

from red_pill.core.paths import get_neon_link_db_path, get_queue_dir
from red_pill.metabolism.auditor import AuditFinding
from red_pill.metabolism.sentinel_plugins.base import SentinelPlugin

logger = logging.getLogger("redpill.sentinel.sqlite")


def find_processes_holding_file(file_path: str) -> List[int]:
	pids = []
	try:
		abs_path = os.path.abspath(file_path)
		paths_to_check = {abs_path, abs_path + "-wal", abs_path + "-shm"}
		for proc_dir in glob.glob("/proc/[0-9]*"):
			try:
				pid = int(os.path.basename(proc_dir))
				fd_dir = os.path.join(proc_dir, "fd")
				if os.path.isdir(fd_dir):
					for fd in os.listdir(fd_dir):
						fd_path = os.path.join(fd_dir, fd)
						if os.path.islink(fd_path):
							target = os.readlink(fd_path)
							if target in paths_to_check:
								pids.append(pid)
								break
			except (OSError, ValueError, PermissionError):
				continue
	except Exception as e:
		logger.error(f"Error scanning proc files: {e}")
	return pids


def get_pid_systemd_unit(pid: int) -> Optional[str]:
	try:
		with open(f"/proc/{pid}/cgroup", "r") as f:
			for line in f:
				if ".service" in line:
					parts = line.strip().split("/")
					for p in parts:
						if p.endswith(".service"):
							return p.replace("\\x2d", "-")
	except Exception:
		pass
	return None


def get_pid_command(pid: int) -> str:
	try:
		with open(f"/proc/{pid}/cmdline", "r") as f:
			return f.read().replace("\x00", " ").strip()
	except Exception:
		return ""


class SQLiteCheck(SentinelPlugin):
	@property
	def name(self) -> str:
		return "SQLite DBs Check"

	def is_enabled(self, cfg: Any) -> bool:
		return True

	def audit(self, cfg: Any) -> List[AuditFinding]:
		findings = []

		dbs = [
			("events.db", get_neon_link_db_path()),
			("bunker_queue.db", get_queue_dir() / "bunker_queue.db"),
			("minion_inbox.db", get_queue_dir() / "minion_inbox.db"),
		]

		for name, db_path in dbs:
			if db_path.exists():
				try:
					with sqlite3.connect(db_path, timeout=2.0) as conn:
						res = conn.execute("PRAGMA integrity_check").fetchone()
						if not res or res[0] != "ok":
							findings.append(
								AuditFinding(
									type="amnesia",
									severity=10.0,
									message=f"SQLite {name} is CORRUPTED",
									metadata={"db_path": str(db_path), "error_type": "corrupted", "db_name": name},
								)
							)
				except sqlite3.OperationalError as e:
					err_msg = str(e).lower()
					if "locked" in err_msg or "busy" in err_msg:
						findings.append(
							AuditFinding(
								type="amnesia",
								severity=10.0,
								message=f"SQLite {name} is LOCKED: {e}",
								metadata={"db_path": str(db_path), "error_type": "locked", "db_name": name},
							)
						)
					else:
						findings.append(
							AuditFinding(
								type="amnesia",
								severity=10.0,
								message=f"SQLite {name} is UNREADABLE: {e}",
								metadata={"db_path": str(db_path), "error_type": "corrupted", "db_name": name},
							)
						)
				except Exception as e:
					findings.append(
						AuditFinding(
							type="amnesia",
							severity=10.0,
							message=f"SQLite {name} is UNREADABLE: {e}",
							metadata={"db_path": str(db_path), "error_type": "corrupted", "db_name": name},
						)
					)
		return findings

	def heal(self, cfg: Any, finding: AuditFinding) -> bool:
		db_path_str = finding.metadata.get("db_path")
		error_type = finding.metadata.get("error_type")
		db_name = finding.metadata.get("db_name", "unknown")

		if not db_path_str or not os.path.exists(db_path_str):
			return False

		db_path = Path(db_path_str)

		if error_type == "locked":
			logger.warning(f"Auto-Healer: Attempting to resolve SQLite lock on {db_name} ({db_path})")
			pids = find_processes_holding_file(db_path_str)
			if not pids:
				logger.info(f"Auto-Healer: No processes found holding files for {db_name}. Running checkpoint.")
			else:
				logger.info(f"Auto-Healer: Found lock holders for {db_name}: {pids}")

			restarted_units = set()
			for pid in pids:
				if pid == os.getpid():
					continue

				cmd = get_pid_command(pid)
				unit = get_pid_systemd_unit(pid)

				if unit:
					if unit not in restarted_units:
						logger.info(f"Auto-Healer: PID {pid} ({cmd}) belongs to unit {unit}. Restarting unit...")
						subprocess.run(["systemctl", "--user", "restart", unit], capture_output=True)
						restarted_units.add(unit)
				else:
					if "red_pill" in cmd or "python" in cmd:
						logger.info(f"Auto-Healer: Killing orphan lock holder PID {pid} ({cmd})...")
						try:
							os.kill(pid, signal.SIGTERM)
							import time

							time.sleep(0.5)
							try:
								os.kill(pid, 0)
								os.kill(pid, signal.SIGKILL)
							except OSError:
								pass
						except OSError as e:
							logger.error(f"Auto-Healer: Failed to kill PID {pid}: {e}")

			# Force checkpoint WAL truncation
			try:
				with sqlite3.connect(db_path, timeout=5.0) as conn:
					conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
				logger.info(f"Auto-Healer: Checkpoint TRUNCATE executed successfully for {db_name}.")
				return True
			except Exception as e:
				logger.error(f"Auto-Healer: Checkpoint failed for {db_name} after restarting processes: {e}")
				return False

		elif error_type == "corrupted":
			logger.warning(f"Auto-Healer: Attempting to heal corrupted SQLite database {db_name} ({db_path})")

			pids = find_processes_holding_file(db_path_str)
			for pid in pids:
				if pid == os.getpid():
					continue
				cmd = get_pid_command(pid)
				unit = get_pid_systemd_unit(pid)
				if unit:
					logger.info(f"Auto-Healer: Restarting lock holder unit {unit} during corruption recovery...")
					subprocess.run(["systemctl", "--user", "restart", unit], capture_output=True)
				else:
					if "red_pill" in cmd or "python" in cmd:
						logger.info(f"Auto-Healer: Killing lock holder PID {pid} during corruption recovery...")
						try:
							os.kill(pid, signal.SIGKILL)
						except OSError:
							pass

			import time

			time.sleep(0.5)

			try:
				corrupt_bak = db_path.with_name(db_path.name + ".corrupted_bak")
				if corrupt_bak.exists():
					corrupt_bak.unlink()
				db_path.rename(corrupt_bak)
				logger.info(f"Auto-Healer: Moved corrupted DB to {corrupt_bak}")

				for ext in ["-wal", "-shm"]:
					sidecar = Path(db_path_str + ext)
					if sidecar.exists():
						sidecar.rename(Path(db_path_str + ext + ".corrupted_bak"))
						logger.info(f"Auto-Healer: Moved corrupted sidecar {sidecar} to bak")

				if db_name == "minion_inbox.db":
					from red_pill.core.inbox import MinionInbox

					_ = MinionInbox(db_path=db_path_str)
					logger.info("Auto-Healer: MinionInbox reconstructed successfully.")
				elif db_name == "bunker_queue.db":
					from red_pill.core.queue_manager import MemoryQueueManager

					_ = MemoryQueueManager(db_path=db_path_str)
					from red_pill.cognitive.queue_manager import CognitiveQueueManager

					_ = CognitiveQueueManager(db_path=db_path_str)
					logger.info("Auto-Healer: bunker_queue.db constructed successfully.")
				else:
					with sqlite3.connect(db_path, timeout=5.0) as conn:
						conn.execute("PRAGMA journal_mode=WAL;")
						conn.execute("PRAGMA synchronous=NORMAL;")
					logger.info(f"Auto-Healer: Recreated empty database for {db_name}")

				return True
			except Exception as e:
				logger.error(f"Auto-Healer: Failed to recreate database {db_name}: {e}")
				return False

		return False
