"""
Sentinel Plugin: Syntax Guard (py_compile)

Zero-cost, zero-token syntax validation of critical Python modules.
Detects IndentationError/SyntaxError BEFORE systemd timers hit them.

Uses py_compile (no execution, no imports, ~0ms per file) and tracks
mtime to avoid redundant checks.

Severity: 9.5 (higher than ruff/mypy because syntax errors brick ALL services).
Auto-heal: restores the last committed version from git HEAD.
"""

import json
import logging
import os
import py_compile
import subprocess
from typing import Any, Dict, List

from red_pill.metabolism.auditor import AuditFinding
from red_pill.metabolism.sentinel_plugins.base import SentinelPlugin

logger = logging.getLogger(__name__)

# Critical modules that, if broken, cascade-crash all systemd services.
# Paths relative to APP_ROOT.
CRITICAL_MODULES = [
	"src/red_pill/config.py",
	"src/red_pill/heartbeat.py",
	"src/red_pill/memory.py",
	"src/red_pill/core/paths.py",
	"src/red_pill/core/storage.py",
	"src/red_pill/core/inbox.py",
	"src/red_pill/core/p2p_sync.py",
	"src/red_pill/core/queue_worker.py",
	"src/red_pill/metabolism/auditor.py",
	"src/red_pill/metabolism/sleep.py",
	"src/red_pill/plugins/antigravity_ide/worker.py",
	"src/red_pill/plugins/antigravity_ide/bridge.py",
	"src/red_pill/plugins/antigravity_ide/factory.py",
	"src/red_pill/plugins/antigravity_ide/grpc_bridge.py",
	"src/red_pill/plugins/antigravity_ide/agy_bridge.py",
	"src/red_pill/plugins/antigravity_ide/telegram_session.py",
	"src/red_pill/swarm/daemon.py",
	"src/red_pill/mcp_server.py",
	"src/red_pill/interceptors/05_cognitive_router.py",
	"src/red_pill/interceptors/06_tone_adapter.py",
	"src/red_pill/interceptors/07_mood_analytics.py",
	"src/red_pill/interceptors/11_pre_heating.py",
	"src/red_pill/cognitive/queue_manager.py",
	"src/red_pill/cognitive/drive_evaluator.py",
]


class SyntaxGuardCheck(SentinelPlugin):
	"""Ultra-lightweight syntax validation using py_compile.

	- Tracks per-file mtime to skip unchanged files (O(1) stat calls).
	- On failure: fires pain signal with severity 9.5.
	- Auto-heal: restores file from git HEAD.
	"""

	def __init__(self):
		from red_pill.core.paths import get_data_dir

		self._mtime_cache_path = get_data_dir() / "syntax_guard_mtime.json"
		self._mtime_cache: Dict[str, float] = self._load_mtime_cache()

	@property
	def name(self) -> str:
		return "Syntax Guard (py_compile)"

	def is_enabled(self, cfg: Any) -> bool:
		return True  # Always enabled — zero cost

	def _load_mtime_cache(self) -> Dict[str, float]:
		if self._mtime_cache_path.exists():
			try:
				with open(self._mtime_cache_path, "r") as f:
					data = json.load(f)
					if isinstance(data, dict):
						return {str(k): float(v) for k, v in data.items()}
			except Exception:
				pass
		return {}

	def _save_mtime_cache(self):
		try:
			self._mtime_cache_path.parent.mkdir(parents=True, exist_ok=True)
			with open(self._mtime_cache_path, "w") as f:
				json.dump(self._mtime_cache, f)
		except Exception as e:
			logger.warning(f"[SyntaxGuard] Failed to save mtime cache: {e}")

	def audit(self, cfg: Any) -> List[AuditFinding]:
		findings: List[AuditFinding] = []
		app_root = getattr(cfg, "APP_ROOT", "")
		if not app_root or not os.path.isdir(app_root):
			return findings

		checked = 0
		skipped = 0

		for rel_path in CRITICAL_MODULES:
			abs_path = os.path.join(app_root, rel_path)
			if not os.path.isfile(abs_path):
				continue

			# mtime differential — skip unchanged files
			try:
				current_mtime = os.path.getmtime(abs_path)
			except OSError:
				continue

			cached_mtime = self._mtime_cache.get(abs_path, 0.0)
			if current_mtime <= cached_mtime:
				skipped += 1
				continue

			# py_compile: syntax-only, no execution, no imports
			try:
				py_compile.compile(abs_path, doraise=True)
				# File compiles OK — update cache
				self._mtime_cache[abs_path] = current_mtime
				checked += 1
			except py_compile.PyCompileError as e:
				error_msg = str(e)
				# Extract just the error type and location
				short_msg = error_msg.split("\n")[0] if "\n" in error_msg else error_msg
				findings.append(
					AuditFinding(
						type="syntax",
						severity=9.5,
						message=f"SYNTAX BROKEN: {rel_path}\n{short_msg}",
						metadata={
							"file": abs_path,
							"rel_path": rel_path,
							"error": error_msg,
						},
					)
				)
				# Do NOT update mtime cache for broken files — recheck every cycle
				logger.error(f"[SyntaxGuard] 🔴 {rel_path}: {short_msg}")

		if checked > 0 or skipped > 0:
			logger.info(f"[SyntaxGuard] Checked {checked} files, skipped {skipped} unchanged, {len(findings)} broken")

		self._save_mtime_cache()
		return findings

	def heal(self, cfg: Any, finding: AuditFinding) -> bool:
		"""Auto-heal: restore the broken file from git HEAD."""
		abs_path = finding.metadata.get("file", "")
		rel_path = finding.metadata.get("rel_path", "")
		app_root = getattr(cfg, "APP_ROOT", "")

		if not abs_path or not app_root:
			return False

		try:
			# Restore from git HEAD
			result = subprocess.run(
				["git", "checkout", "HEAD", "--", rel_path],
				cwd=app_root,
				capture_output=True,
				text=True,
				timeout=10,
			)

			if result.returncode == 0:
				# Verify the restored file compiles
				py_compile.compile(abs_path, doraise=True)
				# Update mtime cache with the restored file
				self._mtime_cache[abs_path] = os.path.getmtime(abs_path)
				self._save_mtime_cache()
				logger.info(f"[SyntaxGuard] ✅ Auto-healed {rel_path} from git HEAD")
				return True
			else:
				logger.error(f"[SyntaxGuard] git checkout failed: {result.stderr}")
				return False
		except Exception as e:
			logger.error(f"[SyntaxGuard] Auto-heal failed for {rel_path}: {e}")
			return False
