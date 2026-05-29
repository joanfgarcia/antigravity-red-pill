import sqlite3
from typing import Any, List

from red_pill.core.paths import get_neon_link_db_path
from red_pill.metabolism.auditor import AuditFinding
from red_pill.metabolism.sentinel_plugins.base import SentinelPlugin


class SQLiteCheck(SentinelPlugin):
	@property
	def name(self) -> str:
		return "SQLite Events DB"

	def is_enabled(self, cfg: Any) -> bool:
		return True

	def audit(self, cfg: Any) -> List[AuditFinding]:
		findings = []
		db_path = get_neon_link_db_path()
		if db_path.exists():
			try:
				with sqlite3.connect(db_path, timeout=2) as conn:
					res = conn.execute("PRAGMA integrity_check").fetchone()
					if not res or res[0] != "ok":
						findings.append(AuditFinding(type="amnesia", severity=10.0, message="SQLite events.db is CORRUPTED"))
			except Exception as e:
				findings.append(AuditFinding(type="amnesia", severity=10.0, message=f"SQLite events.db is LOCKED/UNREADABLE: {e}"))
		return findings

	def heal(self, cfg: Any, finding: AuditFinding) -> bool:
		"""Curación: SQLite suele requerir intervención manual si se corrompe."""
		# Se podría intentar un .dump y restore automático en el futuro.
		return False
