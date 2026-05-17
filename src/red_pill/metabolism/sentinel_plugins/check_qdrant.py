import subprocess
import urllib.error
import urllib.request
from typing import Any, List

from red_pill.metabolism.auditor import AuditFinding
from red_pill.metabolism.sentinel_plugins.base import SentinelPlugin


class QdrantCheck(SentinelPlugin):
    @property
    def name(self) -> str:
        return "Qdrant Vector DB"

    def is_enabled(self, cfg: Any) -> bool:
        return True  # Core service, always enabled

    def audit(self, cfg: Any) -> List[AuditFinding]:
        findings = []
        try:
            # Assuming QDRANT_URL or default to localhost:6333
            url = getattr(cfg, "QDRANT_URL", "http://localhost:6333")
            urllib.request.urlopen(url, timeout=2)
        except Exception:
            findings.append(
                AuditFinding(type="amnesia", severity=10.0, message="Qdrant Vector DB is UNREACHABLE")
            )
        return findings

    def heal(self, cfg: Any, finding: AuditFinding) -> bool:
        """Intento de curación para Qdrant (Systemd user service)"""
        try:
            # Intentar reiniciar el podman/systemd container de qdrant
            subprocess.run(["systemctl", "--user", "restart", "qdrant.service"], check=False)
            return True
        except Exception:
            return False
