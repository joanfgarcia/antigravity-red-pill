import os
import subprocess
import urllib.error
import urllib.request
from typing import Any, List

from red_pill.metabolism.auditor import AuditFinding
from red_pill.metabolism.sentinel_plugins.base import SentinelPlugin


class NeonLinkCheck(SentinelPlugin):
	@property
	def name(self) -> str:
		return "Neon-Link Telegram Bridge"

	def is_enabled(self, cfg: Any) -> bool:
		return getattr(cfg, "NEON_LINK_ENABLED", True)

	def audit(self, cfg: Any) -> List[AuditFinding]:
		findings = []
		try:
			urllib.request.urlopen(cfg.NEON_LINK_URL, timeout=2)
		except Exception as e:
			if not isinstance(e, urllib.error.HTTPError):
				findings.append(AuditFinding(type="blindness", severity=10.0, message=f"Neon-Link Bridge is HUNG/OFFLINE: {e}"))
		return findings

	def heal(self, cfg: Any, finding: AuditFinding) -> bool:
		"""Auto-curación: Reiniciar neon-link vía systemd o relanzar start.sh."""
		import shutil
		if shutil.which("systemctl"):
			try:
				subprocess.run(["systemctl", "--user", "restart", "neon-link.service"], check=False, timeout=15)
				return True
			except Exception:
				pass

		try:
			subprocess.run(["pkill", "-f", "neon-link"], check=False)
			from red_pill.core.paths import get_bunker_root
			neon_dir = str(get_bunker_root().parent / "neon-link")
			start_script = os.path.join(neon_dir, "start.sh")

			if os.path.exists(start_script):
				subprocess.Popen(["nohup", start_script], cwd=neon_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=os.setpgrp)
				return True
		except Exception:
			pass
		return False
